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
from .openai.session import OpenAIRealtimeTranslateSession
from .qwen.session import QwenLiveTranslateSession
from .soniox.session import SonioxLiveTranslateSession
from .languages import language_label
from .out.osc_chatbox import Chatbox, MAX_CHARS as CHATBOX_MAX_CHARS
from .state import AppState
from .subtitles import SubtitleStore

log = logging.getLogger(__name__)

# force a segment out once the translation grows past this size and ends in
# sentence punctuation (the chatbox caps at 144 chars - never truncate there)
FORCE_FINALIZE_CHARS = 120
HARD_FINALIZE_CHARS = 140
# sentence streaming (osc.stream_sentences): flush every completed sentence
# at least this long, so the chatbox updates as you speak instead of
# replaying a big segment in chunk_display_sec-paced parts afterwards
SENTENCE_STREAM_MIN_CHARS = 8
CHAT_TAIL_MAX_AGE_SEC = 15.0   # rolling-bubble sentences older than this drop
CHAT_TAIL_MAX_SEGMENTS = 6
TAP_STATS_INTERVAL_SEC = 15.0  # capture summary cadence, like the session stats
TAP_SILENCE_WARN_SEC = 60.0    # warn once after this long with no capture data
SENTENCE_END_CHARS = (".", "!", "?", "。", "！", "？", "…")
PASSTHROUGH_POLL_SEC = 0.008
# A zero-cushion bridge between two independently clocked devices is prone to
# periodic WASAPI underruns.  Forty milliseconds is short enough for live
# conversation but absorbs normal callback/event-loop jitter; PcmPlayer
# re-arms this cushion after a reported underrun or starvation.
PASSTHROUGH_PREBUFFER_MS = 40
PASSTHROUGH_SLICE_MS = 10
PASSTHROUGH_BLOCK_MS = 10
TTS_PREBUFFER_MS = 80
SPEAKER_PENDING_MAX_CHARS = 32 * 1024

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
                 partial_interval_sec: float = 0.3,
                 sentence_min_chars: int = 0,
                 max_combined_chars: int = 0):
        self._silence = finalize_silence_sec
        self._partial_interval = max(0.05, float(partial_interval_sec))
        # 0 disables; >0 finalizes every completed sentence of at least this
        # many chars (sentence streaming for the chatbox)
        self._sentence_min = int(sentence_min_chars)
        # 0 disables; >0 finalizes before src+dst outgrow one chatbox message
        self._max_combined = int(max_combined_chars)
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
        combined = len(src) + (1 if src and dst else 0) + len(dst)
        if self._max_combined and combined >= self._max_combined:
            self.flush()
            return
        if len(dst) > HARD_FINALIZE_CHARS or \
                (len(dst) > FORCE_FINALIZE_CHARS and dst.endswith(SENTENCE_END_CHARS)):
            self.flush()
            return
        if self._sentence_min and len(dst) >= self._sentence_min \
                and dst.endswith(SENTENCE_END_CHARS):
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


class _SpeakerTurn:
    def __init__(self, speaker_id):
        self.speaker_id = speaker_id
        self.segment = None
        self.finals = []
        self.has_translation = False
        self.closed = False


class SpeakerSegmenter:
    """Pair ordered speaker turns even when original text runs ahead of translation.

    S1/S2/S1 is three turns, not two speaker buckets. Translation speaker
    changes advance through the corresponding pending source turns, so both
    interleaved and source-first streams retain their conversational order.
    Unattributed tokens use one unknown-speaker lane; they never borrow text
    from a known speaker.
    """

    def __init__(self, finalize_silence_sec, on_final, on_partial=None, **options):
        self._silence = finalize_silence_sec
        self._on_final = on_final
        self._on_partial = on_partial
        self._options = options
        self._turns: list[_SpeakerTurn] = []
        self._source_turn = None
        self._target_turn = None

    def _new_turn(self, speaker_id):
        # A lost endpoint or malformed stream must not grow memory forever.
        if len(self._turns) >= 64:
            self._close(self._turns[0])
        turn = _SpeakerTurn(speaker_id)
        turn.segment = Segmenter(
            self._silence,
            lambda src, dst, lang: self._collect(turn, src, dst, lang),
            (lambda src, dst: self._on_partial(src, dst, speaker_id))
            if self._on_partial else None,
            **self._options,
        )
        self._turns.append(turn)
        return turn

    def _collect(self, turn, src, dst, lang):
        turn.finals.append((src, dst, lang))
        self._emit_ready()

    def _emit_ready(self):
        while self._turns:
            turn = self._turns[0]
            for src, dst, lang in turn.finals:
                self._on_final(src, dst, lang, turn.speaker_id)
            turn.finals.clear()
            if not turn.closed:
                break
            self._turns.pop(0)

    def _close(self, turn):
        turn.closed = True
        turn.segment.flush()
        self._emit_ready()

    def _pending_text_chars(self) -> int:
        return sum(
            len(turn.segment._src) + len(turn.segment._dst)
            + sum(len(src) + len(dst) for src, dst, _lang in turn.finals)
            for turn in self._turns
        )

    def _enforce_text_limit(self) -> None:
        # The turn count alone does not bound a never-ending source turn or
        # completed sentences waiting behind an untranslated earlier turn.
        # Publish the oldest turn(s), in order, rather than dropping text or
        # letting a lost endpoint accumulate an unlimited transcript.
        while self._turns and self._pending_text_chars() > SPEAKER_PENDING_MAX_CHARS:
            self._close(self._turns[0])

    def add_src(self, text: str, lang: str | None, speaker_id=None) -> None:
        turn = self._source_turn
        if turn is None or turn.closed or turn.speaker_id != speaker_id:
            turn = self._source_turn = self._new_turn(speaker_id)
        turn.segment.add_src(text, lang)
        self._enforce_text_limit()

    def add_dst(self, text: str, speaker_id=None) -> None:
        turn = self._target_turn
        if turn is None or turn.closed or turn.speaker_id != speaker_id:
            if turn is not None and not turn.closed:
                self._close(turn)
            turn = next((pending for pending in self._turns
                         if pending.speaker_id == speaker_id
                         and not pending.has_translation and not pending.closed), None)
            if turn is None:
                turn = self._new_turn(speaker_id)
            self._target_turn = turn
        turn.has_translation = True
        turn.segment.add_dst(text)
        self._enforce_text_limit()

    def turn_complete(self) -> None:
        self.flush()

    def tick(self) -> None:
        for turn in list(self._turns):
            # Keep source-only turns until the endpoint or the bounded queue
            # limit; slower translated tokens still need their original line.
            if turn.segment._dst:
                turn.segment.tick()

    def flush(self) -> None:
        for turn in list(self._turns):
            self._close(turn)
        self._source_turn = self._target_turn = None


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
                 glossary: str = "",
                 sentence_min_chars: int = 0,
                 max_combined_chars: int = 0):
        au = cfg["audio"]
        self.state = state
        self._audio_sinks = tuple(audio_sinks)
        segmenter_class = SpeakerSegmenter if config_mod.provider(cfg) == "soniox" else Segmenter
        self.segmenter = segmenter_class(finalize_silence_sec, self._on_final,
                                   self._on_partial,
                                   partial_interval_sec=partial_interval_sec,
                                   sentence_min_chars=sentence_min_chars,
                                   max_combined_chars=max_combined_chars)
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
        prov = config_mod.provider(cfg)
        if prov == "soniox":
            sx = cfg.get("soniox", {})
            # Preserve session-local speaker IDs through short pauses, but
            # close a long-idle session rather than billing silence forever.
            common["idle_disconnect_sec"] = config_mod.soniox_idle_disconnect_sec(cfg)
            self.session = SonioxLiveTranslateSession(
                model=sx.get("model", "stt-rt-v5"),
                tts_model=sx.get("tts_model", "tts-rt-v2"),
                voice=sx.get("voice", "Daniel"),
                get_source_language=get_source_language,
                speaker_metadata=True,
                **common,
            )
        elif prov == "openai":
            oa = cfg.get("openai", {})
            # source transcripts are billed separately and only one side
            # displays them by default: the chatbox prints the original above
            # the translation, inbound subtitles do not
            transcribe_key = ("inbound_transcribe_model" if name == "inbound"
                              else "transcribe_model")
            self.session = OpenAIRealtimeTranslateSession(
                model=oa.get("model", "gpt-realtime-translate"),
                transcribe_model=oa.get(
                    transcribe_key,
                    config_mod.DEFAULTS["openai"][transcribe_key]),
                noise_reduction=oa.get("noise_reduction", "near_field"),
                get_source_language=get_source_language,
                **common,
            )
        elif prov == "qwen":
            qw = cfg.get("qwen", {})
            self.session = QwenLiveTranslateSession(
                model=qw.get("model", "qwen3.5-livetranslate-flash-realtime"),
                endpoint=qw.get("endpoint", "intl"),
                workspace_id=qw.get("workspace_id", ""),
                base_url=qw.get("base_url", ""),
                voice=qw.get("voice", ""),
                voice_clone=qw.get("voice_clone", "once"),
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

    def _on_partial(self, src: str, dst: str, speaker_id=None) -> None:
        raise NotImplementedError

    def _on_final(self, src: str, dst: str, lang: str, speaker_id=None) -> None:
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
                                     block_ms=PASSTHROUGH_BLOCK_MS,
                                     match_device_rate=True,
                                     rebuffer_on_underflow=True,
                                     stats_interval_sec=15.0,
                                     max_buffer_ms=200) \
            if self.voice_output or self.passthrough_while_translating else None
        self._passthrough_tap = self.mic.add_raw_tap() if self.passthrough else None
        # passthrough (raw voice) intentionally stays at unity gain
        self.monitor = PcmPlayer(ob["monitor_device"], name="monitor", gain=gain) \
            if self.voice_output and ob["monitor_device"] else None
        self.chatbox = None
        self._feedback_chatbox = cfg.get("control", {}).get("feedback_chatbox", True)
        self._chat_show_source = cfg["osc"].get("show_source", True)
        # sentence streaming: finalize every completed sentence and roll the
        # recent ones through ONE chatbox bubble, instead of accumulating a
        # long segment that then replays in chunk_display_sec-paced parts
        self._stream_sentences = bool(cfg["osc"].get("stream_sentences", True))
        self._chat_tail: list[tuple[float, str, str]] = []  # (time, src, dst)
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
            sentence_min_chars=SENTENCE_STREAM_MIN_CHARS
            if self._stream_sentences else 0,
            max_combined_chars=(CHATBOX_MAX_CHARS - 6)
            if self._stream_sentences else 0,
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
        self._chat_tail.clear()  # don't resurrect pre-toggle sentences
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

    def _tail_render(self, cur_src: str, cur_dst: str) -> str:
        """Rolling bubble: recent finalized sentences + the live partial in
        one snapshot, oldest trimmed until it fits a single chatbox message
        (so nothing ever replays in delayed chunk parts)."""
        now = time.time()
        # Expire by CONVERSATION GAP, not by absolute age: an entry that is
        # merely old is still the context of a sentence still being spoken.
        # Dropping those made a running conversation lose its head mid-bubble,
        # which reads as the chatbox resetting itself. A real pause longer
        # than the window still clears the bubble.
        kept: list[tuple[float, str, str]] = []
        previous = None
        for entry in self._chat_tail:
            if previous is not None and (entry[0] - previous) > CHAT_TAIL_MAX_AGE_SEC:
                kept = []          # the talking stopped here; start a new bubble
            kept.append(entry)
            previous = entry[0]
        if kept and (now - kept[-1][0]) > CHAT_TAIL_MAX_AGE_SEC:
            kept = []              # nothing said recently: the bubble is stale
        self._chat_tail = kept[-CHAT_TAIL_MAX_SEGMENTS:]
        entries = list(self._chat_tail)
        if cur_src or cur_dst:
            entries.append((now, cur_src, cur_dst))
        while entries:
            srcs = " ".join(s for _, s, _ in entries if s).strip()
            dsts = " ".join(d for _, _, d in entries if d).strip()
            if self._chat_show_source and srcs and dsts:
                payload = f"{srcs}\n{dsts}"
            else:
                payload = dsts or srcs
            if len(payload) <= CHATBOX_MAX_CHARS or len(entries) == 1:
                return payload
            entries.pop(0)  # drop the oldest sentence until it fits
        return ""

    def _send_chatbox_text(self, src: str, dst: str, *, partial: bool = False) -> bool:
        if not self.chatbox:
            return False
        if self._stream_sentences:
            src, dst = _clean(src), _clean(dst)
            if partial and not dst:
                return False
            if not partial:
                if not (src or dst):
                    return False
                self._chat_tail.append((time.time(), src, dst))
                src = dst = ""
            payload = self._tail_render(src, dst)
            if not payload or payload == self._last_chatbox_payload:
                return False
            self._last_chatbox_payload = payload
            self.chatbox.send(payload)  # pre-fitted: always a single part
            return True
        payload = self._chatbox_payload(src, dst, partial=partial)
        if not payload or payload == self._last_chatbox_payload:
            return False
        self._last_chatbox_payload = payload
        if self._chat_show_source and src and dst:
            self.chatbox.send_pair(src, dst)
        else:
            self.chatbox.send(dst or src)
        return True

    def _on_partial(self, src: str, dst: str, speaker_id=None) -> None:
        if self.chatbox:
            self.chatbox.typing(True)
            self._send_chatbox_text(src, dst, partial=True)

    def _on_final(self, src: str, dst: str, lang: str, speaker_id=None) -> None:
        log.info("FINAL [%s] %s  ->  %s", lang, src, dst)
        if self.chatbox:
            self.chatbox.typing(False)
            self._send_chatbox_text(src, dst)
            self._last_chatbox_payload = ""

    # -- main --
    async def run(self, stop: asyncio.Event) -> None:
        tick_task = route_task = None

        def stop_resource(name, resource):
            if resource is not None:
                try:
                    resource.stop()
                except Exception:
                    log.exception("outbound: could not stop %s", name)

        try:
            # Startup is covered by the same cleanup as the running session:
            # a missing output device must not leave the mic/player alive.
            self.mic.start()
            if self.tts_player:
                self.tts_player.start()
            if self.passthrough:
                self.passthrough.start()
            if self.monitor:
                try:
                    self.monitor.start()
                except Exception as exc:
                    log.warning("outbound: optional monitor unavailable; "
                                "continuing primary output: %s", exc)
                    monitor = self.monitor
                    self.monitor = None
                    self._audio_sinks = tuple(
                        sink for sink in self._audio_sinks if sink is not monitor)
                    stop_resource("disabled monitor", monitor)
            tick_task = asyncio.ensure_future(self._segment_tick(stop))
            route_task = asyncio.ensure_future(self._route_passthrough(stop)) \
                if self.passthrough else None
            await self.session.run(stop)
        finally:
            for task in (tick_task, route_task):
                if task is not None:
                    task.cancel()
            # await the cancellations so the coroutine frames (and the
            # buffers they close over) are released now, not at some later
            # GC pass ("Task was destroyed but it is pending"). Swallow a
            # CancelledError delivered AT this await (forced-stop path) so
            # the device cleanup below still runs.
            try:
                await asyncio.gather(
                    *(t for t in (tick_task, route_task) if t is not None),
                    return_exceptions=True)
            except asyncio.CancelledError:
                pass
            try:
                self.segmenter.flush()
            finally:
                for name, resource in (("microphone", self.mic),
                                       ("translated voice", self.tts_player),
                                       ("passthrough", self.passthrough),
                                       ("monitor", self.monitor),
                                       ("chatbox", self.chatbox)):
                    stop_resource(name, resource)
                if self._passthrough_tap is not None:
                    self.mic.remove_raw_tap(self._passthrough_tap)
                    self._passthrough_tap = None

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
            allow_system_audio=ib.get("allow_system_audio", False),
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

    def _on_partial(self, src: str, dst: str, speaker_id=None) -> None:
        self.store.set_partial(src, dst, speaker_id=speaker_id)

    def _on_final(self, src: str, dst: str, lang: str, speaker_id=None) -> None:
        log.info("INBOUND [%s%s] %s  ->  %s", lang,
                 f" speaker={speaker_id}" if speaker_id is not None else "", src, dst)
        self.store.add_final(src, dst, lang, speaker_id=speaker_id)

    async def run(self, stop: asyncio.Event) -> None:
        tap_task = tick_task = None
        try:
            if self.player:
                self.player.start()
            tap_task = asyncio.ensure_future(self._tap_supervisor(stop))
            tick_task = asyncio.ensure_future(self._segment_tick(stop))
            await self.session.run(stop)
        finally:
            for task in (tap_task, tick_task):
                if task is not None:
                    task.cancel()
            try:
                await asyncio.gather(
                    *(t for t in (tap_task, tick_task) if t is not None),
                    return_exceptions=True)
            except asyncio.CancelledError:
                pass
            try:
                self.segmenter.flush()
            finally:
                self._tap_running = False
                for name, resource in (("capture", self.tap), ("audio", self.player)):
                    if resource is not None:
                        try:
                            resource.stop()
                        except Exception:
                            log.exception("inbound: could not stop %s", name)

    async def _tap_supervisor(self, stop: asyncio.Event) -> None:
        """Start/stop the process tap as the target app launches and exits.

        tap.start()/stop() and find_pid() are blocking (first tap.start may
        even download the Silero VAD model); run them in a thread so the
        outbound session sharing this event loop never stalls.
        """
        waiting_logged = False
        last_stats = time.time()
        while not stop.is_set():
            await asyncio.sleep(3.0)
            if self._tap_running:
                # ProcTap logs nothing of its own once running, so a capture
                # that dies quietly used to leave the log completely blank
                self.tap.check_capture(TAP_SILENCE_WARN_SEC)
                if (time.time() - last_stats) >= TAP_STATS_INTERVAL_SEC:
                    last_stats = time.time()
                    log.info("game tap stats(%ds): %s",
                             int(TAP_STATS_INTERVAL_SEC), self.tap.stats_line())
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
