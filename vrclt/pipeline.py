"""Pipeline wiring: audio source -> Live session -> sinks (player/chatbox/log).

OutboundPipeline: my voice -> translated voice into VB-Cable + chatbox text.
  Translation toggle: when state.translation_on is False the Gemini session is
  closed (enabled gate) and raw mic audio is routed straight to the VB-Cable
  player instead (passthrough mode) - others hear the real voice.
  VRC text-only mode disables translated voice but keeps raw microphone
  passthrough while sending translated chatbox text.

InboundPipeline: VRChat's audio (process loopback) -> subtitles for me.
"""
import asyncio
import logging
import re
import time

from .audio.game_tap import GameAudioTap, find_pid
from .audio.mic_in import MicCapture, CAPTURE_RATE
from .audio.player import PcmPlayer
from . import config as config_mod
from . import i18n
from .gemini.session import LiveTranslateSession
from .qwen.session import QwenLiveTranslateSession
from .languages import language_label
from .out.osc_chatbox import Chatbox
from .state import AppState
from .subtitles import SubtitleStore

log = logging.getLogger(__name__)

# force a segment out once the translation grows past this size and ends in
# sentence punctuation (the chatbox caps at 144 chars - never truncate there)
FORCE_FINALIZE_CHARS = 120
HARD_FINALIZE_CHARS = 140
SENTENCE_END_CHARS = (".", "!", "?", "。", "！", "？", "…")
PASSTHROUGH_POLL_SEC = 0.008
PASSTHROUGH_PREBUFFER_MS = 0
PASSTHROUGH_SLICE_MS = 20
PASSTHROUGH_BLOCK_MS = 10
TTS_PREBUFFER_MS = 80

# the model sometimes emits control-token junk like "<cont>" / "{cont>" when
# it hears non-speech (background music/noise); strip those tag-like fragments
_JUNK_RE = re.compile(r"[<{][^<>{}]{0,20}[>}]?")
_TRAILING_CJK_APOSTROPHE_RE = re.compile(
    r"(?<=[\u1100-\u11FF\u3130-\u318F\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7AF])"
    r"['’‘`´](?=\s*$)"
)


def _clean(text: str) -> str:
    text = _JUNK_RE.sub("", text).strip()
    return _TRAILING_CJK_APOSTROPHE_RE.sub(".", text)


def _normalize_glossary(value) -> str:
    """Config may hold a string or a YAML list of 'source=target' lines."""
    if isinstance(value, (list, tuple)):
        return "\n".join(str(v).strip() for v in value if str(v).strip())
    return str(value or "")


class Segmenter:
    """Accumulates transcription fragments; finalizes on turnComplete, silence,
    or when the text outgrows the chatbox limit."""

    def __init__(self, finalize_silence_sec: float, on_final, on_partial=None,
                 partial_interval_sec: float = 0.3):
        self._silence = finalize_silence_sec
        self._partial_interval = max(0.05, float(partial_interval_sec))
        self._on_final = on_final
        self._on_partial = on_partial
        self._src = ""
        self._dst = ""
        self._lang = ""
        self._last_fragment = 0.0
        self._last_partial = 0.0

    def add_src(self, text: str, lang: str | None) -> None:
        self._src += text
        if lang:
            self._lang = lang
        self._fragment()

    def add_dst(self, text: str) -> None:
        self._dst += text
        self._fragment()

    def _fragment(self) -> None:
        self._last_fragment = time.time()
        src, dst = _clean(self._src), _clean(self._dst)
        if len(dst) > HARD_FINALIZE_CHARS or \
                (len(dst) > FORCE_FINALIZE_CHARS and dst.endswith(SENTENCE_END_CHARS)):
            self.flush()
            return
        if self._on_partial and (src or dst) and \
                (time.time() - self._last_partial) > self._partial_interval:
            self._last_partial = time.time()
            self._on_partial(src, dst)

    def turn_complete(self) -> None:
        self.flush()

    def tick(self) -> None:
        if (self._src or self._dst) and (time.time() - self._last_fragment) > self._silence:
            self.flush()

    def flush(self) -> None:
        src, dst, lang = _clean(self._src), _clean(self._dst), self._lang
        self._src = self._dst = ""
        if src or dst:
            self._on_final(src, dst, lang or "auto")


class _TranslationPipeline:
    """Shared pipeline skeleton: Segmenter + Live session wiring, state
    subscription, audio-sink fan-out, and the segment flush timer.
    Subclasses provide the audio source, gating lambdas, and text sinks."""

    # AppState fields whose change reconnects the session (languages are read
    # through the get_* callables again on every connect)
    LANGUAGE_FIELDS: tuple = ()

    def __init__(self, cfg: dict, api_key: str, state: AppState, *,
                 source, name: str, get_target_language, enabled,
                 echo_target_language: bool,
                 turn_end_silence_sec: float,
                 finalize_silence_sec: float,
                 get_source_language=lambda: "",
                 partial_interval_sec: float = 0.3,
                 audio_sinks: tuple = (),
                 glossary: str = ""):
        au = cfg["audio"]
        self.state = state
        self._audio_sinks = tuple(audio_sinks)
        self.segmenter = Segmenter(finalize_silence_sec, self._on_final,
                                   self._on_partial,
                                   partial_interval_sec=partial_interval_sec)
        common = dict(
            api_key=api_key,
            source=source,
            name=name,
            get_target_language=get_target_language,
            enabled=enabled,
            send_interval_ms=au["send_interval_ms"],
            idle_disconnect_sec=au["mic_idle_disconnect_sec"],
            turn_end_silence_sec=turn_end_silence_sec,
            glossary=glossary,
            on_src=self.segmenter.add_src,
            on_dst=self.segmenter.add_dst,
            on_audio=self._on_audio if self._audio_sinks else None,
            on_turn_complete=self.segmenter.turn_complete,
            on_interrupted=self._on_interrupted,
        )
        if config_mod.provider(cfg) == "qwen":
            qw = cfg.get("qwen", {})
            self.session = QwenLiveTranslateSession(
                model=qw.get("model", "qwen3.5-livetranslate-flash-realtime"),
                endpoint=qw.get("endpoint", "intl"),
                workspace_id=qw.get("workspace_id", ""),
                base_url=qw.get("base_url", ""),
                voice=qw.get("voice", ""),
                voice_clone=qw.get("voice_clone", "always"),
                get_source_language=get_source_language,
                **common,
            )
        else:
            self.session = LiveTranslateSession(
                model=cfg["model"],
                echo_target_language=echo_target_language,
                **common,
            )
        state.subscribe(self._on_state_change)

    def detach(self) -> None:
        """Stop reacting to state changes (the AppState outlives pipelines
        across runtime restarts)."""
        self.state.unsubscribe(self._on_state_change)

    def _on_state_change(self, field: str, value) -> None:
        if field in self.LANGUAGE_FIELDS:
            self.session.request_restart()

    def _on_audio(self, pcm: bytes) -> None:
        for sink in self._audio_sinks:
            sink.play(pcm)

    def _on_interrupted(self) -> None:
        for sink in self._audio_sinks:
            sink.interrupt()

    def _on_partial(self, src: str, dst: str) -> None:
        raise NotImplementedError

    def _on_final(self, src: str, dst: str, lang: str) -> None:
        raise NotImplementedError

    async def _segment_tick(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(0.2)
            self.segmenter.tick()


class OutboundPipeline(_TranslationPipeline):
    """My voice -> translated voice into VB-Cable + translated text into chatbox."""

    LANGUAGE_FIELDS = ("target_language", "source_language")

    def __init__(self, cfg: dict, api_key: str, state: AppState):
        ob = cfg["outbound"]
        au = cfg["audio"]
        self.voice_output = ob.get("voice_output", True)
        self.passthrough_while_translating = ob.get("passthrough_while_translating", False)
        self.mic = MicCapture(ob["mic_device"], au.get("voice_rms_threshold", 90.0),
                              hangover_sec=au.get("voice_hangover_sec", 2.5))
        # Voice mode: gate only while translating; passthrough sends raw audio
        # continuously while translation is off. VRC text-only keeps the gate
        # enabled for Gemini text translation and uses a raw tap for passthrough.
        self.mic.set_gate_enabled(
            lambda: state.translation_active
            if self.voice_output and not self.passthrough_while_translating else True)
        gain = max(0.0, min(2.0, float(ob.get("tts_gain", 1.0))))
        self.tts_player = PcmPlayer(ob["tts_device"], name="tts", rate=24000,
                                    prebuffer_ms=TTS_PREBUFFER_MS, gain=gain) \
            if self.voice_output else None
        # passthrough: raw 48k mic audio straight to the cable when translation is off
        self.passthrough = PcmPlayer(ob["tts_device"], name="passthrough", rate=CAPTURE_RATE,
                                     prebuffer_ms=PASSTHROUGH_PREBUFFER_MS,
                                     slice_ms=PASSTHROUGH_SLICE_MS,
                                     block_ms=PASSTHROUGH_BLOCK_MS) \
            if self.voice_output or self.passthrough_while_translating else None
        self._passthrough_tap = self.mic.add_raw_tap() if self.passthrough else None
        # passthrough (raw voice) intentionally stays at unity gain
        self.monitor = PcmPlayer(ob["monitor_device"], name="monitor", gain=gain) \
            if self.voice_output and ob["monitor_device"] else None
        self.chatbox = None
        self._feedback_chatbox = cfg.get("control", {}).get("feedback_chatbox", True)
        self._chat_show_source = cfg["osc"].get("show_source", True)
        self._last_chatbox_payload = ""
        if ob["chatbox"]:
            osc = cfg["osc"]
            self.chatbox = Chatbox(osc["ip"], osc["port"], osc["throttle_sec"],
                                   osc["notification_sfx"],
                                   chunk_display_sec=osc.get("chunk_display_sec", 4.0))

        self._last_active = state.translation_active
        super().__init__(
            cfg, api_key, state,
            source=self.mic,
            name="outbound",
            get_target_language=lambda: self.state.target_language,
            get_source_language=lambda: self.state.source_language,
            enabled=lambda: self.state.translation_active,
            echo_target_language=ob["echo_target_language"],
            turn_end_silence_sec=au.get("turn_end_silence_sec", 0.55),
            finalize_silence_sec=au["finalize_silence_sec"],
            audio_sinks=tuple(p for p in (self.tts_player, self.monitor) if p),
            glossary=_normalize_glossary(ob.get("glossary", "")),
        )

    # -- state changes (called from OSC control / UI threads) --
    def _on_state_change(self, field: str, value) -> None:
        super()._on_state_change(field, value)
        if field in ("translation_on", "hold_mute"):
            # the audio transition follows the EFFECTIVE state (toggle minus
            # hold-mute) so a held hotkey behaves exactly like toggling off
            active = self.state.translation_active
            if active != self._last_active:
                self._last_active = active
                self._apply_translation_transition(active)
        if self.chatbox and self._feedback_chatbox:
            if field == "translation_on":
                if value:
                    self.chatbox.send(self._feedback("osc_feedback_translation_on"))
                elif self.voice_output or self.passthrough_while_translating:
                    self.chatbox.send(self._feedback("osc_feedback_translation_off_voice"))
                else:
                    self.chatbox.send(self._feedback("osc_feedback_translation_off_text"))
            elif field == "target_language":
                self.chatbox.send(self._feedback(
                    "osc_feedback_language", language=language_label(str(value))))

    def _apply_translation_transition(self, active: bool) -> None:
        if active:
            # Leaving passthrough: keep only a small speech onset cushion for
            # Gemini and drop raw audio that may still be queued for VB-Cable.
            self.mic.trim_to(0.5)
            if self.passthrough:
                self.passthrough.interrupt()
        else:
            # Entering passthrough: stop stale translated audio immediately
            # and start from fresh mic frames rather than replaying the last
            # gated chunks that were meant for Gemini.
            self.mic.trim_to(0.0)
            if self._passthrough_tap is not None:
                self.mic.drain_tap(self._passthrough_tap)
            if self.tts_player:
                self.tts_player.interrupt()
            if self.monitor:
                self.monitor.interrupt()
            if self.passthrough:
                self.passthrough.interrupt()

    def _feedback(self, key: str, **values) -> str:
        text = i18n.tr(self.state.ui_lang, key)
        if values:
            try:
                text = text.format(**values)
            except Exception:
                pass
        return f"[vrclt] {text}"

    # -- session callbacks (worker event loop) --
    def _on_interrupted(self) -> None:
        super()._on_interrupted()
        self._last_chatbox_payload = ""

    def _chatbox_payload(self, src: str, dst: str, *, partial: bool = False) -> str:
        src, dst = _clean(src), _clean(dst)
        if partial and not dst:
            return ""
        if self._chat_show_source and src and dst:
            return f"{src}\n{dst}"
        return dst or src

    def _send_chatbox_text(self, src: str, dst: str, *, partial: bool = False) -> bool:
        if not self.chatbox:
            return False
        payload = self._chatbox_payload(src, dst, partial=partial)
        if not payload or payload == self._last_chatbox_payload:
            return False
        self._last_chatbox_payload = payload
        if self._chat_show_source and src and dst:
            self.chatbox.send_pair(src, dst)
        else:
            self.chatbox.send(dst or src)
        return True

    def _on_partial(self, src: str, dst: str) -> None:
        if self.chatbox:
            self.chatbox.typing(True)
            self._send_chatbox_text(src, dst, partial=True)

    def _on_final(self, src: str, dst: str, lang: str) -> None:
        log.info("FINAL [%s] %s  ->  %s", lang, src, dst)
        if self.chatbox:
            self.chatbox.typing(False)
            self._send_chatbox_text(src, dst)
            self._last_chatbox_payload = ""

    # -- main --
    async def run(self, stop: asyncio.Event) -> None:
        self.mic.start()
        if self.tts_player:
            self.tts_player.start()
        if self.passthrough:
            self.passthrough.start()
        if self.monitor:
            self.monitor.start()
        tick_task = asyncio.ensure_future(self._segment_tick(stop))
        route_task = asyncio.ensure_future(self._route_passthrough(stop)) \
            if self.passthrough else None
        try:
            await self.session.run(stop)
        finally:
            tick_task.cancel()
            if route_task:
                route_task.cancel()
            self.segmenter.flush()
            self.mic.stop()
            if self.tts_player:
                self.tts_player.stop()
            if self.passthrough:
                self.passthrough.stop()
            if self._passthrough_tap is not None:
                self.mic.remove_raw_tap(self._passthrough_tap)
            if self.monitor:
                self.monitor.stop()
            if self.chatbox:
                self.chatbox.stop()

    async def _route_passthrough(self, stop: asyncio.Event) -> None:
        """Route raw mic frames to the cable when passthrough should be audible."""
        if self._passthrough_tap is None:
            return
        while not stop.is_set():
            await asyncio.sleep(PASSTHROUGH_POLL_SEC)
            chunks = self.mic.drain_tap(self._passthrough_tap)
            if self.state.translation_active and not self.passthrough_while_translating:
                continue
            if chunks:
                self.passthrough.play(b"".join(chunks))


class InboundPipeline(_TranslationPipeline):
    """Others' voices (VRChat process audio) -> my-language subtitles."""

    LANGUAGE_FIELDS = ("inbound_language", "inbound_source_language")

    def __init__(self, cfg: dict, api_key: str, store: SubtitleStore, state: AppState):
        ib = cfg["inbound"]
        au = cfg["audio"]
        self.store = store
        self._process_name = ib["process"]
        self.tap = GameAudioTap(
            self._process_name,
            use_vad=ib.get("vad_enabled", True),
            vad_threshold=ib.get("vad_threshold", 0.5),
            vad_hangover_sec=ib.get("vad_hangover_sec", 0.35),
        )
        self._tap_running = False
        self.player = PcmPlayer(ib["audio_device"], name="inbound-audio") if ib["play_audio"] else None

        super().__init__(
            cfg, api_key, state,
            source=self.tap,
            name="inbound",
            get_target_language=lambda: self.state.inbound_language,
            get_source_language=lambda: self.state.inbound_source_language,
            enabled=lambda: self._tap_running and self.state.subtitles_on,
            echo_target_language=False,
            turn_end_silence_sec=au.get(
                "inbound_turn_end_silence_sec",
                au.get("turn_end_silence_sec", 0.55),
            ),
            finalize_silence_sec=au.get("subtitle_finalize_silence_sec",
                                        au["finalize_silence_sec"]),
            partial_interval_sec=au.get("subtitle_partial_interval_sec", 0.15),
            audio_sinks=(self.player,) if self.player else (),
        )

    def _on_partial(self, src: str, dst: str) -> None:
        self.store.set_partial(src, dst)

    def _on_final(self, src: str, dst: str, lang: str) -> None:
        log.info("INBOUND [%s] %s  ->  %s", lang, src, dst)
        self.store.add_final(src, dst, lang)

    async def run(self, stop: asyncio.Event) -> None:
        if self.player:
            self.player.start()
        tap_task = asyncio.ensure_future(self._tap_supervisor(stop))
        tick_task = asyncio.ensure_future(self._segment_tick(stop))
        try:
            await self.session.run(stop)
        finally:
            tap_task.cancel()
            tick_task.cancel()
            self.segmenter.flush()
            self.tap.stop()
            self._tap_running = False
            if self.player:
                self.player.stop()

    async def _tap_supervisor(self, stop: asyncio.Event) -> None:
        """Start/stop the process tap as the target app launches and exits.

        tap.start()/stop() and find_pid() are blocking (first tap.start may
        even download the Silero VAD model); run them in a thread so the
        outbound session sharing this event loop never stalls.
        """
        waiting_logged = False
        while not stop.is_set():
            await asyncio.sleep(3.0)
            pid = await asyncio.to_thread(find_pid, self._process_name)
            if pid is not None and (not self._tap_running or self.tap.pid != pid):
                if self._tap_running:
                    log.info(
                        "inbound: %s capture PID changed %s -> %s - restarting tap",
                        self._process_name,
                        self.tap.pid,
                        pid,
                    )
                    await asyncio.to_thread(self.tap.stop)
                    self._tap_running = False
                try:
                    await asyncio.to_thread(self.tap.start, pid)
                    self._tap_running = True
                    waiting_logged = False
                    log.info("inbound: capturing %s audio", self._process_name)
                except Exception as e:
                    if not waiting_logged:
                        waiting_logged = True
                        log.warning("inbound: tap start failed (%s) - will retry", e)
            elif pid is None and self._tap_running:
                log.info("inbound: %s exited - tap stopped", self._process_name)
                await asyncio.to_thread(self.tap.stop)
                self._tap_running = False
            elif pid is None and not waiting_logged:
                waiting_logged = True
                log.info("inbound: waiting for %s to start...", self._process_name)
