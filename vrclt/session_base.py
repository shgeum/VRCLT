"""Provider-neutral pieces shared by the Live translate sessions.

Both the Gemini session (vrclt.gemini.session) and the Qwen session
(vrclt.qwen.session) expose the same surface to the pipelines:
run(stop) / request_restart() / .connected / .last_error / .error_class /
.next_retry_at, and both consume an AudioSource. This module holds the
symbols they (and app_controller) share so neither provider imports the
other.
"""
import asyncio
import time

RECONNECT_MIN_BACKOFF = 2.0
RECONNECT_MAX_BACKOFF = 30.0


class FatalSessionError(RuntimeError):
    """A non-retriable Live API session error."""


class AudioSource:
    """Interface the session pulls 16 kHz mono int16 PCM from."""

    def drain(self) -> list[bytes]: ...
    def requeue(self, chunks: list[bytes]) -> None: ...
    def active(self, timeout: float = 2.0) -> bool: ...
    def trim_to(self, seconds: float) -> None: ...


async def sleep_interruptible(duration: float, stop: asyncio.Event) -> None:
    end = time.time() + duration
    while time.time() < end and not stop.is_set():
        await asyncio.sleep(0.2)
