"""Failed startup releases audio; a missing monitor preserves primary output.

All capture/player/session objects are fakes. No devices or network are opened.
"""
import asyncio
import pathlib
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vrclt.pipeline import InboundPipeline, OutboundPipeline


class FakeResource:
    def __init__(self, name, fail_start=False, fail_stop=False):
        self.name = name
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.starts = self.stops = 0
        self.running = False
        self.audio = []
        self.removed_taps = []

    def start(self):
        self.starts += 1
        self.running = True  # even partially started resources must unwind
        if self.fail_start:
            raise RuntimeError(f"{self.name} unavailable")

    def stop(self):
        self.stops += 1
        self.running = False
        if self.fail_stop:
            raise RuntimeError(f"{self.name} stop failed")

    def play(self, data):
        assert self.running, f"audio was routed to stopped {self.name}"
        self.audio.append(data)

    def remove_raw_tap(self, tap):
        self.removed_taps.append(tap)


class FakeSegmenter:
    def __init__(self):
        self.flushed = 0

    def flush(self):
        self.flushed += 1


def outbound(failure=None):
    pipeline = object.__new__(OutboundPipeline)
    for name in ("mic", "tts_player", "passthrough", "monitor", "chatbox"):
        setattr(pipeline, name, FakeResource(name, fail_start=name == failure))
    pipeline._passthrough_tap = object()
    pipeline._audio_sinks = (pipeline.tts_player, pipeline.monitor)
    pipeline.segmenter = FakeSegmenter()
    pipeline.tasks_started = []
    pipeline.tasks_closed = []

    async def worker(stop, name):
        pipeline.tasks_started.append(name)
        try:
            await stop.wait()
        finally:
            pipeline.tasks_closed.append(name)

    pipeline._segment_tick = lambda stop: worker(stop, "tick")
    pipeline._route_passthrough = lambda stop: worker(stop, "route")
    return pipeline


def attach_session(pipeline, action=None):
    session = SimpleNamespace(calls=0)

    async def run(stop):
        session.calls += 1
        await asyncio.sleep(0)  # allow background workers to enter their finally
        if action:
            await action(stop)

    session.run = run
    pipeline.session = session
    return session


async def scenario():
    baseline = asyncio.all_tasks()

    # Real incident: the saved optional monitor is absent, but mic/CABLE are
    # available. Disable only monitor fan-out and keep primary translated PCM.
    pipeline = outbound("monitor")
    failed_monitor = pipeline.monitor

    async def send_audio(_stop):
        pipeline._on_audio(b"\x01\x00")

    session = attach_session(pipeline, send_audio)
    with patch("vrclt.pipeline.log.warning") as warning:
        await pipeline.run(asyncio.Event())
    assert session.calls == 1 and pipeline.tts_player.audio == [b"\x01\x00"]
    assert pipeline.monitor is None and failed_monitor.stops == 1
    assert not failed_monitor.audio and failed_monitor not in pipeline._audio_sinks
    assert any("optional monitor unavailable" in call.args[0] for call in warning.call_args_list)
    assert sorted(pipeline.tasks_closed) == ["route", "tick"]
    assert all(not resource.running for resource in (
        pipeline.mic, pipeline.tts_player, pipeline.passthrough, failed_monitor))

    # Failures at any required startup stage propagate, stopping earlier and
    # partially started resources before any translation session is entered.
    for failure in ("mic", "tts_player", "passthrough"):
        pipeline = outbound(failure)
        tap = pipeline._passthrough_tap
        session = attach_session(pipeline)
        try:
            await pipeline.run(asyncio.Event())
        except RuntimeError as exc:
            assert str(exc) == f"{failure} unavailable"
        else:
            raise AssertionError(f"required {failure} startup failure was hidden")
        assert session.calls == 0 and not pipeline.tasks_started
        assert all(not getattr(pipeline, name).running for name in (
            "mic", "tts_player", "passthrough", "monitor"))
        assert pipeline.mic.removed_taps == [tap]
        assert pipeline.chatbox.stops == 1

    # One cleanup error cannot prevent the remaining sinks from shutting down.
    pipeline = outbound()
    pipeline.mic.fail_stop = True
    attach_session(pipeline)
    with patch("vrclt.pipeline.log.exception") as logged:
        await pipeline.run(asyncio.Event())
    assert logged.called
    assert pipeline.tts_player.stops == pipeline.passthrough.stops == pipeline.monitor.stops == 1

    # Inbound audio startup is protected too, including a partially opened
    # output and the capture object's lifecycle flag.
    inbound = object.__new__(InboundPipeline)
    inbound.player = FakeResource("inbound audio", fail_start=True)
    inbound.tap = FakeResource("capture")
    inbound._tap_running = True
    inbound.segmenter = FakeSegmenter()
    session = attach_session(inbound)
    try:
        await inbound.run(asyncio.Event())
    except RuntimeError as exc:
        assert str(exc) == "inbound audio unavailable"
    else:
        raise AssertionError("inbound startup failure was hidden")
    assert not inbound._tap_running and not inbound.player.running
    assert inbound.player.stops == inbound.tap.stops == 1 and session.calls == 0

    # Cancelling an active runtime still cancels workers and releases audio.
    pipeline = outbound()
    entered = asyncio.Event()

    async def wait_forever(stop):
        entered.set()
        await stop.wait()

    attach_session(pipeline, wait_forever)
    task = asyncio.create_task(pipeline.run(asyncio.Event()))
    await entered.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("runtime cancellation was swallowed")
    assert sorted(pipeline.tasks_closed) == ["route", "tick"]
    assert all(not getattr(pipeline, name).running for name in (
        "mic", "tts_player", "passthrough", "monitor"))
    assert asyncio.all_tasks() == baseline, "startup/stop leaked worker tasks"


if __name__ == "__main__":
    asyncio.run(scenario())
    print("smoke_pipeline_startup: OK")
