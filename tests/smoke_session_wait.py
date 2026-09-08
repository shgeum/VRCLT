"""Reconnect waits wake on stop, expire promptly, and leave no waiter tasks."""
import asyncio
import pathlib
import sys
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vrclt.session_base import sleep_interruptible


async def scenario():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    baseline = asyncio.all_tasks()

    # Backoff expiry must not poll via asyncio.sleep, even for short delays.
    with patch("vrclt.session_base.asyncio.sleep",
               side_effect=AssertionError("reconnect wait polled")):
        await asyncio.wait_for(sleep_interruptible(0.01, stop), timeout=0.15)
        assert not stop.is_set()

        # Stopping a long backoff wakes immediately through the event.
        handle = loop.call_later(0.01, stop.set)
        try:
            await asyncio.wait_for(sleep_interruptible(30.0, stop), timeout=0.15)
        finally:
            handle.cancel()
        assert stop.is_set()
        await sleep_interruptible(30.0, stop)
        stop.clear()
        await sleep_interruptible(0, stop)
        await sleep_interruptible(-1, stop)

        # Runtime cancellation propagates and removes the inner Event waiter.
        task = asyncio.create_task(sleep_interruptible(30.0, stop))
        handle = loop.call_later(0.01, task.cancel)
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("reconnect wait swallowed cancellation")
        finally:
            handle.cancel()

    assert asyncio.all_tasks() == baseline, "reconnect wait leaked background tasks"


if __name__ == "__main__":
    asyncio.run(scenario())
    print("smoke_session_wait: OK")
