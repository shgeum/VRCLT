"""Microphone capture -> 48 kHz raw taps + 16 kHz Gemini source.

The physical mic is opened at its endpoint-default rate.  Raw passthrough is
kept at 48 kHz mono int16 and Gemini audio is resampled to 16 kHz.  Audio is
voice-activity gated: only audio during actual speech (RMS over the gate, plus
a short pre-roll and hangover tail) is buffered for sending. This matters for
two reasons:

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
import soxr

from . import devices
from .. import platform_support

log = logging.getLogger(__name__)

RATE = 16000  # Gemini input rate
# Rate the raw passthrough is delivered at. The mic itself is opened at
# whatever the device actually runs at (see _device_rate): forcing a rate the
# hardware does not use pushes a sample-rate conversion into the driver, and
# WASAPI's converter with a fixed 10 ms blocksize glitches audibly on devices
# with unusual rates (e.g. a 30 kHz headset-link mic). Capturing natively and
# resampling here keeps the passthrough contract fixed for PcmPlayer while the
# stream stays glitch-free.
CAPTURE_RATE = 48000  # raw mic / passthrough rate
CHUNK_MS = 10
PREROLL_CHUNKS = 20  # ~200 ms kept so speech onsets aren't clipped
UPGRADE_INTERVAL = 6.0  # how often to retry upgrading to WASAPI
BUFFER_CHUNKS = int(13_000 / CHUNK_MS)
STATS_INTERVAL = 15.0
STATUS_WARNING_INTERVAL = 5.0


def _device_rate(idx: int) -> int:
    """The device's own sample rate; CAPTURE_RATE when it cannot be read."""
    try:
        rate = int(round(float(sd.query_devices(idx)["default_samplerate"])))
    except Exception:
        log.debug("mic: default_samplerate unreadable for device %s", idx,
                  exc_info=True)
        return CAPTURE_RATE
    return rate if rate > 0 else CAPTURE_RATE


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
        self._rs: soxr.ResampleStream | None = None
        # level-meter taps: plain float writes from the audio callback, read
        # lock-free by the Qt meter (atomic under the GIL)
        self.last_rms = 0.0
        self.last_rms_time = 0.0
        self.last_effective_threshold = self._threshold
        # ~13 s of audio max; old chunks drop automatically while disconnected
        self.buffer: collections.deque[bytes] = collections.deque(maxlen=BUFFER_CHUNKS)
        self._raw_taps: list[collections.deque[bytes]] = []
        self._preroll: collections.deque[bytes] = collections.deque(maxlen=PREROLL_CHUNKS)
        self.last_voice_time = 0.0
        self._in_voice = False
        self._swap_lock = threading.Lock()
        self._upgrade_stop = threading.Event()
        self._upgrade_thread: threading.Thread | None = None
        self._st_started = time.monotonic()
        self._st_last_callback = 0.0
        self._st_calls = 0
        self._st_frames = 0
        self._st_status = 0
        self._st_raw_dropped = 0
        self._st_max_gap_ms = 0.0
        self._st_last_status_warning = 0.0

    def set_threshold_boost(self, fn) -> None:
        self._boost = fn

    def set_suppressed(self, fn, *, barge_in_multiplier: float = 0.0) -> None:
        self._suppress = fn
        self._suppress_barge_in_multiplier = max(0.0, float(barge_in_multiplier))

    def set_gate_enabled(self, fn) -> None:
        self._gate_enabled = fn

    def add_raw_tap(self, maxlen: int = BUFFER_CHUNKS) -> collections.deque[bytes]:
        """Add a 48 kHz mono int16 raw mic tap for passthrough."""
        tap: collections.deque[bytes] = collections.deque(maxlen=maxlen)
        self._raw_taps.append(tap)
        return tap

    def remove_raw_tap(self, tap: collections.deque[bytes]) -> None:
        try:
            self._raw_taps.remove(tap)
        except ValueError:
            pass

    # ---------------- audio callback ----------------
    def _make_callback(self, rs: soxr.ResampleStream, prs, rate: int):
        def callback(indata, frames, time_info, status):
            self._callback(indata, frames, time_info, status, rs, prs, rate)
        return callback

    def _callback(self, indata, frames, time_info, status, rs: soxr.ResampleStream,
                  prs=None, rate: int = CAPTURE_RATE):
        # currency guard: during a WASAPI hot-swap (or after stop()) a stale
        # stream's callback may still fire; only the stream owning the live
        # resampler may touch buffer/_preroll/_in_voice. An escaped exception
        # here would make sounddevice abort the stream permanently.
        if rs is not self._rs:
            return
        mono_now = time.monotonic()
        self._st_calls += 1
        self._st_frames += int(frames)
        if self._st_last_callback:
            self._st_max_gap_ms = max(
                self._st_max_gap_ms,
                (mono_now - self._st_last_callback) * 1000.0)
        self._st_last_callback = mono_now
        if status:
            self._st_status += 1
            if mono_now - self._st_last_status_warning >= STATUS_WARNING_INTERVAL:
                self._st_last_status_warning = mono_now
                log.warning("mic callback status: %s (count=%d)", status,
                            self._st_status)
        data = bytes(indata)
        now = time.time()
        x16 = np.frombuffer(data, dtype=np.int16)
        x = x16.astype(np.float32)
        rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
        xn = x / 32768.0
        y = rs.resample_chunk(xn)
        if y.size:
            gemini_data = (np.clip(y, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        else:
            gemini_data = b""
        try:
            threshold = self._threshold * float(self._boost())
        except Exception:
            threshold = self._threshold
        # meter taps: recorded before the suppress/gate early-returns so the
        # level display stays live in every mode (incl. echo-suppressed)
        self.last_rms = rms
        self.last_rms_time = now
        self.last_effective_threshold = threshold
        # raw passthrough taps always get the mic: the echo guard only
        # protects the Gemini send path below, so the user's real voice never
        # cuts out of passthrough while inbound audio is playing
        # taps expect CAPTURE_RATE; convert when the device runs at another
        # rate, otherwise hand over the device bytes untouched
        if prs is None:
            raw = data
        else:
            pass_y = prs.resample_chunk(xn)
            raw = ((np.clip(pass_y, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
                   if pass_y.size else b"")
        if raw:
            for tap in list(self._raw_taps):
                if tap.maxlen is not None and len(tap) >= tap.maxlen:
                    self._st_raw_dropped += 1
                tap.append(raw)
        self._maybe_log_stats(mono_now, rate)
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
        if not gemini_data:
            return
        if not self._gate_enabled():
            # passthrough / gate off: stream everything continuously
            self.buffer.append(gemini_data)
            self.last_voice_time = now
            self._preroll.append(gemini_data)
            return
        # hysteresis: open at `threshold`, but once speaking, stay open down to
        # 40% of it - so weak consonants / brief dips don't chop the stream
        # (which made the translated audio come out choppy).
        if not self._in_voice:
            if rms >= threshold:
                self._in_voice = True
                self.last_voice_time = now
                self.buffer.extend(self._preroll)  # include the speech onset
                self.buffer.append(gemini_data)
        else:
            if rms >= threshold * 0.4:
                self.last_voice_time = now
                self.buffer.append(gemini_data)
            elif (now - self.last_voice_time) < self._hangover:
                self.buffer.append(gemini_data)  # hangover: bridge a short pause
            else:
                self._in_voice = False
        self._preroll.append(gemini_data)

    # ---------------- stream open ----------------
    def _open(self, idx: int, api: str, latency, rs: soxr.ResampleStream,
              prs=None, rate: int = CAPTURE_RATE,
              start: bool = True) -> sd.RawInputStream:
        kwargs = dict(device=idx, samplerate=rate, channels=1, dtype="int16",
                      blocksize=int(rate * CHUNK_MS / 1000), latency=latency,
                      callback=self._make_callback(rs, prs, rate))
        settings = devices.extra_settings(api)
        if settings is not None:
            kwargs["extra_settings"] = settings
        s = sd.RawInputStream(**kwargs)
        if start:
            s.start()
        return s

    def start(self) -> None:
        candidates = devices.find_input_candidates(self._device_substr)
        if not candidates:
            raise RuntimeError(f"input device not found: {self._device_substr!r}")

        last_err = None
        for idx, api in candidates:
            name = sd.query_devices(idx)["name"]
            rate = _device_rate(idx)
            for latency in ("low", None):
                try:
                    rs, prs = self._resamplers(rate)
                    # install the resampler before starting the stream so the
                    # callback currency guard accepts the first frames
                    s = self._open(idx, api, latency, rs, prs, rate, start=False)
                    self._rs = rs
                    self._stream = s
                    self._reset_stats()
                    s.start()
                    self._current_api = api
                    log.info("mic capture started: [%d] %s via %s @ %d Hz mono "
                             "(endpoint default; passthrough %d Hz%s, send %d Hz, "
                             "gate RMS %.0f, hangover %.1fs, latency=%s)",
                             idx, name, api, rate, CAPTURE_RATE,
                             "" if prs is None else " resampled", RATE,
                             self._threshold, self._hangover, latency or "default")
                    best = self._best_api()
                    if best and api != best:
                        log.warning("mic opened via %s (HIGH latency). %s was busy "
                                    "(VRChat probing the mic?); will auto-upgrade to "
                                    "%s in the background.", api, best, best)
                        self._start_upgrade(candidates, best)
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
                        self._rs = None
        raise RuntimeError(
            f"could not start mic capture ({self._device_substr!r}): {last_err}. "
            "The mic may be held by another app - set VRChat's microphone to "
            "'CABLE Output', not this mic.")

    # ---------------- background host-API upgrade ----------------
    @staticmethod
    def _resamplers(rate: int):
        """(send 16 kHz, passthrough 48 kHz or None) for a device rate."""
        send = soxr.ResampleStream(rate, RATE, 1, dtype="float32")
        through = (None if rate == CAPTURE_RATE
                   else soxr.ResampleStream(rate, CAPTURE_RATE, 1, dtype="float32"))
        return send, through

    def _reset_stats(self) -> None:
        self._st_started = time.monotonic()
        self._st_last_callback = 0.0
        self._st_calls = 0
        self._st_frames = 0
        self._st_status = 0
        self._st_raw_dropped = 0
        self._st_max_gap_ms = 0.0
        self._st_last_status_warning = 0.0

    def _maybe_log_stats(self, mono_now: float, rate: int) -> None:
        if mono_now - self._st_started < STATS_INTERVAL:
            return
        elapsed = mono_now - self._st_started
        max_raw_queue = max((len(t) for t in self._raw_taps), default=0)
        log.info(
            "mic stats(%.0fs): calls=%d audio=%.1fs max_gap=%.1fms "
            "status=%d raw_queue=%dms dropped=%d",
            elapsed, self._st_calls,
            self._st_frames / max(1, rate), self._st_max_gap_ms,
            self._st_status, max_raw_queue * CHUNK_MS, self._st_raw_dropped)
        self._st_started = mono_now
        self._st_calls = 0
        self._st_frames = 0
        self._st_status = 0
        self._st_raw_dropped = 0
        self._st_max_gap_ms = 0.0

    @staticmethod
    def _best_api() -> str:
        """Lowest-latency host API on this platform (WASAPI on Windows).
        Empty when the platform has only one, so no upgrade is attempted."""
        order = platform_support.host_api_order()
        return order[0] if len(order) > 1 else ""

    def _start_upgrade(self, candidates: list[tuple[int, str]], best: str) -> None:
        target = next(((idx, api) for idx, api in candidates if api == best), None)
        if target is None:
            return
        self._upgrade_stop.clear()
        self._upgrade_thread = threading.Thread(
            target=self._upgrade_loop, args=(target[0], best), daemon=True,
            name="vrclt-mic-upgrade")
        self._upgrade_thread.start()

    def _upgrade_loop(self, target_idx: int, target_api: str) -> None:
        while not self._upgrade_stop.wait(UPGRADE_INTERVAL):
            if self._current_api == target_api:
                return
            new = None
            new_rs = None
            rate = _device_rate(target_idx)
            for latency in ("low", None):
                try:
                    new_rs, new_prs = self._resamplers(rate)
                    new = self._open(target_idx, target_api, latency, new_rs,
                                     new_prs, rate, start=False)
                    break
                except Exception:
                    new = None
                    new_rs = None
            if new is None:
                continue  # still busy, retry next interval
            # swap-then-start under the lock: the new stream's callback cannot
            # fire before start(), and the currency guard silences the old
            # stream's callback the moment _rs is swapped - so the two streams
            # never mutate buffer/_preroll concurrently. stop() sets
            # _upgrade_stop before taking _swap_lock, so checking it here
            # guarantees we never install a stream after stop().
            stale = None
            old = None
            with self._swap_lock:
                if self._upgrade_stop.is_set():
                    stale = new
                else:
                    prev = (self._stream, self._rs, self._current_api)
                    self._stream, self._rs, self._current_api = \
                        new, new_rs, target_api
                    try:
                        new.start()
                    except Exception:
                        self._stream, self._rs, self._current_api = prev
                        stale = new
                    else:
                        old = prev[0]
            if stale is not None:
                try:
                    stale.close()
                except Exception:
                    pass
                if self._upgrade_stop.is_set():
                    return
                continue  # start() failed - retry next interval
            if old is not None:
                try:
                    old.stop()
                    old.close()
                except Exception:
                    pass
            log.info("mic upgraded to %s (low latency) - outbound is now fast",
                     target_api)
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
        if seconds <= 0:
            self.buffer.clear()
            return
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
            self._rs = None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
            log.info("mic capture stopped")
