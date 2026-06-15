"""Pipeline wiring: audio source -> Live session -> sinks (player/chatbox/log).

OutboundPipeline: my voice -> translated voice into VB-Cable + chatbox text.
  Translation toggle: when state.translation_on is False the Gemini session is
  closed (enabled gate) and raw mic audio is routed straight to the VB-Cable
  player instead (passthrough mode) - others hear the real voice.

InboundPipeline: VRChat's audio (process loopback) -> subtitles for me.
"""
import asyncio
import logging
import re
import time

from ..audio.game_tap import GameAudioTap, find_pid
from ..audio.mic_in import MicCapture, RATE as MIC_RATE
from ..audio.player import PcmPlayer
from ..gemini.session import LiveTranslateSession
from ..out.osc_chatbox import Chatbox
from ..state import AppState
from ..subtitles import SubtitleStore

log = logging.getLogger(__name__)

# force a segment out once the translation grows past this size and ends in
# sentence punctuation (the chatbox caps at 144 chars - never truncate there)
FORCE_FINALIZE_CHARS = 120
HARD_FINALIZE_CHARS = 140
SENTENCE_END_CHARS = (".", "!", "?", "。", "！", "？", "…")

# the model sometimes emits control-token junk like "<cont>" / "{cont>" when
# it hears non-speech (background music/noise); strip those tag-like fragments
_JUNK_RE = re.compile(r"[<{][^<>{}]{0,20}[>}]?")


def _clean(text: str) -> str:
    return _JUNK_RE.sub("", text).strip()


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
        self.mic = MicCapture(ob["mic_device"], au.get("voice_rms_threshold", 200.0),
                              hangover_sec=au.get("voice_hangover_sec", 0.5))
        # gate only while translating; passthrough sends raw audio continuously
        self.mic.set_gate_enabled(lambda: state.translation_on)
        self.tts_player = PcmPlayer(ob["tts_device"], name="tts", rate=24000)
        # passthrough: raw 16k mic audio straight to the cable when translation is off
        self.passthrough = PcmPlayer(ob["tts_device"], name="passthrough", rate=MIC_RATE)
        self.monitor = PcmPlayer(ob["monitor_device"], name="monitor") if ob["monitor_device"] else None
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
            on_src=self.segmenter.add_src,
            on_dst=self.segmenter.add_dst,
            on_audio=self._on_audio,
            on_turn_complete=self.segmenter.turn_complete,
            on_interrupted=self._on_interrupted,
        )
        self.state.subscribe(self._on_state_change)

    # -- state changes (called from OSC control / UI threads) --
    def _on_state_change(self, field: str, value) -> None:
        if field == "target_language":
            self.session.request_restart()
        if field == "translation_on":
            # leaving passthrough: drop the audio buffered while off
            self.mic.trim_to(0.5)
        if self.chatbox and self._feedback_chatbox:
            if field == "translation_on":
                self.chatbox.send("[vrclt] 번역 ON" if value else "[vrclt] 번역 OFF (원음 송출)")
            elif field == "target_language":
                self.chatbox.send(f"[vrclt] 번역 언어: {value}")

    # -- session callbacks (worker event loop) --
    def _on_audio(self, pcm: bytes) -> None:
        self.tts_player.play(pcm)
        if self.monitor:
            self.monitor.play(pcm)

    def _on_interrupted(self) -> None:
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
        self.tts_player.start()
        self.passthrough.start()
        if self.monitor:
            self.monitor.start()
        tick_task = asyncio.ensure_future(self._segment_tick(stop))
        route_task = asyncio.ensure_future(self._route_passthrough(stop))
        try:
            await self.session.run(stop)
        finally:
            tick_task.cancel()
            route_task.cancel()
            self.segmenter.flush()
            self.mic.stop()
            self.tts_player.stop()
            self.passthrough.stop()
            if self.monitor:
                self.monitor.stop()
            if self.chatbox:
                self.chatbox.stop()

    async def _segment_tick(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(0.2)
            self.segmenter.tick()

    async def _route_passthrough(self, stop: asyncio.Event) -> None:
        """While translation is OFF, drain the mic straight to the cable."""
        was_off = False
        while not stop.is_set():
            await asyncio.sleep(0.1)
            if self.state.translation_on:
                was_off = False
                continue
            if not was_off:
                was_off = True
                self.mic.trim_to(0.2)  # don't replay buffered audio on mode switch
            chunks = self.mic.drain()
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
