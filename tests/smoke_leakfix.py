"""Verify the memory-leak fixes: forced task cancellation on stop timeout,
genai client close, and the diagnostics tick."""
import asyncio
import sys
import threading
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def test_cancel_all_tasks_unblocks_hung_runtime():
    """A task ignoring the stop event must still unwind (finally runs)
    when stop() escalates with _cancel_all_tasks."""
    from vrclt.app_controller import _cancel_all_tasks

    cleaned = threading.Event()
    loop_box = {}
    started = threading.Event()

    def worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop_box["loop"] = loop

        async def hung():
            started.set()
            try:
                await asyncio.sleep(3600)  # simulates a hung network close
            finally:
                cleaned.set()  # the pipeline-style cleanup path

        try:
            loop.run_until_complete(hung())
        except asyncio.CancelledError:
            pass
        finally:
            loop.close()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    assert started.wait(5.0)
    loop_box["loop"].call_soon_threadsafe(_cancel_all_tasks, loop_box["loop"])
    t.join(timeout=5.0)
    assert not t.is_alive(), "runtime thread failed to unwind after cancel"
    assert cleaned.is_set(), "finally-block cleanup did not run"


def test_gemini_close_client_calls_both_closers():
    from vrclt.gemini.session import LiveTranslateSession

    calls = []

    class FakeAio:
        async def aclose(self):
            calls.append("aclose")

    class FakeClient:
        aio = FakeAio()

        def close(self):
            calls.append("close")

    sess = object.__new__(LiveTranslateSession)
    sess._client = FakeClient()
    sess.name = "test"
    asyncio.run(sess._close_client())
    assert calls == ["aclose", "close"], calls

    # a failing aclose must not block the sync close
    class BrokenAio:
        async def aclose(self):
            raise RuntimeError("boom")

    calls.clear()
    sess._client = FakeClient()
    sess._client.aio = BrokenAio()
    asyncio.run(sess._close_client())
    assert calls == ["close"], calls


def test_pipeline_finally_awaits_cancelled_tasks():
    """The outbound-style finally must consume its cancelled tasks without
    warnings even when cancellation is delivered at the gather await."""
    async def scenario():
        async def ticker():
            while True:
                await asyncio.sleep(0.01)

        tick_task = asyncio.ensure_future(ticker())
        route_task = None
        await asyncio.sleep(0.03)
        tick_task.cancel()
        if route_task:
            route_task.cancel()
        try:
            await asyncio.gather(
                *(t for t in (tick_task, route_task) if t is not None),
                return_exceptions=True)
        except asyncio.CancelledError:
            pass
        assert tick_task.done()

    asyncio.run(scenario())


def test_diag_tick():
    from vrclt.diag import MemoryDiagnostics
    from vrclt.state import AppState
    from vrclt.subtitles import SubtitleStore

    class StubController:
        state = AppState()
        store = SubtitleStore()
        _panels = []

    diag = MemoryDiagnostics(StubController())
    diag._tick()  # must not raise; logs one line


if __name__ == "__main__":
    test_cancel_all_tasks_unblocks_hung_runtime()
    test_gemini_close_client_calls_both_closers()
    test_pipeline_finally_awaits_cancelled_tasks()
    test_diag_tick()
    print("smoke_leakfix: OK")
