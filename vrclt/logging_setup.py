"""Logging: console + rotating file in %LOCALAPPDATA%/vrclt/logs.

File I/O goes through a QueueListener thread so hot paths never block on disk.
"""
import atexit
import logging
import logging.handlers
import os
import queue
import sys
from pathlib import Path

LOG_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "vrclt" / "logs"


def setup(level: str = "INFO", console: bool | None = None) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "vrclt.log"

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
    file_handler.setFormatter(fmt)

    if console is None:
        console = not getattr(sys, "frozen", False)

    q: "queue.SimpleQueue[logging.LogRecord]" = queue.SimpleQueue()
    handlers = [file_handler]
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        handlers.append(console_handler)
    listener = logging.handlers.QueueListener(q, *handlers, respect_handler_level=True)
    listener.start()
    atexit.register(listener.stop)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(logging.handlers.QueueHandler(q))
    return log_file
