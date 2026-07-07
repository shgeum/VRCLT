"""Streaming PCM player: dedicated thread + queue (never blocks the asyncio loop).

A small jitter buffer (prebuffer) absorbs the irregular cadence of server
audio: playback only starts once ~prebuffer_ms is queued, then writes
continuously, so gaps between server chunks don't make the voice choppy.

Epoch-based interruption: play() enqueues (epoch, <=slice_ms) tuples;
interrupt() bumps the epoch so the consumer skips anything stale.
"""
import logging
import queue
import threading

import sounddevice as sd

from . import devices

log = logging.getLogger(__name__)


class PcmPlayer:
    def __init__(self, device_substr: str, name: str = "player", rate: int = 24000,
                 prebuffer_ms: int = 120, slice_ms: int = 100, block_ms: int = 20):
        self._device_substr = device_substr
        self._name = name
        self._rate = rate
        self._slice_bytes = max(1, rate * max(1, slice_ms) // 1000) * 2
        self._blocksize = max(1, rate * max(1, block_ms) // 1000)
        self._prebuffer_bytes = rate * 2 * prebuffer_ms // 1000
        self._q: queue.Queue[tuple[int, bytes]] = queue.Queue(maxsize=256)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._epoch = 0

    def start(self) -> None:
        idx = devices.find_output(self._device_substr)
        if idx is None:
            raise RuntimeError(f"output device not found: {self._device_substr!r}")
        self._device_index = idx
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"vrclt-{self._name}")
        self._thread.start()
        log.info("%s: -> [%d] %s @ %d Hz", self._name, idx, sd.query_devices(idx)["name"], self._rate)

    def _open_stream(self) -> sd.RawOutputStream | None:
        """Open with retries: the device can be transiently busy (exclusive-mode
        holder, WASAPI probe at app startup). A silent give-up here used to kill
        the playback thread while the app still reported Running."""
        for attempt, backoff in enumerate((1.0, 2.0, 4.0, 0.0)):
            try:
                stream = sd.RawOutputStream(
                    device=self._device_index, samplerate=self._rate, channels=1,
                    dtype="int16", blocksize=self._blocksize, latency="low",
                    extra_settings=sd.WasapiSettings(auto_convert=True),
                )
                stream.start()
                return stream
            except Exception:
                if backoff <= 0.0:
                    break
                log.warning("%s: output stream open failed (attempt %d), retrying in %.0fs",
                            self._name, attempt + 1, backoff, exc_info=True)
                if self._stop.wait(backoff):
                    return None
        log.error("%s: could not open output stream - playback disabled "
                  "(restart the runtime after freeing the device)", self._name)
        return None

    def _run(self) -> None:
        stream = self._open_stream()
        if stream is None:
            return
        pending = bytearray()
        playing = False
        try:
            while not self._stop.is_set():
                try:
                    epoch, chunk = self._q.get(timeout=0.2)
                except queue.Empty:
                    # turn gap / underrun: flush remainder and re-buffer next turn
                    if pending:
                        try:
                            stream.write(bytes(pending))
                        except Exception:
                            log.exception("%s: write failed", self._name)
                        pending.clear()
                    playing = False
                    continue
                if epoch != self._epoch:
                    pending.clear()  # interrupted: drop buffered stale audio
                    playing = False
                    continue
                pending.extend(chunk)
                if not playing and len(pending) < self._prebuffer_bytes:
                    continue  # keep buffering until we have a cushion
                playing = True
                try:
                    stream.write(bytes(pending))
                except Exception:
                    log.exception("%s: write failed", self._name)
                pending.clear()
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            log.info("%s: stopped", self._name)

    def play(self, pcm: bytes) -> None:
        epoch = self._epoch
        for i in range(0, len(pcm), self._slice_bytes):
            try:
                self._q.put_nowait((epoch, pcm[i:i + self._slice_bytes]))
            except queue.Full:
                log.warning("%s: queue full, dropping audio", self._name)
                return

    def interrupt(self) -> None:
        """Drop everything queued (server 'interrupted' = barge-in)."""
        self._epoch += 1
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
