"""Capture a target app's audio via Windows process loopback (ProcTap).

Echo-proof by construction: our own TTS playback can never re-enter this
pipeline, regardless of audio devices.

ProcTap v1.0.3 facts (verified):
- real API is ProcessAudioCapture (the README's ProcTap/StreamConfig is stale)
- output is ALWAYS 48000 Hz / 2 ch / float32
- emits NOTHING while the target process is silent (never block on it)
- it SILENTLY falls back to system-wide loopback when per-process activation
  fails, and reports success either way - see _capture_scope() below
"""
import collections
import logging
import time

import numpy as np
import psutil
import soxr

from .. import platform_support

log = logging.getLogger(__name__)

SRC_RATE = 48000
DST_RATE = 16000


def _process_name_matches(process_name: str | None, exe_name: str) -> bool:
    name = (process_name or "").strip().lower()
    if not name:
        return False
    return name in platform_support.process_name_aliases(exe_name)


def _matching_processes(exe_name: str) -> list[psutil.Process]:
    matches = []
    for proc in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if _process_name_matches(proc.info.get("name"), exe_name):
                matches.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return matches


def _has_matching_ancestor(proc: psutil.Process, candidate_pids: set[int],
                           exe_name: str) -> bool:
    seen: set[int] = set()
    try:
        parent = proc.parent()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    while parent is not None and parent.pid not in seen:
        seen.add(parent.pid)
        if parent.pid in candidate_pids:
            return True
        try:
            if _process_name_matches(parent.name(), exe_name):
                return True
            parent = parent.parent()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False
    return False


def _matching_descendant_count(proc: psutil.Process, exe_name: str) -> int:
    try:
        children = proc.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return 0
    count = 0
    for child in children:
        try:
            if _process_name_matches(child.name(), exe_name):
                count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return count


def _create_time(proc: psutil.Process) -> float:
    try:
        return float(proc.info.get("create_time") or proc.create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return float("inf")


def find_pids(exe_name: str = "VRChat.exe") -> list[int]:
    """Return capture root PIDs for an executable name.

    Electron apps such as Discord run several same-name processes. ProcTap
    captures the selected PID's process tree, so choosing a leaf process can
    miss the actual audio service. Prefer same-name tree roots, ordered by the
    size of their same-name subtree.
    """
    matches = _matching_processes(exe_name)
    if not matches:
        return []

    candidate_pids = {proc.pid for proc in matches}
    roots = [
        proc for proc in matches
        if not _has_matching_ancestor(proc, candidate_pids, exe_name)
    ] or matches
    roots.sort(key=lambda proc: (
        -_matching_descendant_count(proc, exe_name),
        _create_time(proc),
        proc.pid,
    ))

    pids = [proc.pid for proc in roots]
    if len(matches) > 1:
        log.debug(
            "process resolver: %s candidates=%s roots=%s selected=%s",
            exe_name,
            sorted(candidate_pids),
            pids,
            pids[0] if pids else None,
        )
    return pids


def find_pid(exe_name: str = "VRChat.exe") -> int | None:
    pids = find_pids(exe_name)
    return pids[0] if pids else None


def _capture_scope(tap) -> tuple[bool, str]:
    """(process_scoped, reason) for a freshly constructed ProcTap capture.

    ProcTap's Windows backend answers *seven* different per-process activation
    failures by opening a plain loopback on the default render endpoint
    instead - the whole desktop, every app, our own TTS included - and reports
    success either way, so a caller that only checks for exceptions believes it
    is capturing one process while it is really capturing everything.

    The reproducible trigger is its Windows build gate (VerifyVersionInfoW
    against 10.0.20438), which no Windows 10 build can pass; the rest
    (mmdevapi.dll, ActivateAudioInterfaceAsync, its 10 s completion wait) are
    machine-dependent and can fire on Windows 11 too. Rather than predict which,
    ask the native object what it actually opened.

    Only ProcTap's Windows backend has that fallback, so a capture we cannot
    interrogate (macOS/Linux backends, a future ProcTap) counts as scoped.
    """
    native = getattr(getattr(tap, "_backend", None), "_native", None)
    is_process_specific = getattr(native, "is_process_specific", None)
    if is_process_specific is None:
        return True, ""
    try:
        if is_process_specific():
            return True, ""
        try:
            reason = native.get_last_error() or ""
        except Exception:
            reason = ""
        return False, reason
    except Exception:
        log.debug("game tap: capture scope query failed", exc_info=True)
        return True, ""


class GameAudioTap:
    """Same source interface as MicCapture: drain()/requeue()/active().

    Optional Silero VAD gates out non-speech (background music) so only voices
    reach Gemini.
    """

    def __init__(self, exe_name: str = "VRChat.exe", *, use_vad: bool = True,
                 vad_threshold: float = 0.5, vad_hangover_sec: float = 0.35,
                 allow_system_audio: bool = False):
        self._exe = exe_name
        self._tap = None
        self._pid: int | None = None
        self._rs = None
        self._allow_system_audio = bool(allow_system_audio)
        # False once start() accepted a system-wide fallback: everything the
        # default output device plays is in the stream, not just the target app
        self.process_scoped = True
        self._use_vad = use_vad
        self._vad_threshold = float(vad_threshold)
        self._vad_hangover = float(vad_hangover_sec)
        self._vad = None
        self._vad_buf = np.zeros(0, dtype=np.float32)
        self._last_speech = 0.0
        self.buffer: collections.deque[bytes] = collections.deque(maxlen=400)
        self.last_chunk_time = 0.0
        # Rolling counters for the periodic stats line. ProcTap is a native
        # extension that captures continuously and logs nothing, so without
        # these an hour of heavy capture is indistinguishable from an idle one
        # in the log - which is exactly the blind spot the memory-growth hunt
        # kept running into. Written from ProcTap's callback thread, read from
        # the supervisor: plain ints, no lock (diagnostics, not control flow).
        self._st_calls = 0        # ProcTap callbacks
        self._st_in_bytes = 0     # 48 kHz stereo float32 bytes handed to us
        self._st_frames = 0       # 512-sample VAD frames examined
        self._st_speech = 0       # frames that passed the gate
        self._st_dropped = 0      # chunks the ring buffer evicted unread
        self._st_errors = 0       # conversion failures
        self._error_log_left = 0
        # monotonic (never reset by stats_line): the silence check needs a
        # counter the stats window cannot zero out underneath it
        self._calls_total = 0
        self._calls_at_check = 0
        self._silent_since = 0.0  # when the capture last went quiet
        self._silence_warned = False

    @property
    def pid(self) -> int | None:
        return self._pid

    def stats_line(self) -> str:
        """One-line capture summary; resets the window counters."""
        seconds = self._st_in_bytes / (SRC_RATE * 2 * 4) if self._st_in_bytes else 0.0
        speech = (100.0 * self._st_speech / self._st_frames) if self._st_frames else 0.0
        line = (f"calls={self._st_calls} audio={seconds:.1f}s "
                f"vad_frames={self._st_frames} speech={speech:.0f}% "
                f"queued={len(self.buffer)} dropped={self._st_dropped} "
                f"errors={self._st_errors}")
        self._st_calls = self._st_in_bytes = self._st_frames = 0
        self._st_speech = self._st_dropped = self._st_errors = 0
        return line

    def start(self, pid: int | None = None) -> None:
        from proctap import ProcessAudioCapture
        pid = pid if pid is not None else find_pid(self._exe)
        if pid is None:
            raise RuntimeError(f"{self._exe} is not running")
        if self._tap is not None:
            self.stop()
        self._rs = soxr.ResampleStream(SRC_RATE, DST_RATE, 1, dtype="float32")
        self.buffer.clear()
        self.last_chunk_time = 0.0
        self._vad_buf = np.zeros(0, dtype=np.float32)
        if self._use_vad and self._vad is None:
            try:
                from .vad import SileroVAD
                self._vad = SileroVAD()
                log.info("game tap: Silero VAD enabled (music/noise gating)")
            except Exception:
                log.exception("game tap: VAD init failed - capturing without it")
                self._vad = None
        elif self._vad is not None:
            self._vad.reset()
        tap = ProcessAudioCapture(pid, on_data=self._on_data)
        scoped, reason = _capture_scope(tap)
        if not scoped and not self._allow_system_audio:
            # refuse rather than transcribe the whole desktop behind the user's
            # back: it captures every other app AND our own TTS (the echo-proof
            # guarantee only holds for a process-scoped tap)
            self._close_quietly(tap)
            self._rs = None
            raise RuntimeError(
                f"per-process capture is unavailable for {self._exe} "
                f"(pid {pid}) - the OS would capture ALL desktop audio "
                f"instead. WASAPI process loopback needs Windows build 20348+ "
                f"(never Windows 10); on Windows 11 the activation itself "
                f"failed. Set inbound.allow_system_audio to accept it."
                + (f" [{reason}]" if reason else "")
            )
        tap.start()
        self._tap = tap
        self._pid = pid
        self.process_scoped = scoped
        if not scoped:
            log.warning(
                "game tap: per-process capture unavailable - capturing ALL "
                "desktop audio (allowed by inbound.allow_system_audio). Other "
                "apps and this app's own translated voice will be transcribed."
            )
        self._error_log_left = 5
        self._silent_since = time.time()
        self._silence_warned = False
        log.info("game tap started: %s (pid %d, %s, %s)", self._exe, pid,
                 "process-scoped" if scoped else "SYSTEM-WIDE",
                 self._describe_format(tap))

    def _describe_format(self, tap) -> str:
        """Report the capture format, loudly if it is not what we decode.

        _on_data hard-assumes 48 kHz stereo float32. ProcTap converts to that,
        but its Windows backend mis-detects the source format when its own
        system-wide fallback returns something other than 48 kHz/32-bit - it
        then treats float32 samples as int16 and the audio becomes noise. A
        capture that "runs" while producing garbage is the hardest failure to
        spot from the outside, so name the format at start.
        """
        try:
            fmt = tap.get_format() or {}
        except Exception:
            log.debug("game tap: format query failed", exc_info=True)
            return "format=unknown"
        rate = fmt.get("sample_rate")
        channels = fmt.get("channels")
        bits = fmt.get("bits_per_sample")
        text = f"format={rate}Hz/{channels}ch/{bits}bit"
        if (rate, channels, bits) != (SRC_RATE, 2, 32):
            log.warning(
                "game tap: unexpected capture format %s - the decoder expects "
                "%d Hz stereo float32, so inbound audio may be garbled",
                text, SRC_RATE)
        return text

    def check_capture(self, silence_sec: float) -> None:
        """Warn once when a running tap stops delivering audio.

        ProcTap emits nothing while the target app is silent, and nothing at
        all when its capture has quietly broken - the two look identical from
        here. Saying so is still better than the previous behaviour, where a
        dead tap produced no log line whatsoever.
        """
        if self._tap is None:
            return
        now = time.time()
        if self._calls_total != self._calls_at_check:
            self._calls_at_check = self._calls_total
            if self._silence_warned:
                log.info("game tap: %s audio resumed after %.0fs of silence",
                         self._exe, now - self._silent_since)
            self._silent_since = now
            self._silence_warned = False
            return
        if not self._silence_warned and (now - self._silent_since) >= silence_sec:
            self._silence_warned = True
            log.warning(
                "game tap: no audio from %s (pid %s) for %.0fs - either the "
                "app is silent or the capture stopped delivering; restart the "
                "runtime if subtitles stay empty while it is clearly playing",
                self._exe, self._pid, now - self._silent_since)

    @staticmethod
    def _close_quietly(tap) -> None:
        try:
            tap.close()
        except Exception:
            log.debug("game tap: closing rejected capture failed", exc_info=True)

    def _on_data(self, pcm: bytes, _frames: int) -> None:
        # snapshot: a late ProcTap callback can arrive after stop() nulled
        # _rs (tap restart on PID change) - bail out instead of raising
        rs = self._rs
        vad = self._vad
        if rs is None:
            return
        self._st_calls += 1
        self._calls_total += 1
        self._st_in_bytes += len(pcm)
        try:
            x = np.frombuffer(pcm, dtype=np.float32)
            mono = x.reshape(-1, 2).mean(axis=1)          # 48k stereo f32 -> mono
            y = rs.resample_chunk(mono)                   # stateful 48k -> 16k
            if not y.size:
                return
            if vad is None:
                pcm16 = (np.clip(y, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
                self.buffer.append(pcm16)
                self.last_chunk_time = time.time()
                return
            # VAD-gated: process in fixed 512-sample frames, keep only speech
            from .vad import FRAME
            self._vad_buf = np.concatenate([self._vad_buf, y])
            now = time.time()
            while self._vad_buf.size >= FRAME:
                frame = self._vad_buf[:FRAME]
                self._vad_buf = self._vad_buf[FRAME:]
                self._st_frames += 1
                if vad.prob(frame) >= self._vad_threshold:
                    self._last_speech = now
                    self._st_speech += 1
                if (now - self._last_speech) < self._vad_hangover:
                    pcm16 = (np.clip(frame, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
                    if len(self.buffer) == self.buffer.maxlen:
                        # the ring is full: appending silently discards the
                        # oldest speech, so count what the consumer never saw
                        self._st_dropped += 1
                    self.buffer.append(pcm16)
                    self.last_chunk_time = now
        except Exception:
            # one callback per ~10 ms: log the first few per session in full,
            # then let the stats line carry the count instead of flooding
            self._st_errors += 1
            self._error_log_left -= 1
            if self._error_log_left >= 0:
                log.exception("game tap conversion failed (pcm=%d bytes)", len(pcm))
            elif self._error_log_left == -1:
                log.warning("game tap: further conversion errors will only be "
                            "counted in the stats line")

    def active(self, timeout: float = 2.0) -> bool:
        return (time.time() - self.last_chunk_time) < timeout

    def drain(self) -> list[bytes]:
        chunks = []
        while True:
            try:
                chunks.append(self.buffer.popleft())
            except IndexError:
                return chunks

    def requeue(self, chunks: list[bytes]) -> None:
        self.buffer.extendleft(reversed(chunks))

    def trim_to(self, seconds: float) -> None:
        """Drop buffered audio beyond a short pre-roll (stale audio guard)."""
        target_bytes = int(seconds * DST_RATE * 2)
        total = sum(len(c) for c in self.buffer)
        while total > target_bytes:
            try:
                total -= len(self.buffer.popleft())
            except IndexError:
                return

    def stop(self) -> None:
        # null _rs first so an in-flight _on_data bails at the guard instead
        # of feeding a resampler that is being torn down. Also releases the
        # soxr ResampleStream so its native object is collected (otherwise
        # nanobind warns about a leaked CSoxr instance at exit).
        self._rs = None
        if self._tap is not None:
            try:
                self._tap.stop()
            except Exception:
                pass
            self._tap = None
            self._pid = None
            self.process_scoped = True
            log.info("game tap stopped")
