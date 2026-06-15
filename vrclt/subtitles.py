"""Subtitle store: recent finalized lines + a live partial line.

Written by the inbound pipeline (any thread), read by the subtitle overlay.
"""
import collections
import threading
import time


class SubtitleStore:
    def __init__(self, max_lines: int = 3, display_sec: float = 7.0):
        self._lock = threading.Lock()
        self._lines: collections.deque = collections.deque(maxlen=max_lines)
        self._partial: tuple[str, str] = ("", "")
        self._display_sec = display_sec
        self._listeners = []

    def subscribe(self, fn) -> None:
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in self._listeners:
            try:
                fn()
            except Exception:
                pass

    def add_final(self, src: str, dst: str, lang: str) -> None:
        with self._lock:
            self._lines.append((time.time(), src, dst, lang))
            self._partial = ("", "")
        self._notify()

    def set_partial(self, src: str, dst: str) -> None:
        with self._lock:
            self._partial = (src, dst)
        self._notify()

    def snapshot(self):
        """Returns (visible_finals, partial): finals filtered by display time."""
        now = time.time()
        with self._lock:
            finals = [(src, dst, lang) for ts, src, dst, lang in self._lines
                      if (now - ts) <= self._display_sec]
            partial = self._partial
        return finals, partial

    def has_content(self) -> bool:
        finals, partial = self.snapshot()
        return bool(finals or partial[0] or partial[1])
