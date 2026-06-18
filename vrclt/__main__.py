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


def cmd_run(args) -> int:
    with SingleInstance() as instance:
        if not instance.acquired:
            SingleInstance.notify_duplicate()
            return 0
        cfg = config_mod.load()
        if args.app:
            cfg.setdefault("app", {})["mode"] = args.app
        log_file = logging_setup.setup(cfg.get("log_level", "INFO"))
        log.info("log file: %s", log_file)
        log.info("config path: %s", config_mod.CONFIG_PATH)
        controller = AppController(cfg)
        return run_qt_app(controller, log_file)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vrclt",
        description="VRChat / Discord Live Translator",
    )
    parser.add_argument("cmd", nargs="?", choices=["run"], default="run")
    parser.add_argument("--app", choices=config_mod.APP_MODES)
    args = parser.parse_args(sys.argv[1:] or ["run"])
    sys.exit(cmd_run(args))


if __name__ == "__main__":
    main()
