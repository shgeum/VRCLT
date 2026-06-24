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

from ..audio.game_tap import GameAudioTap, find_pid
from ..audio.mic_in import MicCapture, CAPTURE_RATE
from ..audio.player import PcmPlayer
from .. import i18n
from ..gemini.session import LiveTranslateSession
from ..languages import language_label
from ..out.osc_chatbox import Chatbox
from ..state import AppState
from ..subtitles import SubtitleStore

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


class Segmenter:
    """Accumulates transcription fragments; finalizes on turnComplete, silence,
    or when the text outgrows the chatbox limit."""

    def __init__(self, finalize_silence_sec: float, on_final, on_partial=None):
        self._silence = finalize_silence_sec
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
        if self._on_partial and (src or dst) and (time.time() - self._last_partial) > 0.3:
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


class OutboundPipeline:
    """My voice -> translated voice into VB-Cable + translated text into chatbox."""

    def __init__(self, cfg: dict, api_key: str, state: AppState):
        ob = cfg["outbound"]
        au = cfg["audio"]
        self.state = state
        self.voice_output = ob.get("voice_output", True)
        self.passthrough_while_translating = ob.get("passthrough_while_translating", False)
        self.mic = MicCapture(ob["mic_device"], au.get("voice_rms_threshold", 200.0),
                              hangover_sec=au.get("voice_hangover_sec", 0.5))
        # Voice mode: gate only while translating; passthrough sends raw audio
        # continuously while translation is off. VRC text-only keeps the gate
        # enabled for Gemini text translation and uses a raw tap for passthrough.
        self.mic.set_gate_enabled(
            lambda: state.translation_on
            if self.voice_output and not self.passthrough_while_translating else True)
        self.tts_player = PcmPlayer(ob["tts_device"], name="tts", rate=24000,
                                    prebuffer_ms=TTS_PREBUFFER_MS) \
            if self.voice_output else None
        # passthrough: raw 48k mic audio straight to the cable when translation is off
        self.passthrough = PcmPlayer(ob["tts_device"], name="passthrough", rate=CAPTURE_RATE,
                                     prebuffer_ms=PASSTHROUGH_PREBUFFER_MS,
                                     slice_ms=PASSTHROUGH_SLICE_MS,
                                     block_ms=PASSTHROUGH_BLOCK_MS) \
            if self.voice_output or self.passthrough_while_translating else None
        self._passthrough_tap = self.mic.add_raw_tap() if self.passthrough else None
        self.monitor = PcmPlayer(ob["monitor_device"], name="monitor") \
            if self.voice_output and ob["monitor_device"] else None
        self.chatbox = None
        self._feedback_chatbox = cfg.get("control", {}).get("feedback_chatbox", True)
        self._chat_show_source = cfg["osc"].get("show_source", True)
        if ob["chatbox"]:
            osc = cfg["osc"]
            self.chatbox = Chatbox(osc["ip"], osc["port"], osc["throttle_sec"],
                                   osc["notification_sfx"],
                                   chunk_display_sec=osc.get("chunk_display_sec", 4.0))

        self.segmenter = Segmenter(au["finalize_silence_sec"], self._on_final, self._on_partial)
        self.session = LiveTranslateSession(
            api_key=api_key,
            model=cfg["model"],
            source=self.mic,
            name="outbound",
            get_target_language=lambda: self.state.target_language,
            echo_target_language=ob["echo_target_language"],
            enabled=lambda: self.state.translation_on,
            send_interval_ms=au["send_interval_ms"],
            idle_disconnect_sec=au["mic_idle_disconnect_sec"],
            turn_end_silence_sec=au.get("turn_end_silence_sec", 0.55),
            on_src=self.segmenter.add_src,
            on_dst=self.segmenter.add_dst,
            on_audio=self._on_audio if self.voice_output else None,
            on_turn_complete=self.segmenter.turn_complete,
            on_interrupted=self._on_interrupted,
        )
        self.state.subscribe(self._on_state_change)

    # -- state changes (called from OSC control / UI threads) --
    def _on_state_change(self, field: str, value) -> None:
        if field == "target_language":
            self.session.request_restart()
        if field == "translation_on":
            if value:
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

    def _feedback(self, key: str, **values) -> str:
        text = i18n.tr(self.state.ui_lang, key)
        if values:
            try:
                text = text.format(**values)
            except Exception:
                pass
        return f"[vrclt] {text}"

    # -- session callbacks (worker event loop) --
    def _on_audio(self, pcm: bytes) -> None:
        if self.tts_player:
            self.tts_player.play(pcm)
        if self.monitor:
            self.monitor.play(pcm)

    def _on_interrupted(self) -> None:
        if self.tts_player:
            self.tts_player.interrupt()
        if self.monitor:
            self.monitor.interrupt()

    def _on_partial(self, src: str, dst: str) -> None:
        if self.chatbox:
            self.chatbox.typing(True)

    def _on_final(self, src: str, dst: str, lang: str) -> None:
        log.info("FINAL [%s] %s  ->  %s", lang, src, dst)
        if self.chatbox:
            self.chatbox.typing(False)
            if self._chat_show_source and src and dst:
                self.chatbox.send_pair(src, dst)  # source on top, translation below
            else:
                self.chatbox.send(dst or src)

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

    async def _segment_tick(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(0.2)
            self.segmenter.tick()

    async def _route_passthrough(self, stop: asyncio.Event) -> None:
        """Route raw mic frames to the cable when passthrough should be audible."""
        if self._passthrough_tap is None:
            return
        while not stop.is_set():
            await asyncio.sleep(PASSTHROUGH_POLL_SEC)
            chunks = self.mic.drain_tap(self._passthrough_tap)
            if self.state.translation_on and not self.passthrough_while_translating:
                continue
            if chunks:
                self.passthrough.play(b"".join(chunks))


class InboundPipeline:
    """Others' voices (VRChat process audio) -> my-language subtitles."""

    def __init__(self, cfg: dict, api_key: str, store: SubtitleStore, state: AppState):
        ib = cfg["inbound"]
        au = cfg["audio"]
        self.store = store
        self.state = state
        self._process_name = ib["process"]
        self.tap = GameAudioTap(
            self._process_name,
            use_vad=ib.get("vad_enabled", True),
            vad_threshold=ib.get("vad_threshold", 0.5),
            vad_hangover_sec=ib.get("vad_hangover_sec", 0.6),
        )
        self._tap_running = False
        self.player = PcmPlayer(ib["audio_device"], name="inbound-audio") if ib["play_audio"] else None

        self.segmenter = Segmenter(au["finalize_silence_sec"], self._on_final, self._on_partial)
        self.session = LiveTranslateSession(
            api_key=api_key,
            model=cfg["model"],
            source=self.tap,
            name="inbound",
            get_target_language=lambda: self.state.inbound_language,
            echo_target_language=False,
            enabled=lambda: self._tap_running and self.state.subtitles_on,
            send_interval_ms=au["send_interval_ms"],
            idle_disconnect_sec=au["mic_idle_disconnect_sec"],
            turn_end_silence_sec=au.get("turn_end_silence_sec", 0.55),
            on_src=self.segmenter.add_src,
            on_dst=self.segmenter.add_dst,
            on_audio=self._on_audio if self.player else None,
            on_turn_complete=self.segmenter.turn_complete,
            on_interrupted=self._on_interrupted,
        )
        state.subscribe(self._on_state_change)

    def _on_state_change(self, field: str, value) -> None:
        if field == "inbound_language":
            self.session.request_restart()

    def _on_audio(self, pcm: bytes) -> None:
        if self.player:
            self.player.play(pcm)

    def _on_interrupted(self) -> None:
        if self.player:
            self.player.interrupt()

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
        """Start/stop the process tap as VRChat launches and exits."""
        waiting_logged = False
        while not stop.is_set():
            await asyncio.sleep(3.0)
            pid = find_pid(self._process_name)
            if pid is not None and not self._tap_running:
                try:
                    self.tap.start()
                    self._tap_running = True
                    waiting_logged = False
                    log.info("inbound: capturing %s audio", self._process_name)
                except Exception as e:
                    if not waiting_logged:
                        waiting_logged = True
                        log.warning("inbound: tap start failed (%s) - will retry", e)
            elif pid is None and self._tap_running:
                log.info("inbound: %s exited - tap stopped", self._process_name)
                self.tap.stop()
                self._tap_running = False
            elif pid is None and not waiting_logged:
                waiting_logged = True
                log.info("inbound: waiting for %s to start...", self._process_name)

    async def _segment_tick(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(0.2)
            self.segmenter.tick()
