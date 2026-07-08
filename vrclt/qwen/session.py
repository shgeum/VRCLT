"""Qwen LiveTranslate realtime session (Alibaba DashScope) with auto-reconnect.

Protocol facts this code is built around (DashScope realtime WebSocket API,
qwen3.5-livetranslate-flash-realtime):
- No official Python SDK: raw WebSocket, Bearer DASHSCOPE_API_KEY header,
  model selected via the ?model= query parameter.
- The server runs its own VAD and owns turn boundaries; there is no client
  "commit"/"audio_stream_end" event. TURN_END_SILENCE_PAD_SEC appends zeroed
  PCM once per locally detected turn end so the server VAD sees the trailing
  silence the mic gate would otherwise swallow.
- Closing without a session.finish -> session.finished handshake can lose the
  final segment and leave the connection hanging, so the watchdog always
  finishes (with a timeout in case the server never answers).
- Whether transcript events carry incremental deltas or cumulative text is
  undocumented; _CumulativeTextAdapter handles both shapes.

Exposes the same surface as vrclt.gemini.session.LiveTranslateSession so the
pipelines and app controller stay provider-agnostic.
"""
import asyncio
import base64
import json
import logging
import time

import websockets

from ..languages import (QWEN_AUDIO_LANGUAGES, QWEN_TEXT_LANGUAGES,
                         canonical_language_code, qwen_language_code)
from ..session_base import (AudioSource, FatalSessionError,
                            RECONNECT_MIN_BACKOFF, RECONNECT_MAX_BACKOFF,
                            sleep_interruptible)

log = logging.getLogger(__name__)

# legacy shared domains: still fully supported, no workspace ID needed
ENDPOINTS = {
    "intl": "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime",
    "beijing": "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
}
# newer workspace-scoped domains Alibaba recommends (and the only form the
# qwen3.5-livetranslate docs show); used when a workspace ID is configured
WORKSPACE_ENDPOINTS = {
    "intl": "wss://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/realtime",
    "beijing": "wss://{workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime",
}


def endpoint_url(endpoint: str, workspace_id: str = "", base_url: str = "") -> str:
    if str(base_url or "").strip():
        return str(base_url).strip()
    endpoint = endpoint if endpoint in ENDPOINTS else "intl"
    workspace_id = str(workspace_id or "").strip()
    if workspace_id:
        return WORKSPACE_ENDPOINTS[endpoint].format(workspace_id=workspace_id)
    return ENDPOINTS[endpoint]
ASR_MODEL = "qwen3-asr-flash-realtime"   # enables source transcripts
MAX_GLOSSARY_PHRASES = 128
# zeroed PCM appended once per local turn end (seconds); 0 disables. Without
# it the server VAD may hold the tail of a translation until more audio comes.
TURN_END_SILENCE_PAD_SEC = 0.7
_INPUT_RATE = 16000  # 16 kHz mono int16, same as the AudioSource contract
# raw server events logged at DEBUG on each connect, to verify event shapes
_RAW_EVENT_LOG_COUNT = 30


class _ServerErrorEvent(Exception):
    """A {type: "error"} event received from the server."""


def _classify_qwen_error(text: str) -> str:
    """Short reason class for UI display: 'quota' | 'network'."""
    text = text.lower()
    if "429" in text or "throttl" in text or "quota" in text \
            or "rate limit" in text or "limit_requests" in text \
            or "resource_exhausted" in text or "allocation" in text:
        return "quota"
    return "network"


def _is_auth_error(exc: Exception) -> bool:
    status = getattr(getattr(exc, "response", None), "status_code", None) \
        or getattr(exc, "status_code", None)
    if status in (401, 403):
        return True
    text = str(exc).lower()
    return "invalidapikey" in text or "invalid api key" in text \
        or "unauthorized" in text or "access denied" in text \
        or "authentication" in text


def _parse_glossary(glossary: str) -> dict[str, str]:
    """'source=target' lines -> the corpus.phrases hotword mapping."""
    phrases: dict[str, str] = {}
    for line in str(glossary or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        src, dst = line.split("=", 1)
        src, dst = src.strip(), dst.strip()
        if src and dst:
            phrases[src] = dst
        if len(phrases) >= MAX_GLOSSARY_PHRASES:
            log.warning("glossary capped at %d phrases", MAX_GLOSSARY_PHRASES)
            break
    return phrases


def _event_text(event: dict) -> str:
    """Transcript payload field; the exact name is undocumented, try likely ones."""
    for key in ("text", "transcript", "delta"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


class _CumulativeTextAdapter:
    """Normalizes transcript events to incremental fragments (what the
    Segmenter expects) whether the server streams deltas or cumulative text."""

    def __init__(self):
        self._acc = ""

    def feed(self, text: str) -> str:
        if not text or text == self._acc:
            return ""
        if self._acc and text.startswith(self._acc):
            # cumulative stream: emit only the new suffix
            frag = text[len(self._acc):]
            self._acc = text
            return frag
        if self._acc and self._acc.startswith(text):
            # shrink/rewrite of already-delivered text: nothing new to emit
            return ""
        self._acc += text  # incremental stream
        return text

    def reset(self) -> None:
        self._acc = ""


class QwenLiveTranslateSession:
    def __init__(self, *, api_key: str, model: str, source: AudioSource, name: str,
                 get_target_language, get_source_language=lambda: "",
                 endpoint: str = "intl", workspace_id: str = "",
                 base_url: str = "", voice: str = "",
                 voice_clone: str = "always",
                 enabled=lambda: True,
                 send_interval_ms: int = 100, idle_disconnect_sec: float = 15.0,
                 turn_end_silence_sec: float = 0.55,
                 glossary: str = "",
                 on_src=None, on_dst=None, on_audio=None, on_turn_complete=None,
                 on_interrupted=None, on_session_state=None):
        self._api_key = api_key
        self._model = model
        self._get_target = get_target_language
        self._get_source = get_source_language
        self._endpoint = endpoint if endpoint in ENDPOINTS else "intl"
        self._workspace_id = workspace_id
        self._base_url = base_url
        # server-side speaker-voice cloning (the Qwen counterpart of Gemini's
        # voice replication): "always" | "once" | "off"
        voice_clone = str(voice_clone or "").strip().lower()
        if voice_clone not in ("always", "once", "off"):
            if voice_clone:
                log.warning("[%s] unknown voice_clone %r - cloning disabled",
                            name, voice_clone)
            voice_clone = "off"
        self._voice_clone = voice_clone
        # only used with cloning off: "" = model default voice. The literal
        # "default" is ONLY valid together with cloning and errors otherwise.
        voice = str(voice or "").strip()
        self._voice = "" if voice.lower() == "default" else voice
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
        self._on_interrupted = on_interrupted  # never fired: no barge-in event
        self._on_session_state = on_session_state
        self._phrases = _parse_glossary(glossary)
        self.connected = False
        # last-failure diagnostics for the status UIs (written on the session
        # asyncio thread; read lock-free from the Qt/VR threads)
        self.last_error = ""
        self.error_class = ""   # "" | "quota" | "network"
        self.next_retry_at = 0.0
        self._closing = False
        self._restart = False
        self._ready = asyncio.Event()
        self._finished = asyncio.Event()
        self._src_adapter = _CumulativeTextAdapter()
        self._dst_adapter = _CumulativeTextAdapter()
        self._src_display_lang = ""   # configured source shown as detected lang
        self._raw_log_left = 0
        # diagnostics (logged every 15s by the watchdog while connected)
        self._st_sent = 0
        self._st_sent_bytes = 0
        self._st_recv = 0
        self._st_src = 0
        self._st_dst = 0
        # per-turn text-vs-audio arrival gap (voice cloning happens between
        # the two; logged to judge voice_clone always/once/off latency cost)
        self._turn_text_at = 0.0
        self._turn_audio_logged = False

    def request_restart(self) -> None:
        """Apply changed settings (e.g. languages) by reconnecting."""
        self._restart = True

    def _session_config(self, target: str, src_lang: str, audio_out: bool) -> dict:
        session = {
            "modalities": ["text", "audio"] if audio_out else ["text"],
            "input_audio_format": "pcm",
            "translation": {"language": target},
            "input_audio_transcription": {"model": ASR_MODEL},
        }
        if audio_out:
            session["output_audio_format"] = "pcm"  # 24 kHz mono int16
            if self._voice_clone in ("always", "once"):
                # server clones the speaker's voice; "voice" MUST be the
                # literal "default" in this mode
                session["voice"] = "default"
                session["enable_voice_clone"] = True
                session["voice_clone_options"] = {"frequency": self._voice_clone}
            elif self._voice:
                # pre-cloned voice ID (qwen-translate-vc-...); frequency
                # "never" selects the stored profile
                session["voice"] = self._voice
                session["enable_voice_clone"] = True
                session["voice_clone_options"] = {"frequency": "never"}
            # else: omit "voice" entirely -> the model's stock default voice
        if self._phrases:
            session["translation"]["corpus"] = {"phrases": dict(self._phrases)}
        if src_lang:
            session["input_audio_transcription"]["language"] = src_lang
        return session

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
            except Exception as e:
                if _is_auth_error(e):
                    raise FatalSessionError(
                        "DashScope API key is invalid. Update the Qwen API key in Settings."
                    ) from e
                clean = False
                self.error_class = _classify_qwen_error(str(e))
                self.last_error = str(e)[:200]
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
        """One realtime session. Returns True if it ended cleanly."""
        target = qwen_language_code(self._get_target())
        src_cfg = canonical_language_code(self._get_source())
        src_lang = qwen_language_code(src_cfg)
        self._src_display_lang = src_cfg
        audio_out = bool(self._on_audio) and target in QWEN_AUDIO_LANGUAGES
        if self._on_audio and not audio_out:
            log.info("[%s] target %s has no Qwen audio output - text-only session",
                     self.name, target)
        if target not in QWEN_TEXT_LANGUAGES:
            log.warning("[%s] target %s is not a known Qwen language - sending anyway",
                        self.name, target)
        if not src_lang:
            log.warning("[%s] no source language configured - Qwen cannot "
                        "auto-detect and will assume English", self.name)
        url = endpoint_url(self._endpoint, self._workspace_id, self._base_url) \
            + f"?model={self._model}"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        log.info("[%s] connecting (model=%s target=%s source=%s endpoint=%s)",
                 self.name, self._model, target, src_lang or "(server default)",
                 self._endpoint)
        async with websockets.connect(url, additional_headers=headers) as ws:
            self._closing = False
            self._ready = asyncio.Event()
            self._finished = asyncio.Event()
            self._src_adapter.reset()
            self._dst_adapter.reset()
            self._raw_log_left = _RAW_EVENT_LOG_COUNT
            await ws.send(json.dumps({
                "type": "session.update",
                "session": self._session_config(target, src_lang, audio_out),
            }))
            self.connected = True
            # clear on successful connect (not on retry start) so the status
            # UI doesn't flicker between backoff sleeps and connect attempts
            self.last_error = ""
            self.error_class = ""
            self.next_retry_at = 0.0
            if self._on_session_state:
                self._on_session_state(True)
            log.info("[%s] session started (target=%s)", self.name, target)
            recv_t = asyncio.ensure_future(self._receiver(ws))
            send_t = asyncio.ensure_future(self._sender(ws))
            watch_t = asyncio.ensure_future(self._watchdog(ws, stop))
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
                    if isinstance(error, websockets.exceptions.ConnectionClosedOK):
                        log.info("[%s] connection closed cleanly", self.name)
                        return True
                    if self._closing:
                        return True
                    raise error
                return True  # receiver saw session.finished or watchdog closed
            finally:
                self.connected = False
                if self._on_session_state:
                    self._on_session_state(False)
                log.info("[%s] session ended", self.name)

    async def _receiver(self, ws) -> None:
        async for raw in ws:
            self._st_recv += 1
            if self._raw_log_left > 0 and log.isEnabledFor(logging.DEBUG):
                self._raw_log_left -= 1
                log.debug("[%s] raw event: %.500s", self.name, raw)
            try:
                event = json.loads(raw)
            except (TypeError, ValueError):
                log.debug("[%s] non-JSON frame ignored", self.name)
                continue
            etype = str(event.get("type") or "")
            if etype in ("session.created", "session.updated"):
                self._ready.set()
            elif etype == "conversation.item.input_audio_transcription.text":
                self._emit_src(self._src_adapter.feed(_event_text(event)))
            elif etype == "conversation.item.input_audio_transcription.completed":
                self._emit_src(self._src_adapter.feed(_event_text(event)))
                self._src_adapter.reset()
            elif etype == "response.audio_transcript.text":
                self._emit_dst(self._dst_adapter.feed(_event_text(event)))
            elif etype in ("response.audio_transcript.done", "response.text.done"):
                self._emit_dst(self._dst_adapter.feed(_event_text(event)))
                self._dst_adapter.reset()
            elif etype == "response.audio.delta":
                if self._on_audio:
                    for key in ("delta", "audio", "data"):
                        value = event.get(key)
                        if isinstance(value, str) and value:
                            try:
                                self._on_audio(base64.b64decode(value))
                            except (ValueError, TypeError):
                                log.debug("[%s] undecodable audio delta", self.name)
                                break
                            if not self._turn_audio_logged:
                                self._turn_audio_logged = True
                                if self._turn_text_at:
                                    log.info("[%s] first audio %.2fs after first "
                                             "text this turn", self.name,
                                             time.time() - self._turn_text_at)
                            break
            elif etype == "response.done":
                self._src_adapter.reset()
                self._dst_adapter.reset()
                self._turn_text_at = 0.0
                self._turn_audio_logged = False
                if self._on_turn_complete:
                    self._on_turn_complete()
            elif etype == "session.finished":
                self._finished.set()
                log.info("[%s] session.finished received", self.name)
                return
            elif etype == "error":
                # schema is undocumented; keep the whole payload for the UI
                raise _ServerErrorEvent(json.dumps(event, ensure_ascii=False)[:400])
            else:
                log.debug("[%s] unhandled event type %s", self.name, etype)

    def _emit_src(self, fragment: str) -> None:
        if fragment and self._on_src:
            self._st_src += 1
            self._on_src(fragment, self._src_display_lang or None)

    def _emit_dst(self, fragment: str) -> None:
        if fragment and self._on_dst:
            self._st_dst += 1
            if not self._turn_text_at:
                self._turn_text_at = time.time()
            self._on_dst(fragment)

    async def _append_audio(self, ws, pcm: bytes) -> None:
        await ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm).decode("ascii"),
        }))

    async def _sender(self, ws) -> None:
        # don't race audio ahead of the session.update acknowledgment
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("[%s] no session.created/updated within 5s - "
                        "sending audio anyway", self.name)
        speaking = False
        # the connect pre-roll must be flushed even when the handshake took
        # longer than turn_end_silence (active() already false) - otherwise a
        # short utterance that triggered this very connection is dropped
        flush_preroll = True
        while True:
            await asyncio.sleep(self._interval)
            if self._restart or not self._enabled():
                # keep idling: returning here would end the task race and get
                # the watchdog cancelled before it runs the finish handshake
                speaking = False
                continue
            chunks = self._source.drain()
            if chunks and (flush_preroll or self._source.active(self._turn_end_silence)):
                flush_preroll = False
                pcm = b"".join(chunks)
                sent = False
                try:
                    await self._append_audio(ws, pcm)
                    sent = True
                    self._st_sent += 1
                    self._st_sent_bytes += len(pcm)
                finally:
                    if not sent:
                        # connection died or task cancelled mid-send:
                        # requeue so the next session resends
                        self._source.requeue(chunks)
                speaking = True
            elif speaking and not self._source.active(self._turn_end_silence):
                # turn over after real silence. Chunks drained this tick are
                # sub-gate hangover bridge audio - drop them. There is no
                # client turn-end event; push the server VAD over its silence
                # threshold instead so it flushes the translation NOW.
                speaking = False
                if TURN_END_SILENCE_PAD_SEC > 0:
                    pad = b"\x00" * int(_INPUT_RATE * 2 * TURN_END_SILENCE_PAD_SEC)
                    try:
                        await self._append_audio(ws, pad)
                    except Exception:
                        return

    async def _finish_and_close(self, ws) -> None:
        """session.finish handshake; force-close if the server never answers."""
        self._closing = True
        try:
            await ws.send(json.dumps({"type": "session.finish"}))
            await asyncio.wait_for(self._finished.wait(), timeout=3.0)
        except Exception:
            log.debug("[%s] finish handshake incomplete - closing anyway", self.name)
        await ws.close()

    async def _watchdog(self, ws, stop: asyncio.Event) -> None:
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
                await self._finish_and_close(ws)
                return
            if not self._source.active(self._idle_disconnect):
                log.info("[%s] voice idle %.0fs - flushing and closing",
                         self.name, self._idle_disconnect)
                close_at = time.time() + 2.0  # let final transcripts arrive
                while time.time() < close_at:
                    await asyncio.sleep(0.1)
                    if stop.is_set() or self._restart or not self._enabled():
                        await self._finish_and_close(ws)
                        return
                    if self._source.active(self._idle_disconnect):
                        log.info("[%s] voice resumed during idle close - keeping session open",
                                 self.name)
                        break
                else:
                    await self._finish_and_close(ws)
                    return
