"""Feed committed translation tokens to Soniox's streaming TTS API.

One WebSocket per utterance keeps playback ordered and allows cancellation to
close every outstanding stream at once. Text is sent as it becomes final; we
do not wait for the whole sentence before starting audio generation.
https://soniox.com/docs/api-reference/tts/websocket-api
"""
import asyncio
import base64
import json

import websockets

TTS_URL = "wss://tts-rt.soniox.com/tts-websocket"
TTS_MODEL = "tts-rt-v2"
DEFAULT_VOICE = "Daniel"
MAX_PENDING_CHARS = 10000


class StreamingSpeech:
    def __init__(self, *, api_key, model, voice, language, on_audio,
                 can_play, check_error, wire_logger):
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._language = language
        self._on_audio = on_audio
        self._can_play = can_play
        self._check_error = check_error
        self._wire_logger = wire_logger
        self._queue = asyncio.Queue(maxsize=128)
        self._pending_chars = 0
        self._open = False
        self._counter = 0
        self.idle = asyncio.Event()
        self.idle.set()

    def add(self, text: str) -> None:
        if not text:
            return
        if self._pending_chars + len(text) > MAX_PENDING_CHARS:
            raise RuntimeError("Soniox speech output is too far behind; reconnecting.")
        self._put(text)
        self._pending_chars += len(text)
        self._open = True
        self.idle.clear()

    def end(self) -> None:
        if self._open:
            self._put(None)
            self._open = False

    def _put(self, value) -> None:
        try:
            self._queue.put_nowait(value)
        except asyncio.QueueFull:
            raise RuntimeError("Soniox speech output queue is full; reconnecting.") from None

    async def run(self) -> None:
        while True:
            first = await self._queue.get()
            if first is None:
                continue
            # Bound a stalled service or a lost endpoint. Cancellation also
            # reaches both sender and receiver, including during connect.
            async with asyncio.timeout(90.0):
                await self._synthesize(first)
            if self._queue.empty():
                self.idle.set()

    async def _synthesize(self, first: str) -> None:
        self._counter += 1
        stream_id = f"vrclt-{self._counter}"
        async with websockets.connect(
            TTS_URL, open_timeout=10, close_timeout=2, max_size=2**21,
            logger=self._wire_logger,
        ) as ws:
            await ws.send(json.dumps({
                "api_key": self._api_key,
                "model": self._model,
                "language": self._language,
                "voice": self._voice,
                "audio_format": "pcm_s16le",
                "sample_rate": 24000,
                "stream_id": stream_id,
            }))
            sender = asyncio.create_task(self._send_text(ws, stream_id, first))
            receiver = asyncio.create_task(self._receive_audio(ws, stream_id))
            tasks = {sender, receiver}
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
                if receiver in done and not sender.done():
                    raise RuntimeError("Soniox TTS terminated before text was complete.")
                # text_end is only step one: wait for audio_end AND the terminal
                # terminated event before opening the next utterance.
                await asyncio.wait_for(receiver, timeout=30.0)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_text(self, ws, stream_id: str, first: str) -> None:
        text = first
        while True:
            if text is None:
                await ws.send(json.dumps({
                    "stream_id": stream_id, "text": "", "text_end": True,
                }))
                return
            # The API caps each text message at 5000 characters.
            for offset in range(0, len(text), 4000):
                await ws.send(json.dumps({
                    "stream_id": stream_id,
                    "text": text[offset:offset + 4000], "text_end": False,
                }, ensure_ascii=False))
            self._pending_chars -= len(text)
            text = await self._queue.get()

    async def _receive_audio(self, ws, stream_id: str) -> None:
        ended = False
        carry = b""
        async for raw in ws:
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise RuntimeError("Soniox TTS returned an invalid response.")
            self._check_error(event)
            if event.get("stream_id") != stream_id:
                continue
            if event.get("audio"):
                # PCM frame boundaries need not coincide with sample boundaries.
                pcm = carry + base64.b64decode(event["audio"], validate=True)
                whole = len(pcm) & ~1
                carry = pcm[whole:]
                if whole and self._can_play():
                    self._on_audio(pcm[:whole])
            if event.get("audio_end"):
                ended = True
            if event.get("terminated"):
                if not ended or carry:
                    raise RuntimeError("Soniox TTS ended with incomplete audio.")
                return
        raise RuntimeError("Soniox TTS disconnected before stream termination.")
