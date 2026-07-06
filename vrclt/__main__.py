"""vrclt application entry point."""
import argparse
import logging
import sys

from . import config as config_mod
from . import logging_setup
from .app_controller import AppController
from .qt_ui import run_qt_app
from .single_instance import SingleInstance

log = logging.getLogger("vrclt")


def cmd_run(args, ignored_args=None) -> int:
    with SingleInstance() as instance:
        if not instance.acquired:
            SingleInstance.notify_duplicate()
            return 0
        cfg = config_mod.load()
        if args.app:
            cfg.setdefault("app", {})["mode"] = args.app
            cfg = config_mod.apply_app_profile(cfg, force=True)
        log_file = logging_setup.setup(cfg.get("log_level", "INFO"))
        log.info("log file: %s", log_file)
        log.info("config path: %s", config_mod.CONFIG_PATH)
        if ignored_args:
            log.info("ignoring unknown arguments: %s", ignored_args)
        controller = AppController(cfg)
        return run_qt_app(controller, log_file)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vrclt",
        description="VRChat / Discord Live Translator",
    )
    parser.add_argument("cmd", nargs="?", choices=["run"], default="run")
    parser.add_argument("--app", choices=config_mod.APP_MODES)
    # Tolerate anything a SteamVR auto-launch (or shell association) may
    # append: unknown flags fall into `unknown`, and even an unparseable
    # positional must not kill the GUI before it exists.
    argv = sys.argv[1:] or ["run"]
    try:
        args, unknown = parser.parse_known_args(argv)
    except SystemExit:
        args = argparse.Namespace(cmd="run", app=None)
        unknown = argv
    sys.exit(cmd_run(args, ignored_args=unknown))


if __name__ == "__main__":
    main()
