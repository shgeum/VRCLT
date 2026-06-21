"""Microphone capture -> 16 kHz mono int16, voice-activity gated.

Only audio during actual speech (RMS over the gate, plus a short pre-roll and
hangover tail) is buffered for sending. This matters for two reasons:

1. Latency/cost: silence is never streamed, so the server isn't fed dead air.
2. Echo: while game audio plays, the echo guard raises the gate, so other
   people's voices bleeding into the mic stay BELOW threshold and are never
   captured as the user's speech - even while a session is already open.

Host-API handling: WASAPI is lowest latency but can be briefly busy when
another app (VRChat) probes the device at startup -> we fall back to
DirectSound/MME, then keep retrying WASAPI in the background and hot-swap up
to it once it's free, so a slow start auto-recovers to low latency.
"""
import collections
import logging
import threading
import time

import numpy as np
import sounddevice as sd

from . import devices

log = logging.getLogger(__name__)

RATE = 16000
CHUNK_MS = 32  # ~512 frames @ 16k
PREROLL_CHUNKS = 6  # ~192 ms kept so speech onsets aren't clipped
UPGRADE_INTERVAL = 6.0  # how often to retry upgrading to WASAPI


class MicCapture:
    def __init__(self, device_substr: str = "", voice_rms_threshold: float = 90.0,
                 hangover_sec: float = 0.5):
        self._device_substr = device_substr
        self._threshold = float(voice_rms_threshold)
        self._hangover = float(hangover_sec)
        # echo guard: callable returning a threshold multiplier (>1 while game
        # audio is playing) so bled-in voices stay below the gate
        self._boost = lambda: 1.0
        # echo suppress: callable returning True while target-app speech should
        # be treated as not-my-voice and never sent to the outbound session.
        self._suppress = lambda: False
        self._suppress_barge_in_multiplier = 0.0
        # gate enable: when False (e.g. passthrough mode), stream everything
        # continuously - no voice gating, so raw audio isn't chopped
        self._gate_enabled = lambda: True
        self._stream: sd.RawInputStream | None = None
        self._current_api: str | None = None
        # ~13 s of audio max; old chunks drop automatically while disconnected
        self.buffer: collections.deque[bytes] = collections.deque(maxlen=400)
        self._raw_taps: list[collections.deque[bytes]] = []
        self._preroll: collections.deque[bytes] = collections.deque(maxlen=PREROLL_CHUNKS)
        self.last_voice_time = 0.0
        self._in_voice = False
        self._blocksize = int(RATE * CHUNK_MS / 1000)
        self._swap_lock = threading.Lock()
        self._upgrade_stop = threading.Event()
        self._upgrade_thread: threading.Thread | None = None

    def set_threshold_boost(self, fn) -> None:
        self._boost = fn

    def set_suppressed(self, fn, *, barge_in_multiplier: float = 0.0) -> None:
        self._suppress = fn
        self._suppress_barge_in_multiplier = max(0.0, float(barge_in_multiplier))

    def set_gate_enabled(self, fn) -> None:
        self._gate_enabled = fn

    def add_raw_tap(self, maxlen: int = 400) -> collections.deque[bytes]:
        tap: collections.deque[bytes] = collections.deque(maxlen=maxlen)
        self._raw_taps.append(tap)
        return tap

    def remove_raw_tap(self, tap: collections.deque[bytes]) -> None:
        try:
            self._raw_taps.remove(tap)
        except ValueError:
            pass

    # ---------------- audio callback ----------------
    def _callback(self, indata, frames, time_info, status):
        if status:
            log.debug("mic status: %s", status)
        data = bytes(indata)
        now = time.time()
        x = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
        try:
            threshold = self._threshold * float(self._boost())
        except Exception:
            threshold = self._threshold
        try:
            suppressed = bool(self._suppress())
        except Exception:
            suppressed = False
        if suppressed:
            barge_mult = self._suppress_barge_in_multiplier
            barge_threshold = self._threshold * barge_mult
            if barge_mult <= 0.0 or rms < barge_threshold:
                self._preroll.clear()
                if self._in_voice and (now - self.last_voice_time) < self._hangover:
                    return
                self.buffer.clear()
                self._in_voice = False
                return
            threshold = min(threshold, barge_threshold)

        for tap in list(self._raw_taps):
            tap.append(data)
        if not self._gate_enabled():
            # passthrough / gate off: stream everything continuously
            self.buffer.append(data)
            self.last_voice_time = now
            self._preroll.append(data)
            return
        # hysteresis: open at `threshold`, but once speaking, stay open down to
        # 40% of it - so weak consonants / brief dips don't chop the stream
        # (which made the translated audio come out choppy).
        if not self._in_voice:
            if rms >= threshold:
                self._in_voice = True
                self.last_voice_time = now
                self.buffer.extend(self._preroll)  # include the speech onset
                self.buffer.append(data)
        else:
            if rms >= threshold * 0.4:
                self.last_voice_time = now
                self.buffer.append(data)
            elif (now - self.last_voice_time) < self._hangover:
                self.buffer.append(data)  # hangover: bridge a short pause
            else:
                self._in_voice = False
        self._preroll.append(data)

    # ---------------- stream open ----------------
    def _open(self, idx: int, api: str, latency) -> sd.RawInputStream:
        kwargs = dict(device=idx, samplerate=RATE, channels=1, dtype="int16",
                      blocksize=self._blocksize, latency=latency, callback=self._callback)
        if api == "Windows WASAPI":
            kwargs["extra_settings"] = sd.WasapiSettings(auto_convert=True)
        s = sd.RawInputStream(**kwargs)
        s.start()
        return s

    def start(self) -> None:
        candidates = devices.find_input_candidates(self._device_substr)
        if not candidates:
            raise RuntimeError(f"input device not found: {self._device_substr!r}")

        last_err = None
        for idx, api in candidates:
            name = sd.query_devices(idx)["name"]
            for latency in ("low", None):
                try:
                    self._stream = self._open(idx, api, latency)
                    self._current_api = api
                    log.info("mic capture started: [%d] %s via %s @ %d Hz mono "
                             "(gate RMS %.0f, hangover %.1fs, latency=%s)",
                             idx, name, api, RATE, self._threshold, self._hangover,
                             latency or "default")
                    if api != "Windows WASAPI":
                        log.warning("mic opened via %s (HIGH latency). WASAPI was busy "
                                    "(VRChat probing the mic?); will auto-upgrade to "
                                    "WASAPI in the background.", api)
                        self._start_upgrade(candidates)
                    return
                except Exception as e:
                    last_err = e
                    log.warning("mic start failed ([%d] %s via %s, latency=%s): %s",
                                idx, name, api, latency or "default", e)
                    if self._stream is not None:
                        try:
                            self._stream.close()
                        except Exception:
                            pass
                        self._stream = None
        raise RuntimeError(
            f"could not start mic capture ({self._device_substr!r}): {last_err}. "
            "The mic may be held by another app - set VRChat's microphone to "
            "'CABLE Output', not this mic.")

    # ---------------- background WASAPI upgrade ----------------
    def _start_upgrade(self, candidates: list[tuple[int, str]]) -> None:
        wasapi = next(((idx, api) for idx, api in candidates if api == "Windows WASAPI"), None)
        if wasapi is None:
            return
        self._upgrade_stop.clear()
        self._upgrade_thread = threading.Thread(
            target=self._upgrade_loop, args=(wasapi[0],), daemon=True, name="vrclt-mic-upgrade")
        self._upgrade_thread.start()

    def _upgrade_loop(self, wasapi_idx: int) -> None:
        while not self._upgrade_stop.wait(UPGRADE_INTERVAL):
            if self._current_api == "Windows WASAPI":
                return
            new = None
            for latency in ("low", None):
                try:
                    new = self._open(wasapi_idx, "Windows WASAPI", latency)
                    break
                except Exception:
                    new = None
            if new is None:
                continue  # still busy, retry next interval
            with self._swap_lock:
                old = self._stream
                self._stream = new
                self._current_api = "Windows WASAPI"
            if old is not None:
                try:
                    old.stop()
                    old.close()
                except Exception:
                    pass
            log.info("mic upgraded to WASAPI (low latency) - outbound is now fast")
            return

    # ---------------- source interface ----------------
    def active(self, timeout: float = 2.0) -> bool:
        return (time.time() - self.last_voice_time) < timeout

    def drain(self) -> list[bytes]:
        chunks = []
        while True:
            try:
                chunks.append(self.buffer.popleft())
            except IndexError:
                return chunks

    @staticmethod
    def drain_tap(tap: collections.deque[bytes]) -> list[bytes]:
        chunks = []
        while True:
            try:
                chunks.append(tap.popleft())
            except IndexError:
                return chunks

    def requeue(self, chunks: list[bytes]) -> None:
        self.buffer.extendleft(reversed(chunks))

    def trim_to(self, seconds: float) -> None:
        """Drop buffered audio beyond a short pre-roll (stale audio guard)."""
        keep = max(1, int(seconds * 1000 / CHUNK_MS))
        while len(self.buffer) > keep:
            try:
                self.buffer.popleft()
            except IndexError:
                return

    def stop(self) -> None:
        self._upgrade_stop.set()
        if self._upgrade_thread is not None:
            self._upgrade_thread.join(timeout=2)
            self._upgrade_thread = None
        with self._swap_lock:
            s = self._stream
            self._stream = None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
            log.info("mic capture stopped")
