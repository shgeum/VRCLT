"""OpenAI realtime translation session (gpt-realtime-translate) with auto-reconnect.

Protocol facts this code is built around (OpenAI realtime translations API):
- A dedicated endpoint, /v1/realtime/translations - NOT the general realtime
  conversation API, so the event names differ from the familiar ones: every
  client and server event is namespaced under "session." and there is no
  response lifecycle at all.
- One session translates into exactly ONE target language, chosen with
  session.audio.output.language and changed by reconnecting.
- Source language is never configured: the model auto-detects across 70+
  input languages. get_source_language is accepted for interface parity with
  the Qwen session and ignored, like Gemini ignores it.
- Source transcripts are opt-in: session.audio.input.transcription.model
  selects the ASR that produces session.input_transcript.delta. That slot is
  what gpt-realtime-whisper is for - it is not a standalone translator.
- Audio in is 24 kHz PCM16 mono, but the AudioSource contract is 16 kHz
  (Gemini's rate), so the sender resamples. Audio out is PCM16 at the rate
  the server reports, 24 kHz in practice - already the PcmPlayer default.
- Transcript deltas are append-only fragments, exactly what the Segmenter
  wants, so no cumulative-text adapter is needed here.
- There is no turn-complete event. Segment boundaries come from the
  pipeline's silence timer (finalize_silence_sec) instead.
- The docs ask for the silence between phrases to be streamed too. The
  capture gates strip it, so pauses are rebuilt with zeroed PCM the same way
  the Qwen session does it.
- Closing without a session.close -> session.closed handshake drops audio
  still in flight, so the watchdog always closes explicitly.

Exposes the same surface as vrclt.gemini.session.LiveTranslateSession so the
pipelines and app controller stay provider-agnostic.
"""
import asyncio
import base64
import json
import logging
import time

import numpy as np
import soxr
import websockets

from ..languages import OPENAI_OUTPUT_LANGUAGES, openai_language_code
from ..session_base import (AudioSource, FatalSessionError,
                            RECONNECT_MIN_BACKOFF, RECONNECT_MAX_BACKOFF,
                            sleep_interruptible)

log = logging.getLogger(__name__)

TRANSLATE_URL = "wss://api.openai.com/v1/realtime/translations"
TRANSLATE_MODEL = "gpt-realtime-translate"
# ASR for the source-language subtitles. Off by default: the transcription is
# billed on top of the translation, and the subtitle only needs the translated
# line. gpt-realtime-whisper is the model that goes here when it is wanted.
TRANSCRIBE_MODEL = ""
NOISE_REDUCTION = ("near_field", "far_field")

_SOURCE_RATE = 16000   # the AudioSource contract
_INPUT_RATE = 24000    # what the translations endpoint accepts
_OUTPUT_RATE = 24000   # what it returns (server restates it per delta)
# pause reconstruction: once the source has yielded nothing for GRACE seconds
# (a real pause, not drain jitter), stream zeroed PCM at the send cadence
# until the pause ends or MAX seconds are filled.
GAP_FILL_GRACE_SEC = 0.25
GAP_FILL_MAX_SEC = 2.5
# raw server events logged at DEBUG on each connect, to verify event shapes.
# Deliberately generous: the first events of a session are handshake noise, and
# the open question (does translated audio ever arrive?) is only answerable
# from events that land while someone is actually speaking.
_RAW_EVENT_LOG_COUNT = 150


class _ServerErrorEvent(Exception):
    """A {type: "error"} event received from the server."""


def _classify_openai_error(text: str) -> str:
    """Short reason class for UI display: 'quota' | 'network'."""
    text = text.lower()
    if "429" in text or "rate limit" in text or "rate_limit" in text \
            or "quota" in text or "insufficient_quota" in text \
            or "billing" in text or "throttl" in text:
        return "quota"
    return "network"


def _is_auth_error(exc: Exception) -> bool:
    status = getattr(getattr(exc, "response", None), "status_code", None) \
        or getattr(exc, "status_code", None)
    if status in (401, 403):
        return True
    text = str(exc).lower()
    return "invalid_api_key" in text or "invalid api key" in text \
        or "incorrect api key" in text or "unauthorized" in text \
        or "authentication" in text


class OpenAIRealtimeTranslateSession:
    def __init__(self, *, api_key: str, model: str, source: AudioSource, name: str,
                 get_target_language, get_source_language=lambda: "",
                 transcribe_model: str = TRANSCRIBE_MODEL,
                 noise_reduction: str = "near_field",
                 enabled=lambda: True,
                 send_interval_ms: int = 100, idle_disconnect_sec: float = 15.0,
                 turn_end_silence_sec: float = 0.55,
                 glossary: str = "",
                 on_src=None, on_dst=None, on_audio=None, on_turn_complete=None,
                 on_interrupted=None, on_session_state=None):
        self._api_key = api_key
        self._model = str(model or TRANSLATE_MODEL).strip() or TRANSLATE_MODEL
        self._get_target = get_target_language
        # accepted for interface parity: the model always auto-detects
        self._get_source = get_source_language
        self._transcribe_model = str(transcribe_model or "").strip()
        noise_reduction = str(noise_reduction or "").strip().lower()
        if noise_reduction not in NOISE_REDUCTION:
            if noise_reduction and noise_reduction != "off":
                log.warning("[%s] unknown noise_reduction %r - disabled",
                            name, noise_reduction)
            noise_reduction = ""
        self._noise_reduction = noise_reduction
        self._enabled = enabled
        self._source = source
        self.name = name
        self._interval = max(0.05, send_interval_ms / 1000.0)
        self._idle_disconnect = idle_disconnect_sec
        self._turn_end_silence = max(self._interval, float(turn_end_silence_sec))
        self._on_src = on_src
        self._on_dst = on_dst
        self._on_audio = on_audio
        self._on_turn_complete = on_turn_complete   # no such event; unused
        self._on_interrupted = on_interrupted       # no barge-in event either
        self._on_session_state = on_session_state
        if str(glossary or "").strip():
            # the translations endpoint takes no prompt, corpus or hotword
            # field (and no voice selection either - the voice is adapted from
            # the speaker), so a configured glossary cannot be honoured
            log.info("[%s] glossary ignored: gpt-realtime-translate takes no "
                     "prompting parameters", name)
        self.connected = False
        # last-failure diagnostics for the status UIs (written on the session
        # asyncio thread; read lock-free from the Qt/VR threads)
        self.last_error = ""
        self.error_class = ""   # "" | "quota" | "network"
        self.next_retry_at = 0.0
        self._closing = False
        self._restart = False
        self._ready = asyncio.Event()
        self._closed = asyncio.Event()
        self._rs = None          # 16 kHz source -> 24 kHz input resampler
        self._raw_log_left = 0
        self._out_rate_logged = 0
        # diagnostics (logged every 15s by the watchdog while connected)
        self._st_sent = 0
        self._st_sent_bytes = 0
        self._st_recv = 0
        self._st_src = 0
        self._st_dst = 0
        self._st_audio = 0                  # output audio deltas actually played
        self._st_unhandled: dict[str, int] = {}   # event types we do not consume

    def request_restart(self) -> None:
        """Apply changed settings (e.g. languages) by reconnecting."""
        self._restart = True

    def _session_config(self, target: str) -> dict:
        # Do NOT send "type" here: the server reports session.type back in
        # session.created but rejects it as an update parameter
        # ("Unknown parameter: 'session.type'"), which kills every session.
        # The settable surface really is just audio.input / audio.output.
        audio: dict = {"output": {"language": target}}
        source: dict = {}
        if self._transcribe_model:
            source["transcription"] = {"model": self._transcribe_model}
        if self._noise_reduction:
            source["noise_reduction"] = {"type": self._noise_reduction}
        if source:
            audio["input"] = source
        return {"audio": audio}

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
            except FatalSessionError:
                raise
            except Exception as e:
                if _is_auth_error(e):
                    raise FatalSessionError(
                        "OpenAI API key is invalid. Update the OpenAI API key in Settings."
                    ) from e
                clean = False
                self.error_class = _classify_openai_error(str(e))
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
        target = openai_language_code(self._get_target())
        if target not in OPENAI_OUTPUT_LANGUAGES:
            # connecting anyway would stream audio and get nothing back
            raise FatalSessionError(
                f"gpt-realtime-translate cannot translate into {target or 'this language'}. "
                f"Choose one of: {', '.join(sorted(OPENAI_OUTPUT_LANGUAGES))}."
            )
        url = f"{TRANSLATE_URL}?model={self._model}"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        log.info("[%s] connecting (model=%s target=%s transcription=%s)",
                 self.name, self._model, target,
                 self._transcribe_model or "(off)")
        async with websockets.connect(url, additional_headers=headers) as ws:
            self._closing = False
            self._ready = asyncio.Event()
            self._closed = asyncio.Event()
            self._rs = soxr.ResampleStream(_SOURCE_RATE, _INPUT_RATE, 1, dtype="int16")
            self._raw_log_left = _RAW_EVENT_LOG_COUNT
            self._out_rate_logged = 0
            await ws.send(json.dumps({
                "type": "session.update",
                "session": self._session_config(target),
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
                return True  # receiver saw session.closed or watchdog closed
            finally:
                self.connected = False
                self._rs = None
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
            elif etype == "session.input_transcript.delta":
                self._emit_src(str(event.get("delta") or ""))
            elif etype == "session.output_transcript.delta":
                self._emit_dst(str(event.get("delta") or ""))
            elif etype == "session.output_audio.delta":
                self._emit_audio(event)
            elif etype == "session.closed":
                self._closed.set()
                log.info("[%s] session.closed received", self.name)
                return
            elif etype == "error":
                # {"error": {"message", "type", "code", ...}}; keep the whole
                # payload for the UI, the shape varies by failure
                raise _ServerErrorEvent(
                    json.dumps(event.get("error") or event, ensure_ascii=False)[:400])
            else:
                # counted, not just DEBUG-logged: a renamed or unexpected event
                # is exactly how translated text/audio goes missing while the
                # session otherwise looks healthy
                self._st_unhandled[etype] = self._st_unhandled.get(etype, 0) + 1
                log.debug("[%s] unhandled event type %s", self.name, etype)

    def _emit_src(self, fragment: str) -> None:
        if fragment and self._on_src:
            self._st_src += 1
            # the model auto-detects and does not report which language it
            # heard, so the subtitle carries no detected-language tag
            self._on_src(fragment, None)

    def _emit_dst(self, fragment: str) -> None:
        if fragment and self._on_dst:
            self._st_dst += 1
            self._on_dst(fragment)

    def _emit_audio(self, event: dict) -> None:
        if not self._on_audio:
            return
        delta = event.get("delta")
        if not isinstance(delta, str) or not delta:
            return
        rate = int(event.get("sample_rate") or _OUTPUT_RATE)
        if rate != _OUTPUT_RATE and self._out_rate_logged < 1:
            # the players are built for 24 kHz; anything else would play at
            # the wrong speed, so say so instead of silently detuning
            self._out_rate_logged += 1
            log.warning("[%s] server audio is %d Hz, players expect %d Hz",
                        self.name, rate, _OUTPUT_RATE)
        try:
            pcm = base64.b64decode(delta)
        except (ValueError, TypeError):
            log.debug("[%s] undecodable audio delta", self.name)
            return
        self._st_audio += 1
        self._on_audio(pcm)

    def _to_input_rate(self, pcm: bytes) -> bytes:
        """16 kHz source PCM -> the 24 kHz the endpoint accepts."""
        rs = self._rs
        if rs is None:
            return b""
        samples = np.frombuffer(pcm, dtype=np.int16)
        if not samples.size:
            return b""
        return rs.resample_chunk(samples).tobytes()

    async def _append_audio(self, ws, pcm: bytes) -> None:
        if not pcm:
            return
        await ws.send(json.dumps({
            "type": "session.input_audio_buffer.append",
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
        last_audio = 0.0   # when real audio last went out
        gap_filled = 0.0   # zeroed seconds streamed into the current pause
        fill_chunk = b"\x00" * (int(_INPUT_RATE * self._interval) * 2)
        # the connect pre-roll must be flushed even when the handshake took
        # longer than turn_end_silence (active() already false) - otherwise a
        # short utterance that triggered this very connection is dropped
        flush_preroll = True
        while True:
            await asyncio.sleep(self._interval)
            if self._restart or not self._enabled():
                # keep idling: returning here would end the task race and get
                # the watchdog cancelled before it runs the close handshake
                speaking = False
                continue
            chunks = self._source.drain()
            if chunks and (flush_preroll or self._source.active(self._turn_end_silence)):
                flush_preroll = False
                sent = False
                try:
                    pcm = self._to_input_rate(b"".join(chunks))
                    await self._append_audio(ws, pcm)
                    sent = True
                    self._st_sent += 1
                    self._st_sent_bytes += len(pcm)
                finally:
                    if not sent:
                        # connection died or task cancelled mid-send: requeue
                        # so the next session resends. The resampler is
                        # rebuilt per session, so its consumed state goes too.
                        self._source.requeue(chunks)
                speaking = True
                last_audio = time.time()
                gap_filled = 0.0
            elif speaking:
                # The source went quiet mid-turn (chunks drained on these
                # ticks are sub-gate hangover bridge audio - dropped). The
                # gates stripped the pause the server segmentation needs, so
                # rebuild it with zeroed PCM at the send cadence.
                if (time.time() - last_audio) < GAP_FILL_GRACE_SEC:
                    continue  # drain jitter, not a real pause yet
                if gap_filled >= GAP_FILL_MAX_SEC:
                    speaking = False  # pause fully padded; go quiet until voice
                    continue
                try:
                    await self._append_audio(ws, fill_chunk)
                except Exception:
                    return
                gap_filled += self._interval

    async def _close_session(self, ws) -> None:
        """session.close handshake; force-close if the server never answers."""
        self._closing = True
        try:
            await ws.send(json.dumps({"type": "session.close"}))
            await asyncio.wait_for(self._closed.wait(), timeout=3.0)
        except Exception:
            log.debug("[%s] close handshake incomplete - closing anyway", self.name)
        await ws.close()

    async def _watchdog(self, ws, stop: asyncio.Event) -> None:
        last_stats = time.time()
        while True:
            await asyncio.sleep(0.2)
            if (time.time() - last_stats) >= 15.0:
                last_stats = time.time()
                qlen = len(getattr(self._source, "buffer", ()))
                other = ", ".join(f"{k}x{v}" for k, v in
                                  sorted(self._st_unhandled.items())) or "-"
                log.info("[%s] stats(15s): sent=%d msg/%.0fKB recv=%d fr "
                         "src+%d dst+%d audio+%d queue=%d other=[%s]",
                         self.name, self._st_sent, self._st_sent_bytes / 1024,
                         self._st_recv, self._st_src, self._st_dst,
                         self._st_audio, qlen, other)
                self._st_sent = self._st_sent_bytes = 0
                self._st_recv = self._st_src = self._st_dst = self._st_audio = 0
                self._st_unhandled = {}
            if stop.is_set() or self._restart or not self._enabled():
                await self._close_session(ws)
                return
            if not self._source.active(self._idle_disconnect):
                log.info("[%s] voice idle %.0fs - flushing and closing",
                         self.name, self._idle_disconnect)
                close_at = time.time() + 2.0  # let final transcripts arrive
                while time.time() < close_at:
                    await asyncio.sleep(0.1)
                    if stop.is_set() or self._restart or not self._enabled():
                        await self._close_session(ws)
                        return
                    if self._source.active(self._idle_disconnect):
                        log.info("[%s] voice resumed during idle close - keeping session open",
                                 self.name)
                        break
                else:
                    await self._close_session(ws)
                    return
