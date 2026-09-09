"""Soniox protocol regression tests using local STT and TTS WebSocket servers.

No credentials, paid requests, audio devices or Soniox SDK are required.
Run with .venv/Scripts/python tests/smoke_soniox_session.py.
"""
import asyncio
import base64
import copy
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

import websockets

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vrclt import config
from vrclt.languages import SONIOX_LANGUAGES, soniox_language_code
from vrclt.session_base import FatalSessionError
from vrclt.soniox import session as sx
from vrclt.soniox import tts
from vrclt.pipeline import InboundPipeline, SpeakerSegmenter, SPEAKER_PENDING_MAX_CHARS
from vrclt.state import AppState
from vrclt.subtitles import SubtitleLine, SubtitleStore


class FakeSource:
    def __init__(self):
        self.buffer = [b"\x01\x02" * 800]
        self.requeued = []
        self.trimmed = []
        self.is_active = True

    def drain(self):
        result, self.buffer = self.buffer, []
        return result

    def requeue(self, chunks):
        self.requeued.extend(chunks)

    def trim_to(self, seconds):
        self.trimmed.append(seconds)

    def active(self, timeout=2.0):
        return self.is_active


def make_session(**overrides):
    kwargs = dict(api_key="test-soniox-key", model="stt-rt-v5", source=FakeSource(),
                  name="test", get_target_language=lambda: "en",
                  send_interval_ms=50, idle_disconnect_sec=30)
    kwargs.update(overrides)
    return sx.SonioxLiveTranslateSession(**kwargs)


def token(text, *, final=True, status="translation", language="en", speaker=None):
    result = dict(text=text, is_final=final, translation_status=status, language=language)
    if speaker is not None:
        result["speaker"] = speaker
    return result


class SonioxConfigTests(unittest.TestCase):
    def test_provider_env_and_reset(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        cfg["provider"] = "soniox"
        with patch.dict("os.environ", {"SONIOX_API_KEY": "env-only-test"}):
            self.assertEqual(config.api_key_for(cfg, config.provider(cfg)), "env-only-test")
            cfg["soniox"]["api_key"] = "saved-test"
            self.assertEqual(config.api_key_for(cfg, "soniox"), "saved-test")
        reset = config.reset_preserving_language_lists(cfg)
        self.assertEqual(reset["provider"], "soniox")
        self.assertEqual(reset["soniox"]["api_key"], "saved-test")
        self.assertEqual(reset["soniox"]["tts_model"], "tts-rt-v2")

    def test_languages_and_config(self):
        self.assertEqual(len(SONIOX_LANGUAGES), 60)
        for original, mapped in (("zh-Hant", "zh"), ("pt-BR", "pt"),
                                 ("fil", "tl"), ("nb", "no")):
            self.assertEqual(soniox_language_code(original), mapped)
        session = make_session(get_source_language=lambda: "ko",
                               glossary="VRChat=브이알챗\ninvalid\n =bad\n X= Y ")
        cfg = session._session_config("en")
        self.assertEqual(cfg["translation"], {"type": "one_way", "target_language": "en"})
        self.assertEqual(cfg["language_hints"], ["ko"])
        self.assertTrue(cfg["enable_speaker_diarization"])
        self.assertEqual(cfg["max_endpoint_delay_ms"], 3000)
        self.assertEqual(cfg["endpoint_sensitivity"], -0.3)
        self.assertGreater(sx.GAP_FILL_MAX_SEC, cfg["max_endpoint_delay_ms"] / 1000)
        self.assertNotIn("endpoint_sensitivity", make_session(model="stt-rt-v4")._session_config("en"))
        self.assertEqual(cfg["context"]["translation_terms"], [
            {"source": "VRChat", "target": "브이알챗"}, {"source": "X", "target": "Y"}])
        self.assertNotIn("language_hints", make_session()._session_config("en"))
        with self.assertRaises(FatalSessionError):
            session._session_config("yue")
        with self.assertRaises(FatalSessionError):
            make_session(get_source_language=lambda: "yue")._session_config("en")

    def test_revisions_are_not_duplicated_or_spoken(self):
        source, target, turns = [], [], []
        session = make_session(on_src=lambda text, lang: source.append((text, lang)),
                               on_dst=target.append, on_turn_complete=lambda: turns.append(True))
        session._consume_tokens([token("bad guess", final=False)])
        session._consume_tokens([token("revised guess", final=False)])
        session._consume_tokens([token("안녕", status="original", language="ko"),
                                 token("Hello"), token(" world", final=False)])
        session._consume_tokens([token(" there!"), token("<end>")])
        session._consume_tokens([token("<fin>"), token("<noise>")])
        self.assertEqual(source, [("안녕", "ko")])
        self.assertEqual("".join(target), "Hello there!")
        self.assertEqual(len(turns), 1)

    def test_error_classification_and_redaction(self):
        session = make_session()
        for code in (400, 401, 403):
            with self.assertRaises(FatalSessionError) as cm:
                session._check_error({"error_code": code,
                                      "error_message": "invalid test-soniox-key"})
            self.assertNotIn("test-soniox-key", str(cm.exception))
        with self.assertRaises(sx._ServerError) as cm:
            session._check_error({"error_code": 402, "error_type": "organization_balance_exhausted",
                                  "error_message": "balance"})
        self.assertEqual(cm.exception.code, 402)

    def test_interleaved_speakers_keep_original_and_translation_paired(self):
        finals = []
        segmenter = SpeakerSegmenter(0.8, lambda src, dst, lang, speaker: finals.append(
            (src, dst, lang, speaker)))
        session = make_session(on_src=segmenter.add_src, on_dst=segmenter.add_dst,
                               on_turn_complete=segmenter.turn_complete, speaker_metadata=True)
        session._consume_tokens([
            token("changed speaker guess", status="original", speaker="9", final=False),
            token("첫 번째", status="original", language="ko", speaker="1"),
            token("두 번째", status="original", language="ko", speaker="2"),
            token("First", speaker="1"), token("Second", speaker="2"), token("<end>"),
        ])
        self.assertEqual(finals, [("첫 번째", "First", "ko", "1"),
                                 ("두 번째", "Second", "ko", "2")])

    def test_repeated_speaker_turns_keep_chronological_order(self):
        for source_first in (True, False):
            with self.subTest(source_first=source_first):
                finals = []
                segmenter = SpeakerSegmenter(
                    0.8, lambda src, dst, lang, speaker: finals.append((src, dst, speaker)))
                session = make_session(on_src=segmenter.add_src, on_dst=segmenter.add_dst,
                    on_turn_complete=segmenter.turn_complete, speaker_metadata=True)
                pairs = [("First question.", "첫 질문.", "1"),
                         ("Answer.", "답변.", "2"),
                         ("Follow-up.", "후속 질문.", "1")]
                originals = [token(src, status="original", speaker=speaker)
                             for src, dst, speaker in pairs]
                translations = [token(dst, speaker=speaker) for src, dst, speaker in pairs]
                if source_first:
                    session._consume_tokens(originals)
                    # Simulate translation lag exceeding the normal subtitle
                    # silence timer. Source turns must remain paired.
                    with patch("vrclt.pipeline.time.time", return_value=10**12):
                        segmenter.tick()
                    self.assertEqual(finals, [])
                    session._consume_tokens(translations)
                else:
                    for original, translated in zip(originals, translations):
                        session._consume_tokens([original, translated])
                session._consume_tokens([token("<end>")])
                self.assertEqual(finals, pairs)

    def test_translation_arrival_order_does_not_reorder_source_turns(self):
        finals = []
        segmenter = SpeakerSegmenter(0.8, lambda src, dst, lang, speaker: finals.append(
            (src, dst, speaker)))
        segmenter.add_src("first", "en", "1")
        segmenter.add_src("second", "en", "2")
        segmenter.add_dst("두 번째", "2")
        segmenter.add_dst("첫 번째", "1")
        segmenter.turn_complete()
        self.assertEqual(finals, [("first", "첫 번째", "1"), ("second", "두 번째", "2")])

    def test_source_only_without_endpoint_has_bounded_pending_text(self):
        finals = []
        segmenter = SpeakerSegmenter(0.8, lambda src, dst, lang, speaker: finals.append(
            (src, dst, speaker)))
        source = "a" * 4096
        for _ in range(10):
            segmenter.add_src(source, "en", "1")
            self.assertLessEqual(segmenter._pending_text_chars(), SPEAKER_PENDING_MAX_CHARS)
        self.assertTrue(finals, "source-only turns never drain without an endpoint")
        segmenter.turn_complete()
        self.assertEqual("".join(src for src, dst, speaker in finals), source * 10)
        self.assertTrue(all(dst == "" and speaker == "1" for src, dst, speaker in finals))
        self.assertEqual(segmenter._pending_text_chars(), 0)

    def test_blocked_sentence_finals_are_bounded_and_drain_in_source_order(self):
        finals = []
        segmenter = SpeakerSegmenter(0.8, lambda src, dst, lang, speaker: finals.append(
            (src, dst, speaker)), sentence_min_chars=1)
        segmenter.add_src("waiting for translation", "en", "1")
        segmenter.add_src("second speaker", "en", "2")
        translated_sentence = "b" * 100 + "."
        for _ in range(400):
            segmenter.add_dst(translated_sentence, "2")
            self.assertLessEqual(segmenter._pending_text_chars(), SPEAKER_PENDING_MAX_CHARS)
        self.assertGreater(len(finals), 1, "blocked completed sentences never drain")
        segmenter.turn_complete()
        self.assertEqual(finals[0], ("waiting for translation", "", "1"))
        self.assertTrue(all(speaker == "2" for src, dst, speaker in finals[1:]))
        self.assertEqual("".join(src for src, dst, speaker in finals[1:]), "second speaker")
        self.assertEqual("".join(dst for src, dst, speaker in finals[1:]), translated_sentence * 400)
        self.assertEqual(segmenter._pending_text_chars(), 0)

    def test_ambiguous_translation_stays_unknown_and_endpoint_resets_attribution(self):
        dst = []
        session = make_session(speaker_metadata=True,
                               on_dst=lambda text, speaker: dst.append((text, speaker)))
        session._consume_tokens([token("one", status="original", speaker="1"),
                                 token("two", status="original", speaker="2"),
                                 token("unassigned"), token("<end>"), token("next turn"),
                                 token("single", status="original", speaker="3"),
                                 token("unambiguous")])
        self.assertEqual(dst, [("unassigned", None), ("next turn", None),
                               ("unambiguous", "3")])

    def test_inbound_pipeline_preserves_speakers_through_subtitle_store(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        cfg["provider"] = "soniox"
        state, store = AppState(), SubtitleStore()
        with patch("vrclt.pipeline.GameAudioTap", return_value=FakeSource()):
            pipeline = InboundPipeline(cfg, "test-soniox-key", store, state)
        try:
            self.assertIsInstance(pipeline.session, sx.SonioxLiveTranslateSession)
            self.assertIsNone(pipeline.session._on_audio)
            self.assertEqual(pipeline.session._idle_disconnect, 60)
            pipeline.session._consume_tokens([
                token("hello", status="original", speaker="1"),
                token("goodbye", status="original", speaker="2"),
                token("안녕하세요", speaker="1"), token("잘 가요", speaker="2"), token("<end>"),
            ])
            finals, partial = store.snapshot_with_speakers()
            self.assertEqual(finals, [SubtitleLine("hello", "안녕하세요", "en", "1"),
                                      SubtitleLine("goodbye", "잘 가요", "en", "2")])
            self.assertEqual(partial, SubtitleLine())
            state.inbound_language = "ja"
            self.assertTrue(pipeline.session._restart)
        finally:
            pipeline.detach()
        cfg["soniox"]["keep_speaker_context"] = False
        with patch("vrclt.pipeline.GameAudioTap", return_value=FakeSource()):
            pipeline = InboundPipeline(cfg, "test-soniox-key", store, state)
        try:
            self.assertEqual(pipeline.session._idle_disconnect,
                             config.DEFAULTS["audio"]["mic_idle_disconnect_sec"])
        finally:
            pipeline.detach()
        del cfg["soniox"]["keep_speaker_context"]
        with patch("vrclt.pipeline.GameAudioTap", return_value=FakeSource()):
            pipeline = InboundPipeline(cfg, "test-soniox-key", store, state)
        try:
            self.assertEqual(pipeline.session._idle_disconnect, 60)
        finally:
            pipeline.detach()

    def test_keep_context_always_has_a_finite_silence_limit(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        self.assertEqual(config.soniox_idle_disconnect_sec(cfg), 60)
        cfg["soniox"]["speaker_context_idle_sec"] = 120
        self.assertEqual(config.soniox_idle_disconnect_sec(cfg), 120)
        for value in (0, -5, None, "bad", float("inf"), float("nan")):
            cfg["soniox"]["speaker_context_idle_sec"] = value
            self.assertEqual(config.soniox_idle_disconnect_sec(cfg), 60, repr(value))
        cfg["soniox"]["keep_speaker_context"] = False
        self.assertEqual(config.soniox_idle_disconnect_sec(cfg), 15)
        cfg["audio"]["mic_idle_disconnect_sec"] = 0
        self.assertEqual(config.soniox_idle_disconnect_sec(cfg), 0)
        cfg["soniox"]["keep_speaker_context"] = True
        self.assertEqual(config.soniox_idle_disconnect_sec(cfg), 60)


class SonioxWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_transcription_tts_and_finished_handshake(self):
        src, dst, audio, states = [], [], [], []
        configs, text_frames, input_audio, closes = [], [], [], []
        first_text, tts_done = asyncio.Event(), asyncio.Event()
        source = FakeSource()
        stop = asyncio.Event()

        async def stt_server(ws):
            configs.append(json.loads(await ws.recv()))
            seen_audio = False
            async for raw in ws:
                if raw == "":
                    closes.append(True)
                    await ws.send(json.dumps({"tokens": [], "finished": True}))
                    return
                if isinstance(raw, bytes) and not seen_audio:
                    seen_audio = True
                    input_audio.append(raw)
                    await ws.send(json.dumps({"tokens": [token("wrong", final=False)]}))
                    await ws.send(json.dumps({"tokens": [token("안녕", status="original", language="ko"),
                                                           token("Hello")]}))
                    # Prove TTS starts before the endpoint arrives.
                    await asyncio.wait_for(first_text.wait(), 3)
                    await ws.send(json.dumps({"tokens": [token(" world!"), token("<end>")]}))

        async def tts_server(ws):
            cfg = json.loads(await ws.recv())
            configs.append(cfg)
            stream_id = cfg["stream_id"]
            async for raw in ws:
                msg = json.loads(raw)
                text_frames.append(msg)
                if msg["text"]:
                    first_text.set()
                    await ws.send(json.dumps({"stream_id": stream_id,
                        "audio": base64.b64encode(b"\x11\x22" * 100).decode(), "audio_end": False}))
                if msg["text_end"]:
                    await ws.send(json.dumps({"stream_id": stream_id, "audio_end": True}))
                    await ws.send(json.dumps({"stream_id": stream_id, "terminated": True}))
                    tts_done.set()

        async with websockets.serve(stt_server, "127.0.0.1", 0) as stt_ws, \
                   websockets.serve(tts_server, "127.0.0.1", 0) as tts_ws:
            stt_url = f"ws://127.0.0.1:{stt_ws.sockets[0].getsockname()[1]}/transcribe-websocket"
            tts_url = f"ws://127.0.0.1:{tts_ws.sockets[0].getsockname()[1]}/tts-websocket"
            with patch.object(sx, "TRANSCRIBE_URL", stt_url), patch.object(tts, "TTS_URL", tts_url):
                session = make_session(source=source,
                    on_src=lambda text, lang: src.append((text, lang)), on_dst=dst.append,
                    on_audio=audio.append, on_session_state=states.append)
                task = asyncio.create_task(session.run(stop))
                try:
                    await asyncio.wait_for(tts_done.wait(), 5)
                    await asyncio.sleep(0.05)
                finally:
                    stop.set()
                    await asyncio.wait_for(task, 5)
        self.assertEqual(configs[0]["audio_format"], "pcm_s16le")
        self.assertEqual(configs[0]["sample_rate"], 16000)
        self.assertEqual(configs[0]["num_channels"], 1)
        self.assertEqual(configs[1]["model"], "tts-rt-v2")
        self.assertEqual(configs[1]["language"], "en")
        self.assertEqual(configs[1]["voice"], "Daniel")
        self.assertEqual(configs[1]["sample_rate"], 24000)
        self.assertEqual(input_audio, [b"\x01\x02" * 800])
        self.assertEqual(src, [("안녕", "ko")])
        self.assertEqual("".join(dst), "Hello world!")
        self.assertEqual("".join(m["text"] for m in text_frames), "Hello world!")
        self.assertTrue(text_frames[-1]["text_end"])
        self.assertEqual(b"".join(audio), b"\x11\x22" * 200)
        self.assertTrue(closes)
        self.assertEqual(states, [True, False])
        self.assertEqual(source.trimmed, [1.0])
        self.assertFalse(session.connected)
        self.assertFalse(session.last_error)

    async def test_text_only_never_connects_tts(self):
        stop = asyncio.Event()
        received = []
        async def server(ws):
            await ws.recv()
            await ws.recv()
            await ws.send(json.dumps({"tokens": [token("text only"), token("<end>")]}))
            async for raw in ws:
                if raw == "":
                    await ws.send(json.dumps({"tokens": [], "finished": True}))
                    return
        async with websockets.serve(server, "127.0.0.1", 0) as ws_server:
            url = f"ws://127.0.0.1:{ws_server.sockets[0].getsockname()[1]}"
            with patch.object(sx, "TRANSCRIBE_URL", url), patch.object(sx, "StreamingSpeech") as speech:
                session = make_session(on_dst=lambda text: (received.append(text), stop.set()))
                await asyncio.wait_for(session.run(stop), 5)
                self.assertIsNone(session._speech)
                speech.assert_not_called()
        self.assertEqual(received, ["text only"])

    async def test_invalid_key_is_fatal_without_retries(self):
        connections = []
        async def server(ws):
            connections.append(True)
            await ws.recv()
            await ws.send(json.dumps({"error_code": 401, "error_type": "unauthenticated",
                                      "error_message": "test-soniox-key rejected"}))
        async with websockets.serve(server, "127.0.0.1", 0) as ws_server:
            url = f"ws://127.0.0.1:{ws_server.sockets[0].getsockname()[1]}"
            with patch.object(sx, "TRANSCRIBE_URL", url):
                session = make_session()
                with self.assertRaises(FatalSessionError):
                    await asyncio.wait_for(session.run(asyncio.Event()), 3)
        self.assertEqual(len(connections), 1)
        self.assertFalse(session.connected)

    async def test_reconnect_resets_error_and_uses_changed_language(self):
        stop = asyncio.Event()
        targets, statuses, sleeps = [], [], []
        current = ["en"]
        async def server(ws):
            cfg = json.loads(await ws.recv())
            targets.append(cfg["translation"]["target_language"])
            if len(targets) == 1:
                await ws.send(json.dumps({"error_code": 429, "error_type": "limit_exceeded"}))
                return
            await ws.send(json.dumps({"tokens": [token("ready"), token("<end>")]}))
            async for raw in ws:
                if raw == "":
                    await ws.send(json.dumps({"finished": True}))
                    return
        async def backoff(delay, stop_event):
            sleeps.append(delay)
            self.assertEqual(session.error_class, "quota")
            self.assertGreater(session.next_retry_at, 0)
            current[0] = "ko"
        async with websockets.serve(server, "127.0.0.1", 0) as ws_server:
            url = f"ws://127.0.0.1:{ws_server.sockets[0].getsockname()[1]}"
            with patch.object(sx, "TRANSCRIBE_URL", url), patch.object(sx, "sleep_interruptible", backoff):
                session = make_session(get_target_language=lambda: current[0],
                                       on_dst=lambda _: stop.set(), on_session_state=statuses.append)
                await asyncio.wait_for(session.run(stop), 5)
        self.assertEqual(targets, ["en", "ko"])
        self.assertEqual(sleeps, [sx.RECONNECT_MIN_BACKOFF])
        self.assertEqual(statuses, [True, False, True, False])
        self.assertEqual(session.error_class, "")
        self.assertEqual(session.next_retry_at, 0)

    async def test_cancellation_cleans_up_stt_and_tts_tasks(self):
        connected = asyncio.Event()
        async def server(ws):
            await ws.recv()
            connected.set()
            await ws.wait_closed()
        async with websockets.serve(server, "127.0.0.1", 0) as ws_server:
            url = f"ws://127.0.0.1:{ws_server.sockets[0].getsockname()[1]}"
            with patch.object(sx, "TRANSCRIBE_URL", url):
                before = set(asyncio.all_tasks())
                session = make_session(on_audio=lambda _: None)
                task = asyncio.create_task(session.run(asyncio.Event()))
                await asyncio.wait_for(connected.wait(), 3)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                await asyncio.sleep(0.05)
                leaked = [t for t in asyncio.all_tasks() - before if not t.done()
                          and "IocpProactor.accept" not in t.get_coro().__qualname__]
                self.assertEqual(leaked, [])
                self.assertFalse(session.connected)

    async def test_failed_audio_send_requeues_capture(self):
        source = FakeSource()
        class BrokenSocket:
            async def send(self, raw):
                raise OSError("connection lost")
        session = make_session(source=source)
        with self.assertRaises(OSError):
            await session._sender(BrokenSocket())
        self.assertEqual(source.requeued, [b"\x01\x02" * 800])

    async def test_gated_silence_padding_and_keepalive(self):
        sent = []
        class Socket:
            async def send(self, raw):
                sent.append(raw)
                if isinstance(raw, str):
                    raise asyncio.CancelledError
        session = make_session()
        with patch.object(sx, "GAP_FILL_GRACE_SEC", 0), \
             patch.object(sx, "GAP_FILL_MAX_SEC", 0.05), patch.object(sx, "KEEPALIVE_SEC", 0.05):
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(session._sender(Socket()), 2)
        self.assertEqual(sent[0], b"\x01\x02" * 800)
        self.assertEqual(sent[1], b"\x00" * 1600)
        self.assertEqual(json.loads(sent[2]), {"type": "keepalive"})

    async def test_zero_idle_timeout_keeps_speaker_session_open_until_stopped(self):
        sent = []
        session = make_session(idle_disconnect_sec=0)
        session._source.is_active = False
        stop = asyncio.Event()
        class Socket:
            async def send(self, raw):
                sent.append(raw)
                session._finished.set()
        task = asyncio.create_task(session._watchdog(Socket(), stop))
        await asyncio.sleep(0.25)
        self.assertFalse(task.done())
        self.assertEqual(sent, [])
        stop.set()
        await asyncio.wait_for(task, 1)
        self.assertEqual(sent, [""])

    async def test_silent_pcm_closes_once_and_only_new_speech_reconnects(self):
        class UngatedSource(FakeSource):
            has_speech = False

            def drain(self):
                return [b"\x00" * 1600]

            def speech_active(self, timeout=2.0):
                return self.has_speech

        source = UngatedSource()
        stop = asyncio.Event()
        first_connected, first_closed, second_connected = (
            asyncio.Event(), asyncio.Event(), asyncio.Event())
        connections, closes, final_text = [], [], []

        async def server(ws):
            await ws.recv()
            connections.append(True)
            (first_connected if len(connections) == 1 else second_connected).set()
            async for raw in ws:
                if raw == "":
                    closes.append(True)
                    # Pending text must still drain when the idle deadline hits.
                    await ws.send(json.dumps({"tokens": [token("last words", speaker="1"),
                                                          token("<end>")], "finished": True}))
                    first_closed.set()
                    return

        async with websockets.serve(server, "127.0.0.1", 0) as ws_server:
            url = f"ws://127.0.0.1:{ws_server.sockets[0].getsockname()[1]}"
            with patch.object(sx, "TRANSCRIBE_URL", url):
                session = make_session(source=source, idle_disconnect_sec=60,
                                       on_dst=final_text.append)
                task = asyncio.create_task(session.run(stop))
                try:
                    # active() is True even for this source's continuous zeros.
                    await asyncio.sleep(0.25)
                    self.assertEqual(connections, [])
                    source.has_speech = True
                    await asyncio.wait_for(first_connected.wait(), 2)
                    source.has_speech = False
                    await asyncio.wait_for(first_closed.wait(), 2)
                    await asyncio.sleep(0.45)
                    self.assertEqual(len(connections), 1)
                    self.assertEqual(final_text, ["last words"])
                    self.assertFalse(session.connected)
                    source.has_speech = True
                    await asyncio.wait_for(second_connected.wait(), 2)
                    stop.set()
                    await asyncio.wait_for(task, 2)
                    self.assertEqual(len(closes), 2)
                finally:
                    stop.set()
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_watchdog_uses_configured_speech_timeout(self):
        source = FakeSource()
        source.speech_active = lambda timeout=2.0: timeout > 30
        session = make_session(source=source, idle_disconnect_sec=60)
        sent = []

        class Socket:
            async def send(self, raw):
                sent.append(raw)
                session._finished.set()

        task = asyncio.create_task(session._watchdog(Socket(), asyncio.Event()))
        try:
            await asyncio.sleep(0.25)
            self.assertFalse(task.done(), "short pause ended retained context")
            source.speech_active = lambda timeout=2.0: False
            await asyncio.wait_for(task, 1)
            self.assertEqual(sent, [""])
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
