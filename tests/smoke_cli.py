"""CLI help exits without a runtime; SteamVR launch arguments remain tolerated."""
import contextlib
import io
import pathlib
import sys
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vrclt import __main__ as cli


def invoke(argv):
    output, errors = io.StringIO(), io.StringIO()
    with (patch.object(sys, "argv", ["vrclt", *argv]),
          patch.object(cli, "cmd_run", return_value=7) as run,
          contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors)):
        try:
            cli.main()
        except SystemExit as exc:
            status = exc.code
        else:
            raise AssertionError("CLI did not return an exit status")
    return status, run, output.getvalue(), errors.getvalue()


def main():
    for args in (["--help"], ["-h"], ["run", "--help"]):
        status, run, output, errors = invoke(args)
        assert status == 0 and "usage:" in output and "custom" in output
        assert not errors
        run.assert_not_called()

    for args, expected_app, ignored in (
        ([], None, []),
        (["run", "--app", "custom"], "custom", []),
        (["run", "--vr-process-id=1337"], None, ["--vr-process-id=1337"]),
        (["--steamvr", "steam://rungameid/250820"], None,
         ["--steamvr", "steam://rungameid/250820"]),
    ):
        status, run, _output, _errors = invoke(args)
        assert status == 7, "runtime exit status was not preserved"
        run.assert_called_once()
        parsed = run.call_args.args[0]
        assert parsed.cmd == "run" and parsed.app == expected_app
        assert run.call_args.kwargs == {"ignored_args": ignored}

    print("smoke_cli: OK")


if __name__ == "__main__":
    main()
