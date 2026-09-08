"""Subtitle store: recent finalized lines + a live partial line.

Written by the inbound pipeline (any thread), read by the subtitle overlay.
"""
import collections
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True, slots=True)
class SubtitleLine:
    """Immutable text plus an optional provider-assigned, session-local speaker.

    Speaker IDs identify turns within the current recognition session; they
    are not account names or persistent identities across reconnects.
    """

    src: str = ""
    dst: str = ""
    lang: str = ""
    speaker_id: str | None = None


def _speaker_id(value) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


class SubtitleStore:
    def __init__(self, max_lines: int = 3, display_sec: float = 7.0):
        self._lock = threading.Lock()
        self._lines: collections.deque = collections.deque(maxlen=max_lines)
        self._partial = SubtitleLine()
        self._display_sec = display_sec
        self._listeners = []

    def subscribe(self, fn) -> None:
        self._listeners.append(fn)

    def unsubscribe(self, fn) -> None:
        try:
            self._listeners.remove(fn)
        except ValueError:
            pass

    def configure(self, max_lines: int, display_sec: float) -> None:
        """Re-apply display settings in place (the store persists across
        runtime restarts so overlay panels can keep their reference)."""
        with self._lock:
            if max_lines != self._lines.maxlen:
                self._lines = collections.deque(self._lines, maxlen=max_lines)
            self._display_sec = display_sec
        self._notify()

    def _notify(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                pass

    def add_final(self, src: str, dst: str, lang: str,
                  speaker_id: str | None = None) -> None:
        line = SubtitleLine(src, dst, lang, _speaker_id(speaker_id))
        with self._lock:
            self._lines.append((time.time(), line))
            # A delayed final for speaker A must not erase speaker B's current
            # partial. Providers without diarization retain the old behavior.
            if (line.speaker_id is None or self._partial.speaker_id is None
                    or self._partial.speaker_id == line.speaker_id):
                self._partial = SubtitleLine()
        self._notify()

    def set_partial(self, src: str, dst: str,
                    speaker_id: str | None = None) -> None:
        line = SubtitleLine(src, dst, speaker_id=_speaker_id(speaker_id))
        with self._lock:
            if self._partial == line:
                return
            self._partial = line
        self._notify()

    def snapshot_with_speakers(self) -> tuple[list[SubtitleLine], SubtitleLine]:
        """Visible immutable finals and partial, including speaker metadata."""
        now = time.time()
        with self._lock:
            finals = [line for ts, line in self._lines
                      if (now - ts) <= self._display_sec]
            partial = self._partial
        return finals, partial

    def snapshot(self):
        """Legacy (final triples, partial pair), with speaker metadata omitted."""
        finals, partial = self.snapshot_with_speakers()
        return ([(line.src, line.dst, line.lang) for line in finals],
                (partial.src, partial.dst))

    def has_content(self) -> bool:
        finals, partial = self.snapshot_with_speakers()
        return bool(finals or partial.src or partial.dst)
