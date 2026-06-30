"""Capture a target app's audio via Windows process loopback (ProcTap).

Echo-proof by construction: our own TTS playback can never re-enter this
pipeline, regardless of audio devices.

ProcTap v1.0.3 facts (verified):
- real API is ProcessAudioCapture (the README's ProcTap/StreamConfig is stale)
- output is ALWAYS 48000 Hz / 2 ch / float32
- emits NOTHING while the target process is silent (never block on it)
"""
import collections
import logging
import time

import numpy as np
import psutil
import soxr

log = logging.getLogger(__name__)

SRC_RATE = 48000
DST_RATE = 16000


def _process_name_matches(process_name: str | None, exe_name: str) -> bool:
    name = (process_name or "").strip().lower()
    target = (exe_name or "").strip().lower()
    if not name or not target:
        return False
    names = {target}
    if target.endswith(".exe"):
        names.add(target[:-4])
    else:
        names.add(f"{target}.exe")
    return name in names


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



class GameAudioTap:
    """Same source interface as MicCapture: drain()/requeue()/active().

    Optional Silero VAD gates out non-speech (background music) so only voices
    reach Gemini.
    """

    def __init__(self, exe_name: str = "VRChat.exe", *, use_vad: bool = True,
                 vad_threshold: float = 0.5, vad_hangover_sec: float = 0.35):
        self._exe = exe_name
        self._tap = None
        self._pid: int | None = None
        self._rs = None
        self._use_vad = use_vad
        self._vad_threshold = float(vad_threshold)
        self._vad_hangover = float(vad_hangover_sec)
        self._vad = None
        self._vad_buf = np.zeros(0, dtype=np.float32)
        self._last_speech = 0.0
        self.buffer: collections.deque[bytes] = collections.deque(maxlen=400)
        self.last_chunk_time = 0.0

    @property
    def pid(self) -> int | None:
        return self._pid

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
        tap.start()
        self._tap = tap
        self._pid = pid
        log.info("game tap started: %s (pid %d)", self._exe, pid)

    def _on_data(self, pcm: bytes, _frames: int) -> None:
        try:
            x = np.frombuffer(pcm, dtype=np.float32)
            mono = x.reshape(-1, 2).mean(axis=1)          # 48k stereo f32 -> mono
            y = self._rs.resample_chunk(mono)             # stateful 48k -> 16k
            if not y.size:
                return
            if self._vad is None:
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
                if self._vad.prob(frame) >= self._vad_threshold:
                    self._last_speech = now
                if (now - self._last_speech) < self._vad_hangover:
                    pcm16 = (np.clip(frame, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
                    self.buffer.append(pcm16)
                    self.last_chunk_time = now
        except Exception:
            log.exception("game tap conversion failed")

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
        if self._tap is not None:
            try:
                self._tap.stop()
            except Exception:
                pass
            self._tap = None
            self._pid = None
            log.info("game tap stopped")
        # release the soxr ResampleStream so its native object is collected
        # (otherwise nanobind warns about a leaked CSoxr instance at exit)
        self._rs = None
