"""Gemini Live translate session with auto-reconnect.

SDK facts this code is built around (verified against google-genai 2.8.0 source):
- AsyncSession.receive() terminates after EVERY turn_complete -> the receiver
  must re-enter receive() on the same websocket to keep the session long-lived.
- Any websocket close (including our own session.close(), code 1000) surfaces
  as errors.APIError raised from receive() -> a _closing flag distinguishes
  intentional closes from genuine failures.
- Turn boundaries come from the server's automatic VAD. The client-side gates
  (mic RMS gate, Silero VAD) strip nearly all silence from the stream, so that
  VAD never hears a pause. Cutting the turn instead with audio_stream_end ends
  generation mid-phrase: the model is interpreting simultaneously and is always
  a few words behind, so the tail was stranded until the next utterance
  ("last word never translated"). The sender therefore rebuilds the pauses the
  gates swallowed - zeroed PCM streamed in real time until the server closes
  the turn itself - and only falls back to audio_stream_end if it never does.
"""
import asyncio
import logging
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from ..session_base import (AudioSource, FatalSessionError,
                            RECONNECT_MIN_BACKOFF, RECONNECT_MAX_BACKOFF,
                            sleep_interruptible)

log = logging.getLogger(__name__)

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

INPUT_RATE = 16000  # the AudioSource contract: 16 kHz mono int16
# pause reconstruction for the server VAD: once real audio stopped flowing,
# wait GRACE seconds (drain jitter, not a pause yet), then stream zeroed PCM at
# the send cadence until the server ends the turn - or MAX seconds pass, which
# means its VAD never fired and the turn has to be closed explicitly.
GAP_FILL_GRACE_SEC = 0.25
GAP_FILL_MAX_SEC = 2.5


def _is_invalid_api_key_error(exc: Exception) -> bool:
    text = str(exc).lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return (str(code) == "1007" and "api key" in text) or "api key not valid" in text


def _looks_like_glossary_rejection(exc: Exception) -> bool:
    text = str(exc).lower()
    code = str(getattr(exc, "code", None) or getattr(exc, "status_code", None))
    return code in ("400", "1007", "1008") and "system_instruction" in text


def _classify_session_error(exc: Exception) -> str:
    """Short reason class for UI display: 'quota' | 'network'."""
    text = str(exc).lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if str(code) == "429" or "resource_exhausted" in text or "quota" in text \
            or "rate limit" in text:
        return "quota"
    return "network"


class LiveTranslateSession:
    def __init__(self, *, api_key: str, model: str, source: AudioSource, name: str,
                 get_target_language, echo_target_language: bool = False,
                 enabled=lambda: True,
                 send_interval_ms: int = 100, idle_disconnect_sec: float = 15.0,
                 turn_end_silence_sec: float = 0.55,
                 glossary: str = "",
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
        self._turn_end_silence = max(self._interval, float(turn_end_silence_sec))
        self._on_src = on_src
        self._on_dst = on_dst
        self._on_audio = on_audio
        self._on_turn_complete = on_turn_complete
        self._on_interrupted = on_interrupted
        self._on_session_state = on_session_state
        glossary = str(glossary or "").strip()
        if len(glossary) > 2000:
            log.warning("[%s] glossary truncated to 2000 chars", name)
            glossary = glossary[:2000]
        self._glossary = glossary
        self._glossary_disabled = False
        self.connected = False
        # last-failure diagnostics for the status UIs (written on the session
        # asyncio thread; read lock-free from the Qt/VR threads)
        self.last_error = ""
        self.error_class = ""   # "" | "quota" | "network"
        self.next_retry_at = 0.0
        self._closing = False
        self._restart = False
        # True between the first audio of a turn and the server's turn_complete;
        # the sender stops padding silence as soon as the turn closes on its own
        self._turn_open = False
        # diagnostics (logged every 15s by the watchdog while connected)
        self._st_sent = 0
        self._st_sent_bytes = 0
        self._st_recv = 0
        self._st_src = 0
        self._st_dst = 0

    def request_restart(self) -> None:
        """Apply changed settings (e.g. target language) by reconnecting."""
        self._restart = True

    def _glossary_instruction(self) -> str:
        if not self._glossary or self._glossary_disabled:
            return ""
        return ("Glossary: always translate the following terms exactly as "
                "specified (source=target), overriding your default wording:\n"
                + self._glossary)

    def _model_and_config(self) -> tuple[str, types.LiveConnectConfig]:
        target = self._get_target()
        instr = self._glossary_instruction()
        if target in AGENT_FALLBACK_LANGUAGES:
            system = AGENT_INSTRUCTION.format(
                language=AGENT_FALLBACK_LANGUAGES[target])
            if instr:
                system += "\n\n" + instr
            return AGENT_MODEL, types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                system_instruction=system,
                input_audio_transcription=types.AudioTranscriptionConfig(),
                output_audio_transcription=types.AudioTranscriptionConfig(),
            )
        kwargs = dict(
            response_modalities=["AUDIO"],
            translation_config=types.TranslationConfig(
                target_language_code=target,
                echo_target_language=self._echo,
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )
        if instr:
            # only attached when a glossary is set, so the empty-glossary
            # config stays byte-identical to the pre-glossary behavior
            kwargs["system_instruction"] = instr
        return self._model, types.LiveConnectConfig(**kwargs)

    async def run(self, stop: asyncio.Event) -> None:
        """Supervisor: wait for voice, run sessions, reconnect with backoff."""
        try:
            await self._run_supervisor(stop)
        finally:
            # genai.Client holds httpx sync+async clients and an SSL context
            # bound to this loop; without closing them here every runtime
            # restart would pin them until process exit
            await self._close_client()

    async def _close_client(self) -> None:
        client = self._client
        for closer in (getattr(getattr(client, "aio", None), "aclose", None),
                       getattr(client, "close", None)):
            if closer is None:
                continue
            try:
                result = closer()
                if asyncio.iscoroutine(result):
                    await result
            except (Exception, asyncio.CancelledError):
                # CancelledError included: on a forced stop the sync close
                # below must still get its chance
                log.debug("[%s] client close failed", self.name, exc_info=True)

    async def _run_supervisor(self, stop: asyncio.Event) -> None:
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
            except Exception as e:
                if _is_invalid_api_key_error(e):
                    raise FatalSessionError(
                        "Gemini API key is invalid. Update the API key in Settings."
                    ) from e
                clean = False
                self.error_class = _classify_session_error(e)
                self.last_error = str(e)[:200]
                if self._glossary and not self._glossary_disabled \
                        and _looks_like_glossary_rejection(e):
                    # self-heal: never loop forever on a server that rejects
                    # system_instruction for the translate model
                    self._glossary_disabled = True
                    log.warning("[%s] model rejected the glossary "
                                "system_instruction - continuing without it",
                                self.name)
                log.exception("[%s] session error", self.name)
            if stop.is_set():
                break
            if clean:
                backoff = RECONNECT_MIN_BACKOFF
                await asyncio.sleep(0.2)
            else:
                log.info("[%s] reconnecting in %.0fs", self.name, backoff)
                self.next_retry_at = time.time() + backoff
                await sleep_interruptible(backoff, stop)
                backoff = min(backoff * 2, RECONNECT_MAX_BACKOFF)

    async def _session_once(self, stop: asyncio.Event) -> bool:
        """One Live session. Returns True if it ended cleanly (goAway/idle/stop)."""
        target = self._get_target()
        model, config = self._model_and_config()
        log.info("[%s] connecting (model=%s target=%s echo=%s)",
                 self.name, model, target, self._echo)
        async with self._client.aio.live.connect(model=model, config=config) as session:
            self._closing = False
            self._turn_open = False
            self.connected = True
            # clear on successful connect (not on retry start) so the status
            # UI doesn't flicker between backoff sleeps and connect attempts
            self.last_error = ""
            self.error_class = ""
            self.next_retry_at = 0.0
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
                        self._turn_open = False
                        if self._on_turn_complete:
                            self._on_turn_complete()
                if response.go_away is not None:
                    log.info("[%s] goAway (time_left=%s) - reconnecting",
                             self.name, response.go_away.time_left)
                    return

    async def _sender(self, session) -> None:
        speaking = False
        last_audio = 0.0   # when real audio last went out
        gap_filled = 0.0   # zeroed seconds streamed into the current pause
        fill_chunk = b"\x00" * (int(INPUT_RATE * self._interval) * 2)
        # the connect pre-roll must be flushed even when the handshake took
        # longer than turn_end_silence (active() already false) - otherwise a
        # short utterance that triggered this very connection is dropped
        flush_preroll = True
        while True:
            await asyncio.sleep(self._interval)
            if self._restart or not self._enabled():
                if speaking:
                    try:
                        await session.send_realtime_input(audio_stream_end=True)
                    except Exception:
                        pass
                return
            chunks = self._source.drain()
            if chunks and (flush_preroll or self._source.active(self._turn_end_silence)):
                flush_preroll = False
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
                speaking = True
                self._turn_open = True
                last_audio = time.time()
                gap_filled = 0.0
            elif speaking:
                # The source went quiet (chunks drained on these ticks are
                # sub-gate hangover bridge audio - dropped). The gates stripped
                # the pause the server VAD needs, so rebuild it with zeroed PCM
                # at the send cadence: the model hears a natural pause, finishes
                # the phrase it is still interpreting and ends the turn itself.
                if not self._turn_open:
                    speaking = False  # server already closed it - stop padding
                    continue
                if (time.time() - last_audio) < GAP_FILL_GRACE_SEC:
                    continue  # drain jitter, not a real pause yet
                if gap_filled >= GAP_FILL_MAX_SEC:
                    # the VAD never fired on the reconstructed silence; close
                    # the turn explicitly rather than let the translation hang
                    # until the session does (which stranded the sentence tail)
                    speaking = False
                    self._turn_open = False
                    try:
                        await session.send_realtime_input(audio_stream_end=True)
                    except Exception:
                        return
                    continue
                try:
                    await session.send_realtime_input(
                        audio=types.Blob(data=fill_chunk,
                                         mime_type="audio/pcm;rate=16000"))
                except Exception:
                    return
                gap_filled += self._interval

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
                except Exception:
                    pass
                close_at = time.time() + 2.0  # let final transcripts arrive
                while time.time() < close_at:
                    await asyncio.sleep(0.1)
                    if stop.is_set() or self._restart or not self._enabled():
                        self._closing = True
                        await session.close()
                        return
                    if self._source.active(self._idle_disconnect):
                        log.info("[%s] voice resumed during idle close - keeping session open",
                                 self.name)
                        break
                else:
                    self._closing = True
                    await session.close()
                    return
