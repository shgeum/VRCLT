"""Gemini Live translate session with auto-reconnect.

SDK facts this code is built around (verified against google-genai 2.8.0 source):
- AsyncSession.receive() terminates after EVERY turn_complete -> the receiver
  must re-enter receive() on the same websocket to keep the session long-lived.
- Any websocket close (including our own session.close(), code 1000) surfaces
  as errors.APIError raised from receive() -> a _closing flag distinguishes
  intentional closes from genuine failures.
"""
import asyncio
import logging
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

log = logging.getLogger(__name__)

RECONNECT_MIN_BACKOFF = 2.0
RECONNECT_MAX_BACKOFF = 30.0

# languages the dedicated translate model does NOT support; for these we fall
# back to a conversational live model with an interpreter system instruction
# (works, but speaks with a stock voice instead of replicating the speaker)
AGENT_FALLBACK_LANGUAGES = {
    "yue": "Cantonese",
}
AGENT_MODEL = "gemini-3.1-flash-live-preview"
AGENT_INSTRUCTION = (
    "You are a professional simultaneous interpreter. Translate everything "
    "you hear into {language}. Speak ONLY the translation - never answer "
    "questions, never add commentary. Keep the original meaning and tone."
)


class AudioSource:
    """Interface the session pulls 16 kHz mono int16 PCM from."""

    def drain(self) -> list[bytes]: ...
    def requeue(self, chunks: list[bytes]) -> None: ...
    def active(self, timeout: float = 2.0) -> bool: ...
    def trim_to(self, seconds: float) -> None: ...


class LiveTranslateSession:
    def __init__(self, *, api_key: str, model: str, source: AudioSource, name: str,
                 get_target_language, echo_target_language: bool = False,
                 enabled=lambda: True,
                 send_interval_ms: int = 100, idle_disconnect_sec: float = 15.0,
                 on_src=None, on_dst=None, on_audio=None, on_turn_complete=None,
                 on_interrupted=None, on_session_state=None):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._get_target = get_target_language
        self._echo = echo_target_language
        self._enabled = enabled
        self._source = source
        self.name = name
        self._interval = max(0.05, send_interval_ms / 1000.0)
        self._idle_disconnect = idle_disconnect_sec
        self._on_src = on_src
        self._on_dst = on_dst
        self._on_audio = on_audio
        self._on_turn_complete = on_turn_complete
        self._on_interrupted = on_interrupted
        self._on_session_state = on_session_state
        self.connected = False
        self._closing = False
        self._restart = False
        # diagnostics (logged every 15s by the watchdog while connected)
        self._st_sent = 0
        self._st_sent_bytes = 0
        self._st_recv = 0
        self._st_src = 0
        self._st_dst = 0

    def request_restart(self) -> None:
        """Apply changed settings (e.g. target language) by reconnecting."""
        self._restart = True

    def _model_and_config(self) -> tuple[str, types.LiveConnectConfig]:
        target = self._get_target()
        if target in AGENT_FALLBACK_LANGUAGES:
            return AGENT_MODEL, types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                system_instruction=AGENT_INSTRUCTION.format(
                    language=AGENT_FALLBACK_LANGUAGES[target]),
                input_audio_transcription=types.AudioTranscriptionConfig(),
                output_audio_transcription=types.AudioTranscriptionConfig(),
            )
        return self._model, types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            translation_config=types.TranslationConfig(
                target_language_code=target,
                echo_target_language=self._echo,
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def run(self, stop: asyncio.Event) -> None:
        """Supervisor: wait for voice, run sessions, reconnect with backoff."""
        backoff = RECONNECT_MIN_BACKOFF
        waiting_logged = False
        while not stop.is_set():
            if not (self._enabled() and self._source.active()):
                if not waiting_logged:
                    waiting_logged = True
                    log.info("[%s] idle (%s) - session closed",
                             self.name, "disabled" if not self._enabled() else "no voice")
                await asyncio.sleep(0.2)
                continue
            if waiting_logged:
                waiting_logged = False
                log.info("[%s] voice detected - connecting", self.name)

            # drop stale buffered silence; keep ~1s pre-roll of speech onset
            self._source.trim_to(1.0)
            self._restart = False
            try:
                clean = await self._session_once(stop)
            except Exception:
                clean = False
                log.exception("[%s] session error", self.name)
            if stop.is_set():
                break
            if clean:
                backoff = RECONNECT_MIN_BACKOFF
                await asyncio.sleep(0.2)
            else:
                log.info("[%s] reconnecting in %.0fs", self.name, backoff)
                await _sleep_interruptible(backoff, stop)
                backoff = min(backoff * 2, RECONNECT_MAX_BACKOFF)

    async def _session_once(self, stop: asyncio.Event) -> bool:
        """One Live session. Returns True if it ended cleanly (goAway/idle/stop)."""
        target = self._get_target()
        model, config = self._model_and_config()
        log.info("[%s] connecting (model=%s target=%s echo=%s)",
                 self.name, model, target, self._echo)
        async with self._client.aio.live.connect(model=model, config=config) as session:
            self._closing = False
            self.connected = True
            if self._on_session_state:
                self._on_session_state(True)
            log.info("[%s] session started (target=%s)", self.name, target)
            recv_t = asyncio.ensure_future(self._receiver(session))
            send_t = asyncio.ensure_future(self._sender(session))
            watch_t = asyncio.ensure_future(self._watchdog(session, stop))
            tasks = {recv_t, send_t, watch_t}
            try:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                # tasks must finish before the websocket closes under them, and
                # cancelled tasks must be awaited so exceptions are retrieved
                await asyncio.gather(*pending, return_exceptions=True)
                error = None
                for t in done:
                    if t.cancelled():
                        continue
                    exc = t.exception()
                    if exc is not None and error is None:
                        error = exc
                if error is not None:
                    if isinstance(error, genai_errors.APIError) and \
                            (self._closing or getattr(error, "code", None) in (1000, 1001)):
                        log.info("[%s] connection closed cleanly (code=%s)",
                                 self.name, getattr(error, "code", None))
                        return True
                    if self._closing:
                        return True
                    raise error
                return True  # receiver returned (goAway) or watchdog closed intentionally
            finally:
                self.connected = False
                if self._on_session_state:
                    self._on_session_state(False)
                log.info("[%s] session ended", self.name)

    async def _receiver(self, session) -> None:
        # SDK 2.8.0: receive() ends after each turn_complete -> re-enter on the
        # same websocket; an actual socket close raises APIError from inside it.
        while True:
            async for response in session.receive():
                self._st_recv += 1
                sc = response.server_content
                if sc is not None:
                    it = sc.input_transcription
                    if it is not None and it.text:
                        self._st_src += 1
                        if self._on_src:
                            self._on_src(it.text, getattr(it, "language_code", None))
                    ot = sc.output_transcription
                    if ot is not None and ot.text:
                        self._st_dst += 1
                        if self._on_dst:
                            self._on_dst(ot.text)
                    if sc.model_turn is not None and self._on_audio:
                        for part in (sc.model_turn.parts or []):
                            if part.inline_data is not None and \
                                    isinstance(part.inline_data.data, (bytes, bytearray)):
                                self._on_audio(bytes(part.inline_data.data))
                    if getattr(sc, "interrupted", None):
                        log.info("[%s] interrupted (barge-in)", self.name)
                        if self._on_interrupted:
                            self._on_interrupted()
                    if getattr(sc, "turn_complete", None):
                        if self._on_turn_complete:
                            self._on_turn_complete()
                if response.go_away is not None:
                    log.info("[%s] goAway (time_left=%s) - reconnecting",
                             self.name, response.go_away.time_left)
                    return

    async def _sender(self, session) -> None:
        speaking = False
        while True:
            await asyncio.sleep(self._interval)
            chunks = self._source.drain()
            if not chunks:
                # no audio this tick: if speech just ended, tell the server the
                # turn is over so it flushes the rest of the translation NOW
                # instead of holding it until the session closes (which split a
                # sentence into "私が自分で" + a 15s-late "作りました")
                if speaking:
                    speaking = False
                    try:
                        await session.send_realtime_input(audio_stream_end=True)
                    except Exception:
                        return
                continue
            speaking = True
            pcm = b"".join(chunks)
            sent = False
            try:
                await session.send_realtime_input(
                    audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))
                sent = True
                self._st_sent += 1
                self._st_sent_bytes += len(pcm)
            finally:
                if not sent:
                    # connection died or task cancelled mid-send:
                    # requeue so the next session resends
                    self._source.requeue(chunks)

    async def _watchdog(self, session, stop: asyncio.Event) -> None:
        last_stats = time.time()
        while True:
            await asyncio.sleep(0.2)
            if (time.time() - last_stats) >= 15.0:
                last_stats = time.time()
                qlen = len(getattr(self._source, "buffer", ()))
                log.info("[%s] stats(15s): sent=%d msg/%.0fKB recv=%d fr "
                         "src+%d dst+%d queue=%d",
                         self.name, self._st_sent, self._st_sent_bytes / 1024,
                         self._st_recv, self._st_src, self._st_dst, qlen)
                self._st_sent = self._st_sent_bytes = 0
                self._st_recv = self._st_src = self._st_dst = 0
            if stop.is_set() or self._restart or not self._enabled():
                self._closing = True
                await session.close()
                return
            if not self._source.active(self._idle_disconnect):
                log.info("[%s] voice idle %.0fs - flushing and closing",
                         self.name, self._idle_disconnect)
                try:
                    await session.send_realtime_input(audio_stream_end=True)
                    await asyncio.sleep(2.0)  # let final transcripts arrive
                except Exception:
                    pass
                self._closing = True
                await session.close()
                return


async def _sleep_interruptible(duration: float, stop: asyncio.Event) -> None:
    end = time.time() + duration
    while time.time() < end and not stop.is_set():
        await asyncio.sleep(0.2)
