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
import time

import numpy as np
import sounddevice as sd
import soxr

from . import devices

log = logging.getLogger(__name__)


class PcmPlayer:
    def __init__(self, device_substr: str, name: str = "player", rate: int = 24000,
                 prebuffer_ms: int = 120, slice_ms: int = 100, block_ms: int = 20,
                 gain: float = 1.0, *, match_device_rate: bool = False,
                 rebuffer_on_underflow: bool = False,
                 stats_interval_sec: float = 0.0,
                 max_buffer_ms: int = 0):
        self._device_substr = device_substr
        self._name = name
        self._rate = rate
        self._output_rate = rate
        self._using_endpoint_default = False
        self._gain = max(0.0, min(2.0, float(gain)))
        self._block_ms = max(1, int(block_ms))
        self._slice_ms = max(1, int(slice_ms))
        self._slice_bytes = max(1, rate * self._slice_ms // 1000) * 2
        self._blocksize = max(1, rate * self._block_ms // 1000)
        self._prebuffer_bytes = rate * 2 * prebuffer_ms // 1000
        self._prebuffer_ms = max(0, int(prebuffer_ms))
        self._match_device_rate = bool(match_device_rate)
        self._rebuffer_on_underflow = bool(rebuffer_on_underflow)
        self._stats_interval = max(0.0, float(stats_interval_sec))
        self._max_buffer_ms = max(0, int(max_buffer_ms))
        queue_size = (max(4, (self._max_buffer_ms + self._slice_ms - 1)
                          // self._slice_ms)
                      if self._max_buffer_ms else 256)
        self._q: queue.Queue[tuple[int, bytes]] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._epoch = 0
        # Diagnostics are plain integer/float writes.  Exact cross-thread
        # snapshots are not required; the GIL makes individual updates safe.
        self._underflows = 0
        self._starvations = 0
        self._queue_drops = 0
        self._max_queue = 0
        self._max_write_ms = 0.0
        self._last_warning = 0.0
        self._last_drop_warning = 0.0

    def set_gain(self, gain: float) -> None:
        """Live volume change; a plain float write is atomic under the GIL."""
        self._gain = max(0.0, min(2.0, float(gain)))

    def _apply_gain(self, data: bytes) -> bytes:
        g = self._gain
        if abs(g - 1.0) < 1e-3:
            return data  # fast path keeps unity playback zero-cost
        x = np.frombuffer(data, dtype=np.int16).astype(np.float32) * g
        return np.clip(x, -32768.0, 32767.0).astype(np.int16).tobytes()

    def start(self) -> None:
        idx = devices.find_output(self._device_substr)
        if idx is None:
            raise RuntimeError(f"output device not found: {self._device_substr!r}")
        self._device_index = idx
        self._output_rate = self._rate
        self._using_endpoint_default = False
        if self._match_device_rate:
            try:
                default_rate = int(round(float(
                    sd.query_devices(idx)["default_samplerate"])))
                if default_rate > 0:
                    self._output_rate = default_rate
                    self._using_endpoint_default = True
            except Exception:
                log.debug("%s: output default_samplerate unreadable", self._name,
                          exc_info=True)
        self._blocksize = max(1, self._output_rate * self._block_ms // 1000)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"vrclt-{self._name}")
        self._thread.start()

    def _open_stream_at(self, rate: int) -> sd.RawOutputStream | None:
        """Open with retries: the device can be transiently busy (exclusive-mode
        holder, WASAPI probe at app startup). A silent give-up here used to kill
        the playback thread while the app still reported Running."""
        blocksize = max(1, rate * self._block_ms // 1000)
        for attempt, backoff in enumerate((1.0, 2.0, 4.0, 0.0)):
            try:
                stream = sd.RawOutputStream(
                    device=self._device_index, samplerate=rate, channels=1,
                    dtype="int16", blocksize=blocksize, latency="low",
                    extra_settings=devices.extra_settings(),
                )
                stream.start()
                self._blocksize = blocksize
                return stream
            except Exception:
                if backoff <= 0.0:
                    break
                log.warning("%s: output stream open failed (attempt %d), retrying in %.0fs",
                            self._name, attempt + 1, backoff, exc_info=True)
                if self._stop.wait(backoff):
                    return None
        return None

    def _open_stream(self) -> sd.RawOutputStream | None:
        stream = self._open_stream_at(self._output_rate)
        if stream is None and self._output_rate != self._rate:
            # Endpoint metadata can be stale on a freshly reconfigured virtual
            # cable.  Preserve the old WASAPI-auto-convert path as a fallback.
            log.warning("%s: endpoint-default %d Hz open failed; falling back "
                        "to source rate %d Hz", self._name, self._output_rate,
                        self._rate)
            self._output_rate = self._rate
            self._using_endpoint_default = False
            stream = self._open_stream_at(self._output_rate)
        if stream is None:
            log.error("%s: could not open output stream - playback disabled "
                      "(restart the runtime after freeing the device)", self._name)
        return stream

    def _output_bytes(self, pcm: bytes, rs: soxr.ResampleStream | None) -> bytes:
        if rs is None or not pcm:
            return pcm
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        y = rs.resample_chunk(x)
        if not y.size:
            return b""
        return (np.clip(y, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()

    def _warn_rebuffer(self, reason: str) -> None:
        now = time.monotonic()
        if now - self._last_warning < 5.0:
            return
        self._last_warning = now
        log.warning("%s: output %s; rebuffering %d ms", self._name, reason,
                    self._prebuffer_ms)

    def stats(self) -> dict[str, int | float]:
        """Best-effort diagnostics snapshot; safe to call from UI/tests."""
        return {
            "underflows": self._underflows,
            "starvations": self._starvations,
            "queue_drops": self._queue_drops,
            "queue": self._q.qsize(),
            "queue_ms": self._q.qsize() * self._slice_ms,
            "max_queue": self._max_queue,
            "max_queue_ms": self._max_queue * self._slice_ms,
            "max_write_ms": self._max_write_ms,
            "source_rate": self._rate,
            "output_rate": self._output_rate,
        }

    def _run(self) -> None:
        stream = self._open_stream()
        if stream is None:
            return
        try:
            device_name = sd.query_devices(self._device_index)["name"]
        except Exception:
            device_name = self._device_substr or str(self._device_index)
        rate_note = ("endpoint default"
                     if self._using_endpoint_default else "requested/fallback")
        conversion = ("; source %d Hz resampled" % self._rate
                      if self._output_rate != self._rate else "")
        buffer_note = ("; jitter buffer %d ms" % self._prebuffer_ms
                       if self._rebuffer_on_underflow else "")
        log.info("%s: -> [%d] %s @ %d Hz (%s%s%s)", self._name,
                 self._device_index, device_name, self._output_rate, rate_note,
                 conversion, buffer_note)
        rs = (soxr.ResampleStream(self._rate, self._output_rate, 1,
                                  dtype="float32")
              if self._output_rate != self._rate else None)
        pending = bytearray()
        output_pending = bytearray()
        output_block_bytes = self._blocksize * 2
        playing = False
        run_epoch = self._epoch
        stats_started = time.monotonic()
        stats_written_frames = 0
        stats_underflows = self._underflows
        stats_starvations = self._starvations
        stats_drops = self._queue_drops

        def write_one(out: bytes) -> bool:
            """Write one contiguous block; True means pause and rebuffer."""
            nonlocal playing, stats_written_frames
            starting = not playing
            playing = True
            try:
                write_started = time.perf_counter()
                underflowed = bool(stream.write(out))
                write_ms = (time.perf_counter() - write_started) * 1000.0
                self._max_write_ms = max(self._max_write_ms, write_ms)
                stats_written_frames += len(out) // 2
                # A first write after silence normally reports the empty
                # period before playback began.  Only an underrun during an
                # already-playing run is a glitch that requires rebuffering.
                if underflowed and not starting:
                    self._underflows += 1
                    if self._rebuffer_on_underflow:
                        playing = False
                        self._warn_rebuffer("underflow")
                        return True
            except Exception:
                log.exception("%s: write failed", self._name)
                if self._rebuffer_on_underflow:
                    playing = False
                    return True
            return False

        try:
            while not self._stop.is_set():
                timeout = (max(0.015, self._block_ms / 1000 * 1.5)
                           if playing and self._rebuffer_on_underflow else 0.2)
                try:
                    epoch, chunk = self._q.get(timeout=timeout)
                except queue.Empty:
                    if self._epoch != run_epoch:
                        # interrupt() intentionally stopped this route.  Clear
                        # worker-local state without reporting a fake underrun.
                        pending.clear()
                        output_pending.clear()
                        playing = False
                        if rs is not None:
                            rs.clear()
                        run_epoch = self._epoch
                        continue
                    if self._rebuffer_on_underflow:
                        if playing:
                            self._starvations += 1
                            self._warn_rebuffer("starved")
                        playing = False
                        continue
                    # turn gap / underrun: flush remainder and re-buffer next turn
                    if pending:
                        try:
                            out = self._output_bytes(
                                self._apply_gain(bytes(pending)), rs)
                            if out:
                                stream.write(out)
                        except Exception:
                            log.exception("%s: write failed", self._name)
                        pending.clear()
                    playing = False
                    continue
                if epoch != self._epoch:
                    # Stale item dequeued concurrently with interrupt().
                    continue
                if epoch != run_epoch:
                    # First fresh item after interrupt(): reset buffered audio
                    # and streaming-resampler history, but keep this new item.
                    pending.clear()  # interrupted: drop buffered stale audio
                    output_pending.clear()
                    playing = False
                    if rs is not None:
                        rs.clear()
                    run_epoch = epoch
                pending.extend(chunk)
                if not playing and len(pending) < self._prebuffer_bytes:
                    continue  # keep buffering until we have a cushion
                out = self._output_bytes(self._apply_gain(bytes(pending)), rs)
                pending.clear()
                if rs is None:
                    if out:
                        write_one(out)
                else:
                    # soxr can emit 0 or several blocks for a 10 ms input
                    # chunk.  Stage it so PortAudio always receives exact
                    # output-device blocks instead of a bursty 0/17 ms feed.
                    output_pending.extend(out)
                    while len(output_pending) >= output_block_bytes:
                        block = bytes(output_pending[:output_block_bytes])
                        del output_pending[:output_block_bytes]
                        if write_one(block):
                            break

                now = time.monotonic()
                if self._stats_interval and now - stats_started >= self._stats_interval:
                    elapsed = now - stats_started
                    log.info(
                        "%s stats(%.0fs): audio=%.1fs queue=%dms max_queue=%dms "
                        "underflows=%d starved=%d dropped=%d write_max=%.1fms",
                        self._name, elapsed,
                        stats_written_frames / max(1, self._output_rate),
                        self._q.qsize() * self._slice_ms,
                        self._max_queue * self._slice_ms,
                        self._underflows - stats_underflows,
                        self._starvations - stats_starvations,
                        self._queue_drops - stats_drops,
                        self._max_write_ms)
                    stats_started = now
                    stats_written_frames = 0
                    stats_underflows = self._underflows
                    stats_starvations = self._starvations
                    stats_drops = self._queue_drops
                    self._max_queue = self._q.qsize()
                    self._max_write_ms = 0.0
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
                self._max_queue = max(self._max_queue, self._q.qsize())
            except queue.Full:
                self._queue_drops += 1
                if self._max_buffer_ms:
                    # A real-time bridge must stay current.  When the bounded
                    # queue fills, discard one oldest slice and retain the new
                    # microphone audio instead of accumulating seconds of lag.
                    try:
                        self._q.get_nowait()
                        self._q.put_nowait((epoch, pcm[i:i + self._slice_bytes]))
                    except (queue.Empty, queue.Full):
                        pass
                now = time.monotonic()
                if now - self._last_drop_warning >= 5.0:
                    self._last_drop_warning = now
                    if self._max_buffer_ms:
                        log.warning("%s: queue full, dropping oldest audio "
                                    "(bounded at %d ms)", self._name,
                                    self._max_buffer_ms)
                    else:
                        log.warning("%s: queue full, dropping audio", self._name)
                if not self._max_buffer_ms:
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
