"""VRChat chatbox via OSC.

Layout: source text on top, translation below ("src\\ndst"). Messages longer
than the 144-char chatbox limit are split into parts that KEEP the two-line
pairing, and the parts are shown sequentially (chunk_display_sec apart).

Constraints (verified): <=144 chars UTF-8, one message at a time, >=1.5 s
between sends (spam timeout). A new message replaces any unsent parts of the
previous one (newest wins). On stop() the worker sends one final part.
"""
import logging
import math
import threading
import time

from pythonosc.udp_client import SimpleUDPClient

log = logging.getLogger(__name__)

MAX_CHARS = 144
BREAK_CHARS = " ,.!?、。！？…"


def _split_even(text: str, n: int) -> list[str]:
    """Split into n roughly equal parts, preferring word/punctuation breaks."""
    if n <= 1 or not text:
        return [text] if text else []
    size = math.ceil(len(text) / n)
    parts = []
    i = 0
    while i < len(text):
        end = min(len(text), i + size)
        if end < len(text):
            window = text[i:end]
            for k in range(len(window) - 1, max(-1, len(window) - 16), -1):
                if window[k] in BREAK_CHARS:
                    end = i + k + 1
                    break
        part = text[i:end].strip()
        if part:
            parts.append(part)
        i = end
    return parts or [text]


def make_parts(src: str, dst: str, limit: int = MAX_CHARS) -> list[str]:
    """Build chatbox messages: 'src\\ndst' pairs, split into <=limit parts."""
    src, dst = src.strip(), dst.strip()
    if not src and not dst:
        return []
    combined = f"{src}\n{dst}" if (src and dst) else (dst or src)
    if len(combined) <= limit:
        return [combined]
    n = max(2, math.ceil((len(src) + len(dst) + 1) / limit))
    while n <= 9:
        sp = _split_even(src, n)
        dp = _split_even(dst, n)
        count = max(len(sp), len(dp))
        parts = []
        for i in range(count):
            s = sp[i] if i < len(sp) else ""
            d = dp[i] if i < len(dp) else ""
            parts.append(f"{s}\n{d}" if (s and d) else (s or d))
        if all(len(p) <= limit for p in parts):
            return parts
        n += 1
    # pathological fallback: hard truncate each part
    return [p[:limit] for p in parts]


class Chatbox:
    def __init__(self, ip: str = "127.0.0.1", port: int = 9000,
                 throttle_sec: float = 1.5, notification_sfx: bool = False,
                 chunk_display_sec: float = 4.0):
        self._client = SimpleUDPClient(ip, port)
        self._throttle = max(1.5, throttle_sec)
        self._chunk_display = max(self._throttle, chunk_display_sec)
        self._sfx = notification_sfx
        self._pending: list[str] | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="vrclt-chatbox")
        self._thread.start()

    def send(self, text: str) -> None:
        self._enqueue(make_parts("", text))

    def send_pair(self, src: str, dst: str) -> None:
        self._enqueue(make_parts(src, dst))

    def _enqueue(self, parts: list[str]) -> None:
        if not parts:
            return
        with self._lock:
            self._pending = parts
        self._wake.set()

    def typing(self, on: bool) -> None:
        try:
            self._client.send_message("/chatbox/typing", [bool(on)])
        except Exception:
            log.debug("typing indicator send failed", exc_info=True)

    def _run(self) -> None:
        last_send = 0.0
        parts: list[str] = []
        next_interval = self._throttle
        while True:
            # newest message replaces any unsent parts of the previous one
            with self._lock:
                if self._pending is not None:
                    parts = list(self._pending)
                    self._pending = None
                    next_interval = self._throttle
                if not parts:
                    # cleared only while nothing is pending, under the lock
                    self._wake.clear()
            if not parts:
                if self._stop.is_set():
                    return
                self._wake.wait(timeout=0.5)
                continue
            wait = next_interval - (time.time() - last_send)
            if wait > 0:
                if self._stop.is_set():
                    time.sleep(wait)  # respect the throttle for the final send
                else:
                    self._stop.wait(timeout=min(wait, 0.5))
                    continue  # re-check pending / stop
            part = parts.pop(0)
            try:
                self._client.send_message("/chatbox/input", [part, True, self._sfx])
                last_send = time.time()
                log.info("chatbox: %s", part.replace("\n", " | "))
            except Exception:
                log.exception("chatbox send failed")
            next_interval = self._chunk_display
            if self._stop.is_set():
                return  # one final part sent - drop the rest and exit

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        # join must cover one final throttled send
        self._thread.join(timeout=self._chunk_display + 1.0)
