"""Voice-idle regressions with synthetic PCM; no devices, models or network."""
import pathlib
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vrclt.audio.game_tap import GameAudioTap
from vrclt.audio.mic_in import MicCapture


class PassthroughResampler:
    def resample_chunk(self, samples):
        return samples


class FakeVad:
    probability = 0.0

    def prob(self, frame):
        return self.probability


class SpeechActivityTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.wall_offset = 10000.0
        self.enterContext(patch("time.monotonic", side_effect=lambda: self.now))
        self.enterContext(patch("time.time", side_effect=lambda: self.wall_offset + self.now))

    def mic(self, **kwargs):
        mic = MicCapture(**kwargs)
        mic._rs = PassthroughResampler()
        return mic

    @staticmethod
    def feed_mic(mic, level):
        pcm = np.full(480, level, dtype=np.int16).tobytes()
        mic._callback(pcm, 480, None, None, mic._rs)

    def tap(self, **kwargs):
        tap = GameAudioTap(**kwargs)
        tap._rs = PassthroughResampler()
        return tap

    @staticmethod
    def feed_tap(tap, level):
        # The capture contract is 48 kHz stereo float32. Resampling itself is
        # irrelevant here; leave 512 mono samples for one synthetic VAD frame.
        pcm = np.full((512, 2), level / 32768.0, dtype=np.float32).tobytes()
        tap._on_data(pcm, 512)

    def test_ungated_mic_silence_expires_and_speech_resumes(self):
        mic = self.mic()
        mic.set_gate_enabled(lambda: False)
        raw = mic.add_raw_tap()
        self.feed_mic(mic, 0)
        self.assertTrue(mic.active())
        self.assertFalse(mic.speech_active(300))
        self.feed_mic(mic, 200)
        self.assertTrue(mic.speech_active())
        for self.now in (1.0, 50.0, 299.9):
            self.feed_mic(mic, 0)
            self.assertTrue(mic.speech_active(300))
        self.now = 300.0
        self.feed_mic(mic, 0)
        self.assertTrue(mic.active(), "PCM-flow behavior must remain unchanged")
        self.assertFalse(mic.speech_active(300))
        self.assertEqual(len(raw), len(mic.buffer))
        self.feed_mic(mic, 200)
        self.assertTrue(mic.speech_active())

    def test_mic_hysteresis_does_not_reopen_on_weak_noise_after_pause(self):
        mic = self.mic(voice_rms_threshold=100, hangover_sec=0.5)
        mic.set_gate_enabled(lambda: False)
        self.feed_mic(mic, 50)
        self.assertFalse(mic.speech_active())
        self.feed_mic(mic, 200)
        self.now = 0.1
        self.feed_mic(mic, 50)
        self.now = 0.6
        self.assertTrue(mic.speech_active(0.55), "weak speech should extend activity")
        self.now = 1.0
        self.feed_mic(mic, 50)
        self.assertFalse(mic.speech_active(0.55))

    def test_mic_gate_zero_still_rejects_digital_silence(self):
        mic = self.mic(voice_rms_threshold=0)
        self.feed_mic(mic, 0)
        self.assertTrue(mic.active())
        self.assertFalse(mic.speech_active())
        self.feed_mic(mic, 1)
        self.assertTrue(mic.speech_active())

    def test_echo_suppression_does_not_extend_mic_activity_or_block_raw_tap(self):
        mic = self.mic()
        raw = mic.add_raw_tap()
        self.feed_mic(mic, 200)
        mic.set_suppressed(lambda: True)
        self.now = 3.0
        self.feed_mic(mic, 2000)
        self.assertFalse(mic.speech_active())
        self.assertEqual(len(raw), 2)
        mic.set_suppressed(lambda: True, barge_in_multiplier=2.0)
        self.feed_mic(mic, 2000)
        self.assertTrue(mic.speech_active(), "accepted barge-in should resume speech")

    def test_mic_echo_boost_is_respected_with_pcm_gate_disabled(self):
        mic = self.mic()
        mic.set_gate_enabled(lambda: False)
        mic.set_threshold_boost(lambda: 5.0)
        self.feed_mic(mic, 200)
        self.assertTrue(mic.active())
        self.assertFalse(mic.speech_active())
        self.feed_mic(mic, 1000)
        self.assertTrue(mic.speech_active())

    def test_tap_without_vad_expires_on_silent_pcm_and_resumes_on_energy(self):
        for requested_vad in (False, True):
            with self.subTest(requested_vad=requested_vad):
                self.now = 0.0
                # _vad=None covers both disabled VAD and a failed model load.
                tap = self.tap(use_vad=requested_vad)
                self.feed_tap(tap, 0)
                self.assertTrue(tap.active())
                self.assertFalse(tap.speech_active(300))
                self.feed_tap(tap, 200)
                self.assertTrue(tap.speech_active())
                for self.now in (1.0, 50.0, 299.9):
                    self.feed_tap(tap, 0)
                    self.assertTrue(tap.speech_active(300))
                self.now = 300.0
                self.feed_tap(tap, 0)
                self.assertTrue(tap.active())
                self.assertFalse(tap.speech_active(300))
                self.feed_tap(tap, 200)
                self.assertTrue(tap.speech_active())

    def test_tap_vad_rejects_non_speech_energy_and_hangover_does_not_extend_activity(self):
        tap = self.tap()
        tap._vad = vad = FakeVad()
        self.feed_tap(tap, 2000)
        self.assertFalse(tap.speech_active())
        vad.probability = 0.9
        self.feed_tap(tap, 2000)
        self.assertTrue(tap.speech_active())
        vad.probability = 0.0
        self.now = 0.3
        self.feed_tap(tap, 0)
        self.assertTrue(tap.active(0.1), "VAD hangover still queues PCM")
        self.assertFalse(tap.speech_active(0.2), "hangover is not fresh speech")
        self.now = 5.0
        self.feed_tap(tap, 2000)
        self.assertFalse(tap.speech_active())
        vad.probability = 0.9
        self.feed_tap(tap, 2000)
        self.assertTrue(tap.speech_active())

    def test_activity_expiry_uses_monotonic_clock_for_both_sources(self):
        for source, feed in ((self.mic(), self.feed_mic), (self.tap(), self.feed_tap)):
            with self.subTest(source=type(source).__name__):
                self.now = 0.0
                feed(source, 200)
                self.wall_offset -= 100000
                self.now = 3.0
                self.assertFalse(source.speech_active())
                feed(source, 200)
                self.wall_offset += 200000
                self.assertTrue(source.speech_active())

    def test_stop_and_failed_start_forget_previous_activity(self):
        mic = self.mic()
        self.feed_mic(mic, 200)
        mic.stop()
        self.assertFalse(mic.speech_active(300))
        mic._rs = PassthroughResampler()
        self.assertFalse(mic.speech_active(300))
        self.feed_mic(mic, 200)
        with patch("vrclt.audio.mic_in.devices.find_input_candidates", return_value=[]):
            with self.assertRaises(RuntimeError):
                mic.start()
        self.assertFalse(mic.speech_active(300))

        tap = self.tap()
        self.feed_tap(tap, 200)
        tap.stop()
        self.assertFalse(tap.speech_active(300))
        tap._rs = PassthroughResampler()
        self.assertFalse(tap.speech_active(300))
        self.feed_tap(tap, 200)
        with patch.dict(sys.modules, {"proctap": type("FakeProcTap", (), {
                "ProcessAudioCapture": object})}), \
                patch("vrclt.audio.game_tap.find_pid", return_value=None):
            with self.assertRaises(RuntimeError):
                tap.start()
        self.assertFalse(tap.speech_active(300))


if __name__ == "__main__":
    unittest.main(verbosity=2)
