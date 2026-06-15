"""Silero VAD (ONNX) - lightweight voice-activity detection, no torch.

Used on the inbound (game audio) path so only speech is sent to Gemini -
background music alone is gated out (no spurious translation / junk tokens).
The ~2.3 MB ONNX model is downloaded once to %LOCALAPPDATA%/vrclt.
"""
import logging
import os
import urllib.request
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

MODEL_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "vrclt" / "silero_vad.onnx"
MODEL_URL = ("https://github.com/snakers4/silero-vad/raw/master/"
             "src/silero_vad/data/silero_vad.onnx")
FRAME = 512    # new samples per inference @ 16 kHz (~32 ms)
CONTEXT = 64   # Silero v5 prepends the previous 64 samples to each frame


class SileroVAD:
    def __init__(self):
        import onnxruntime as ort
        if not MODEL_PATH.exists():
            MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            log.info("downloading Silero VAD model -> %s", MODEL_PATH)
            urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._sess = ort.InferenceSession(
            str(MODEL_PATH), sess_options=opts, providers=["CPUExecutionProvider"])
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT), dtype=np.float32)
        self._sr = np.array(16000, dtype=np.int64)

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT), dtype=np.float32)

    def prob(self, frame_f32: np.ndarray) -> float:
        """frame_f32: exactly FRAME float32 samples in [-1, 1]. Returns speech prob.

        Silero v5 expects [context(64) + frame(512)] = 576 samples; passing only
        512 silently produces near-zero probs."""
        frame = frame_f32.reshape(1, -1).astype(np.float32)
        x = np.concatenate([self._context, frame], axis=1)  # (1, 576)
        out, self._state = self._sess.run(
            None, {"input": x, "state": self._state, "sr": self._sr})
        self._context = x[:, -CONTEXT:]
        return float(out.reshape(-1)[0])
