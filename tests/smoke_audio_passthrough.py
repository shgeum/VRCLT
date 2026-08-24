"""Deterministic passthrough buffering/rate/diagnostic smoke tests.

No real audio device is opened.  A blocking RawOutputStream stand-in exercises
the same worker thread and queue used by the application.
"""
from __future__ import annotations

import collections
import logging
import pathlib
import sys
import threading
import time
from contextlib import contextmanager

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vrclt.audio import player as player_mod
from vrclt.audio.mic_in import MicCapture
from vrclt.audio.player import PcmPlayer


def wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError("condition timed out")


class FakeRawOutputStream:
    instances: list["FakeRawOutputStream"] = []
    write_results: collections.deque[bool] = collections.deque()
    realtime = False

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.closed = False
        self.writes: list[bytes] = []
        self.__class__.instances.append(self)

    def start(self):
        self.started = True

    def write(self, data):
        self.writes.append(bytes(data))
        if self.__class__.realtime:
            frames = len(data) // 2
            time.sleep(frames / self.kwargs["samplerate"])
        if self.__class__.write_results:
            return self.__class__.write_results.popleft()
        return False

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


@contextmanager
def fake_output(default_rate: int, write_results=(), *, realtime=False):
    originals = (
        player_mod.sd.RawOutputStream,
        player_mod.sd.query_devices,
        player_mod.devices.find_output,
        player_mod.devices.extra_settings,
    )
    FakeRawOutputStream.instances = []
    FakeRawOutputStream.write_results = collections.deque(write_results)
    FakeRawOutputStream.realtime = realtime
    player_mod.sd.RawOutputStream = FakeRawOutputStream
    player_mod.sd.query_devices = lambda _idx: {
        "name": "Fake Cable",
        "default_samplerate": float(default_rate),
    }
    player_mod.devices.find_output = lambda _name: 7
    player_mod.devices.extra_settings = lambda *_args, **_kwargs: None
    try:
        yield
    finally:
        (player_mod.sd.RawOutputStream,
         player_mod.sd.query_devices,
         player_mod.devices.find_output,
         player_mod.devices.extra_settings) = originals


def pcm_ms(milliseconds: int, rate: int = 48000) -> bytes:
    frames = rate * milliseconds // 1000
    # Non-zero ramp catches accidental silence and preserves exact comparison
    # in the no-resampler case.
    x = (np.arange(frames, dtype=np.int32) % 20000 - 10000).astype(np.int16)
    return x.tobytes()


def make_passthrough(**kwargs) -> PcmPlayer:
    return PcmPlayer(
        "Fake Cable", name="passthrough", rate=48000,
        prebuffer_ms=40, slice_ms=10, block_ms=10,
        match_device_rate=True, rebuffer_on_underflow=True,
        max_buffer_ms=200,
        **kwargs,
    )


def check_48k_bit_exact_and_prebuffer() -> None:
    with fake_output(48000):
        p = make_passthrough()
        p.start()
        wait_until(lambda: bool(FakeRawOutputStream.instances))
        stream = FakeRawOutputStream.instances[0]
        assert stream.kwargs["samplerate"] == 48000, stream.kwargs
        assert stream.kwargs["blocksize"] == 480, stream.kwargs
        assert p._q.maxsize == 20

        p.play(pcm_ms(30))
        time.sleep(0.04)
        assert not stream.writes, "audio started before the 40 ms cushion"

        final = pcm_ms(10)
        p.play(final)
        wait_until(lambda: len(stream.writes) == 1)
        assert stream.writes[0] == pcm_ms(30) + final
        p.stop()


def check_endpoint_rate_resampling() -> None:
    for endpoint_rate in (30000, 44100, 96000):
        with fake_output(endpoint_rate):
            p = make_passthrough()
            p.start()
            wait_until(lambda: bool(FakeRawOutputStream.instances))
            stream = FakeRawOutputStream.instances[0]
            block_frames = endpoint_rate // 100
            assert stream.kwargs["samplerate"] == endpoint_rate, stream.kwargs
            assert stream.kwargs["blocksize"] == block_frames, stream.kwargs
            p.play(pcm_ms(40))
            wait_until(lambda: len(stream.writes) >= 2)
            # Stateful soxr output is bursty for small input chunks.  The
            # player must stage it into exact 10 ms endpoint-rate writes.
            assert all(len(block) == block_frames * 2
                       for block in stream.writes), \
                [len(block) for block in stream.writes]
            assert p.stats()["output_rate"] == endpoint_rate
            p.stop()


def check_underflow_rebuffers() -> None:
    # First write starts playback; the second is an actual in-run underrun.
    with fake_output(48000, write_results=(False, True, False)):
        p = make_passthrough()
        p.start()
        wait_until(lambda: bool(FakeRawOutputStream.instances))
        stream = FakeRawOutputStream.instances[0]
        p.play(pcm_ms(50))
        wait_until(lambda: len(stream.writes) >= 2)
        wait_until(lambda: p.stats()["underflows"] == 1)

        # The underrun disarms playback.  Thirty milliseconds is insufficient;
        # the fourth 10 ms chunk rebuilds the configured cushion.
        p.play(pcm_ms(30))
        time.sleep(0.04)
        assert len(stream.writes) == 2, len(stream.writes)
        p.play(pcm_ms(10))
        wait_until(lambda: len(stream.writes) == 3)
        p.stop()


def check_bursty_arrival_uses_cushion() -> None:
    # Two 10 ms chunks arriving together every 20 ms model the 8 ms polling
    # bridge and ordinary scheduler jitter while preserving the source rate.
    with fake_output(48000, realtime=True):
        p = make_passthrough()
        p.start()
        wait_until(lambda: bool(FakeRawOutputStream.instances))
        for _ in range(35):
            p.play(pcm_ms(20))
            time.sleep(0.02)
        assert p.stats()["starvations"] == 0, p.stats()
        assert p.stats()["underflows"] == 0, p.stats()
        p.stop()


def check_interrupt_is_not_starvation() -> None:
    with fake_output(48000):
        p = make_passthrough()
        p.start()
        wait_until(lambda: bool(FakeRawOutputStream.instances))
        stream = FakeRawOutputStream.instances[0]
        p.play(pcm_ms(40))
        wait_until(lambda: bool(stream.writes))
        p.interrupt()
        time.sleep(0.04)
        assert p.stats()["starvations"] == 0, p.stats()
        p.stop()


class FakeStatus:
    def __bool__(self):
        return True

    def __str__(self):
        return "input overflow"


class IdentityResampler:
    def resample_chunk(self, x):
        return x


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def check_mic_status_is_visible() -> None:
    mic = MicCapture()
    rs = IdentityResampler()
    mic._rs = rs
    tap = mic.add_raw_tap()
    handler = ListHandler()
    mic_log = logging.getLogger("vrclt.audio.mic_in")
    old_level = mic_log.level
    mic_log.setLevel(logging.INFO)
    mic_log.addHandler(handler)
    try:
        mic._st_started = time.monotonic() - 16.0
        raw = pcm_ms(10)
        mic._callback(raw, 480, None, FakeStatus(), rs, None, 48000)
    finally:
        mic_log.removeHandler(handler)
        mic_log.setLevel(old_level)
    assert tap.popleft() == raw
    assert any("mic callback status: input overflow" in m
               for m in handler.messages), handler.messages
    assert any("mic stats(" in m and "status=1" in m
               for m in handler.messages), handler.messages


def main() -> None:
    check_48k_bit_exact_and_prebuffer()
    check_endpoint_rate_resampling()
    check_underflow_rebuffers()
    check_bursty_arrival_uses_cushion()
    check_interrupt_is_not_starvation()
    check_mic_status_is_visible()
    print("smoke_audio_passthrough: OK")


if __name__ == "__main__":
    main()
