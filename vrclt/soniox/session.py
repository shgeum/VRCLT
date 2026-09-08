"""Soniox live STT/translation with optional streaming TTS and reconnect.

Protocol: JSON config, 16 kHz mono PCM16 binary frames, final token deltas,
<end>/<fin> utterance boundaries, empty text frame then finished on close.
Provisional tokens are deliberately not appended to the shared Segmenter or
spoken: the API replaces them on every response. Committed tokens stream
immediately and are emitted once, without accumulating session transcripts.
https://soniox.com/docs/api-reference/stt/websocket-api
"""
import asyncio
import json
import logging
import time

import websockets

from ..languages import SONIOX_LANGUAGES, soniox_language_code
from ..session_base import (AudioSource, FatalSessionError,
                            RECONNECT_MIN_BACKOFF, RECONNECT_MAX_BACKOFF,
                            sleep_interruptible)
from .tts import DEFAULT_VOICE, TTS_MODEL, StreamingSpeech

log = logging.getLogger(__name__)
# Config frames contain the API key. Do not let the websockets DEBUG frame
# logger expose it even when the application's diagnostic level is DEBUG.
_wire_log = logging.getLogger("vrclt.soniox.wire")
_wire_log.setLevel(logging.WARNING)

TRANSCRIBE_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
TRANSCRIBE_MODEL = "stt-rt-v5"
GAP_FILL_GRACE_SEC = 0.25
GAP_FILL_MAX_SEC = 2.5
KEEPALIVE_SEC = 5.0


class _ServerError(RuntimeError):
    def __init__(self, code: int, kind: str, message: str):
        self.code = code
        self.kind = kind
        super().__init__(f"Soniox {code} ({kind}): {message}")


def _glossary_terms(glossary: str) -> list[dict]:
    terms = []
    for line in str(glossary or "").splitlines():
        source, separator, target = line.partition("=")
        if separator and source.strip() and target.strip():
            terms.append({"source": source.strip(), "target": target.strip()})
    return terms


class SonioxLiveTranslateSession:
    def __init__(self, *, api_key: str, model: str, source: AudioSource, name: str,
                 get_target_language, get_source_language=lambda: "",
                 tts_model: str = TTS_MODEL, voice: str = DEFAULT_VOICE,
                 enabled=lambda: True, send_interval_ms: int = 100,
                 idle_disconnect_sec: float = 15.0,
                 turn_end_silence_sec: float = 0.55, glossary: str = "",
                 on_src=None, on_dst=None, on_audio=None, on_turn_complete=None,
                 on_interrupted=None, on_session_state=None,
                 speaker_metadata: bool = False):
        self._api_key = str(api_key or "").strip()
        self._model = str(model or TRANSCRIBE_MODEL).strip() or TRANSCRIBE_MODEL
        self._tts_model = str(tts_model or TTS_MODEL).strip() or TTS_MODEL
        self._voice = str(voice or DEFAULT_VOICE).strip() or DEFAULT_VOICE
        self._source = source
        self.name = name
        self._get_target = get_target_language
        self._get_source = get_source_language
        self._enabled = enabled
        self._interval = max(0.05, send_interval_ms / 1000.0)
        self._idle_disconnect = max(0.0, float(idle_disconnect_sec))
        self._turn_end_silence = max(self._interval, float(turn_end_silence_sec))
        self._terms = _glossary_terms(glossary)
        self._on_src = on_src
        self._on_dst = on_dst
        self._on_audio = on_audio
        self._on_turn_complete = on_turn_complete
        self._on_interrupted = on_interrupted
        self._on_session_state = on_session_state
        self._speaker_metadata = speaker_metadata
        self._pending_speakers: set[str | None] = set()
        self._restart = False
        self._closing = False
        self._finished = asyncio.Event()
        self._speech = None
        self._turn_has_text = False
        self._stop = None
        self.connected = False
        self.last_error = ""
        self.error_class = ""
        self.next_retry_at = 0.0

    def request_restart(self) -> None:
        self._restart = True

    def _safe_error(self, value) -> str:
        message = str(value)
        if self._api_key:
            message = message.replace(self._api_key, "[redacted]")
        return message[:300]

    def _check_error(self, event: dict) -> None:
        if not event.get("error_code"):
            return
        code = int(event["error_code"])
        kind = str(event.get("error_type") or "unknown_error")
        message = self._safe_error(event.get("error_message") or kind)
        if code == 401 or kind == "unauthenticated":
            raise FatalSessionError(
                "Soniox API key is invalid. Update the Soniox API key in Settings.")
        if code in (400, 403):
            raise FatalSessionError(f"Soniox configuration error: {message}")
        raise _ServerError(code, kind, message)

    def _session_config(self, target: str) -> dict:
        if target not in SONIOX_LANGUAGES:
            raise FatalSessionError(
                f"Soniox cannot translate into {target or 'this language'}. "
                "Choose a supported target language in Settings.")
        source = soniox_language_code(self._get_source())
        if source and source not in SONIOX_LANGUAGES:
            raise FatalSessionError(
                f"Soniox does not support the source language hint {source}. "
                "Choose a supported source language or Auto.")
        cfg = {
            "api_key": self._api_key,
            "model": self._model,
            "audio_format": "pcm_s16le",
            "sample_rate": 16000,
            "num_channels": 1,
            "enable_language_identification": True,
            "enable_speaker_diarization": True,
            "enable_endpoint_detection": True,
            # Avoid aggressive endpointing: it reduces speaker accuracy.
            "max_endpoint_delay_ms": 2000,
            "translation": {"type": "one_way", "target_language": target},
        }
        if source:
            cfg["language_hints"] = [source]
        if self._terms:
            cfg["context"] = {"translation_terms": self._terms}
        return cfg

    async def run(self, stop: asyncio.Event) -> None:
        self._stop = stop
        backoff = RECONNECT_MIN_BACKOFF
        while not stop.is_set():
            if not (self._enabled() and self._source.active()):
                await asyncio.sleep(0.2)
                continue
            self._source.trim_to(1.0)
            self._restart = False
            try:
                await self._session_once(stop)
            except FatalSessionError:
                raise
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status == 401:
                    raise FatalSessionError(
                        "Soniox API key is invalid. Update it in Settings.") from None
                code = getattr(exc, "code", status)
                self.error_class = "quota" if code in (402, 429) else "network"
                self.last_error = self._safe_error(exc)
                log.warning("[%s] %s", self.name, self.last_error)
                if stop.is_set():
                    break
                self.next_retry_at = time.time() + backoff
                await sleep_interruptible(backoff, stop)
                backoff = min(backoff * 2, RECONNECT_MAX_BACKOFF)
            else:
                backoff = RECONNECT_MIN_BACKOFF
                if not stop.is_set():
                    await asyncio.sleep(0.2)

    def _can_play(self) -> bool:
        return (self._enabled() and not self._restart
                and not (self._stop and self._stop.is_set()))

    async def _session_once(self, stop: asyncio.Event) -> None:
        target = soniox_language_code(self._get_target())
        cfg = self._session_config(target)
        self._closing = False
        self._finished = asyncio.Event()
        self._turn_has_text = False
        self._pending_speakers.clear()
        self._speech = StreamingSpeech(
            api_key=self._api_key, model=self._tts_model, voice=self._voice,
            language=target, on_audio=self._on_audio, can_play=self._can_play,
            check_error=self._check_error, wire_logger=_wire_log,
        ) if self._on_audio else None
        async with websockets.connect(
            TRANSCRIBE_URL, open_timeout=10, close_timeout=2, max_size=2**21,
            logger=_wire_log,
        ) as ws:
            await ws.send(json.dumps(cfg, ensure_ascii=False))
            self.connected = True
            self.last_error = self.error_class = ""
            self.next_retry_at = 0.0
            if self._on_session_state:
                self._on_session_state(True)
            log.info("[%s] Soniox session started (model=%s target=%s voice=%s)",
                     self.name, self._model, target, self._voice if self._speech else "off")
            receiver = asyncio.create_task(self._receiver(ws))
            tasks = {receiver, asyncio.create_task(self._sender(ws)),
                     asyncio.create_task(self._watchdog(ws, stop))}
            speech_task = asyncio.create_task(self._speech.run()) if self._speech else None
            if speech_task:
                tasks.add(speech_task)
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
                # Idle closure drains the last utterance. Stop, disable and
                # language change cancel it instead, so stale audio never leaks.
                if self._finished.is_set() and self._speech and self._can_play():
                    drain = asyncio.create_task(self._speech.idle.wait())
                    tasks.add(drain)
                    finished, _ = await asyncio.wait(
                        {drain, speech_task}, timeout=5,
                        return_when=asyncio.FIRST_COMPLETED)
                    for task in finished:
                        task.result()
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self.connected = False
                self._speech = None
                self._finish_turn()
                if (not self._can_play()) and self._on_interrupted:
                    self._on_interrupted()
                if self._on_session_state:
                    self._on_session_state(False)
                log.info("[%s] Soniox session ended", self.name)

    async def _receiver(self, ws) -> None:
        async for raw in ws:
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise RuntimeError("Soniox returned an invalid response.")
            self._check_error(event)
            self._consume_tokens(event.get("tokens") or [])
            if event.get("finished"):
                self._finish_turn()
                self._finished.set()
                return
        if not self._closing:
            raise RuntimeError("Soniox disconnected before the stream was finished.")

    def _consume_tokens(self, tokens: list) -> None:
        for token in tokens:
            if not isinstance(token, dict) or not token.get("is_final"):
                continue
            text = str(token.get("text") or "")
            if text in ("<end>", "<fin>"):
                self._finish_turn()
                continue
            if not text or (text.startswith("<") and text.endswith(">")):
                continue
            self._turn_has_text = True
            status = token.get("translation_status")
            speaker = token.get("speaker")
            speaker = str(speaker) if speaker is not None and speaker != "" else None
            if status == "translation":
                # Explicit token provenance wins. A translation can arrive
                # after several source speakers, so a global "last speaker"
                # would silently attribute somebody else's words to them.
                if speaker is None and len(self._pending_speakers) == 1:
                    speaker = next(iter(self._pending_speakers))
                if self._on_dst:
                    if self._speaker_metadata:
                        self._on_dst(text, speaker)
                    else:
                        self._on_dst(text)
                if self._speech:
                    self._speech.add(text)
            else:
                self._pending_speakers.add(speaker)
                if self._on_src:
                    if self._speaker_metadata:
                        self._on_src(text, token.get("language"), speaker)
                    else:
                        self._on_src(text, token.get("language"))

    def _finish_turn(self) -> None:
        self._pending_speakers.clear()
        if self._speech:
            self._speech.end()
        if self._turn_has_text:
            self._turn_has_text = False
            if self._on_turn_complete:
                self._on_turn_complete()

    async def _sender(self, ws) -> None:
        last_audio = last_send = time.monotonic()
        gap_filled = GAP_FILL_MAX_SEC
        flush_preroll = True
        fill = b"\x00" * (int(16000 * self._interval) * 2)
        while True:
            if self._closing or self._restart or not self._enabled():
                await asyncio.sleep(self._interval)
                continue
            chunks = self._source.drain()
            now = time.monotonic()
            if chunks and (flush_preroll or self._source.active(self._turn_end_silence)):
                sent = False
                try:
                    await ws.send(b"".join(chunks))
                    sent = True
                finally:
                    if not sent:
                        self._source.requeue(chunks)
                flush_preroll = False
                last_audio = last_send = now
                gap_filled = 0.0
            elif gap_filled < GAP_FILL_MAX_SEC and now - last_audio >= GAP_FILL_GRACE_SEC:
                # The capture gates remove silence. Rebuild enough of it for
                # semantic endpoints; then use keepalive to reduce bandwidth.
                # Soniox bills the full connected stream, including pauses.
                await ws.send(fill)
                gap_filled += self._interval
                last_send = now
            elif now - last_send >= KEEPALIVE_SEC:
                await ws.send(json.dumps({"type": "keepalive"}))
                last_send = now
            await asyncio.sleep(self._interval)

    async def _watchdog(self, ws, stop: asyncio.Event) -> None:
        while True:
            await asyncio.sleep(0.2)
            if (stop.is_set() or self._restart or not self._enabled()
                    or (self._idle_disconnect > 0
                        and not self._source.active(self._idle_disconnect))):
                self._closing = True
                await ws.send("")
                try:
                    await asyncio.wait_for(self._finished.wait(), timeout=3)
                except asyncio.TimeoutError:
                    log.debug("[%s] Soniox finish timed out", self.name)
                return
