"""Drive OpenAIRealtimeTranslateSession against a mock realtime endpoint.

The real /v1/realtime/translations service cannot be hit from a test, so a
local websockets server plays it: it asserts what the client sends (auth
header, model query, session.update shape, 24 kHz audio) and replays the
documented server events back.
"""
import asyncio
import base64
import json
import pathlib
import sys

import websockets

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vrclt.openai import session as oai   # noqa: E402
from vrclt.session_base import FatalSessionError  # noqa: E402


class FakeSource:
    """AudioSource over a fixed number of 16 kHz chunks, then silence."""

    def __init__(self, chunks: int = 3, chunk_ms: int = 100):
        samples = 16000 * chunk_ms // 1000
        self.buffer = [b"\x01\x02" * samples for _ in range(chunks)]
        self.requeued: list[bytes] = []
        self.trimmed = False

    def drain(self):
        out, self.buffer = self.buffer, []
        return out

    def requeue(self, chunks):
        self.requeued.extend(chunks)

    def active(self, timeout: float = 2.0) -> bool:
        return True

    def trim_to(self, seconds: float) -> None:
        self.trimmed = True


class MockServer:
    def __init__(self):
        self.session_update = None
        self.auth = None
        self.path = None
        self.audio_bytes = 0
        self.closed_cleanly = False
        self.got_audio = asyncio.Event()

    async def handler(self, ws):
        self.auth = ws.request.headers.get("Authorization")
        self.path = ws.request.path
        await ws.send(json.dumps({"type": "session.created", "session": {}}))
        async for raw in ws:
            event = json.loads(raw)
            etype = event["type"]
            if etype == "session.update":
                self.session_update = event["session"]
                await ws.send(json.dumps({"type": "session.updated", "session": {}}))
            elif etype == "session.input_audio_buffer.append":
                pcm = base64.b64decode(event["audio"])
                if any(pcm):   # ignore the zeroed gap-fill padding
                    self.audio_bytes += len(pcm)
                    await ws.send(json.dumps({
                        "type": "session.input_transcript.delta", "delta": "안녕"}))
                    await ws.send(json.dumps({
                        "type": "session.output_transcript.delta", "delta": "hello"}))
                    await ws.send(json.dumps({
                        "type": "session.output_audio.delta",
                        "delta": base64.b64encode(b"\x11\x22" * 480).decode(),
                        "sample_rate": 24000}))
                    self.got_audio.set()
            elif etype == "session.close":
                self.closed_cleanly = True
                await ws.send(json.dumps({"type": "session.closed"}))
                return


async def _run_session(server: MockServer, port: int, source: FakeSource, sink: dict):
    session = oai.OpenAIRealtimeTranslateSession(
        api_key="sk-test",
        model="gpt-realtime-translate",
        source=source,
        name="test",
        get_target_language=lambda: "en",
        transcribe_model="gpt-realtime-whisper",   # off by default; opt in here
        send_interval_ms=50,
        idle_disconnect_sec=30.0,
        on_src=lambda text, lang: sink.setdefault("src", []).append((text, lang)),
        on_dst=lambda text: sink.setdefault("dst", []).append(text),
        on_audio=lambda pcm: sink.setdefault("audio", []).append(pcm),
    )
    stop = asyncio.Event()
    task = asyncio.ensure_future(session.run(stop))
    await asyncio.wait_for(server.got_audio.wait(), timeout=10.0)
    await asyncio.sleep(0.3)      # let the deltas land
    stop.set()
    await asyncio.wait_for(task, timeout=10.0)
    return session


async def main() -> None:
    server = MockServer()
    sink: dict = {}
    source = FakeSource()
    async with websockets.serve(server.handler, "127.0.0.1", 0) as ws_server:
        port = ws_server.sockets[0].getsockname()[1]
        oai.TRANSLATE_URL = f"ws://127.0.0.1:{port}/v1/realtime/translations"
        session = await _run_session(server, port, source, sink)

    assert server.auth == "Bearer sk-test", server.auth
    assert "model=gpt-realtime-translate" in server.path, server.path

    # session.update carries the documented shape: whisper as the source ASR,
    # the target under audio.output.language
    assert server.session_update == {"audio": {
        "input": {"transcription": {"model": "gpt-realtime-whisper"},
                  "noise_reduction": {"type": "near_field"}},
        "output": {"language": "en"},
    }}, server.session_update

    # 3 x 100 ms of 16 kHz int16 resampled up to 24 kHz (+/- resampler warmup)
    expected = int(16000 * 0.3) * 2 * 24000 // 16000
    assert abs(server.audio_bytes - expected) < 2000, (server.audio_bytes, expected)

    # default is source transcription OFF: no transcription block is sent at all
    default_cfg = oai.OpenAIRealtimeTranslateSession(
        api_key="k", model="m", source=FakeSource(), name="t",
        get_target_language=lambda: "en")._session_config("en")
    assert "transcription" not in default_cfg["audio"].get("input", {}), default_cfg

    assert sink.get("src") and sink["src"][0] == ("안녕", None), sink.get("src")
    assert sink.get("dst") and sink["dst"][0] == "hello", sink.get("dst")
    assert sink.get("audio") and sink["audio"][0] == b"\x11\x22" * 480
    assert server.closed_cleanly, "session.close handshake never ran"
    assert source.trimmed, "pre-roll was not trimmed before connecting"
    assert not session.connected and not session.last_error, session.last_error
    print("  translate session: config, 24 kHz audio, deltas, close handshake OK")


async def unsupported_target_is_fatal() -> None:
    """A target the model cannot speak must fail loudly, not stream silence."""
    session = oai.OpenAIRealtimeTranslateSession(
        api_key="sk-test", model="gpt-realtime-translate",
        source=FakeSource(), name="test",
        get_target_language=lambda: "th",   # Thai: not one of the 13 outputs
    )
    stop = asyncio.Event()
    try:
        await asyncio.wait_for(session.run(stop), timeout=10.0)
    except FatalSessionError as e:
        assert "th" in str(e), e
        print("  unsupported target rejected:", str(e)[:60])
        return
    raise AssertionError("unsupported target did not raise FatalSessionError")


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(unsupported_target_is_fatal())
    print("smoke_openai_session: OK")
