"""Silero VAD (ONNX) - lightweight voice-activity detection, no torch.

Used on the inbound (game audio) path so only speech is sent to Gemini -
background music alone is gated out (no spurious translation / junk tokens).
The ~2.3 MB ONNX model is downloaded once to the per-user app data directory.
"""
import logging
import os
import urllib.request

import numpy as np

from .. import platform_support

log = logging.getLogger(__name__)

MODEL_PATH = platform_support.app_data_dir() / "silero_vad.onnx"
MODEL_URL = ("https://github.com/snakers4/silero-vad/raw/master/"
             "src/silero_vad/data/silero_vad.onnx")
MODEL_MIN_BYTES = 500_000  # real model is ~2.3 MB; smaller = truncated/error page
FRAME = 512    # new samples per inference @ 16 kHz (~32 ms)
CONTEXT = 64   # Silero v5 prepends the previous 64 samples to each frame


def _download_model() -> None:
    """Download to a temp file, validate, then atomically promote: an
    interrupted download must never leave a corrupt file at MODEL_PATH
    (its existence is what skips re-downloading on the next run)."""
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MODEL_PATH.with_name(MODEL_PATH.name + ".tmp")
    log.info("downloading Silero VAD model -> %s", MODEL_PATH)
    try:
        urllib.request.urlretrieve(MODEL_URL, tmp)
        if tmp.stat().st_size < MODEL_MIN_BYTES:
            raise RuntimeError(
                f"VAD model download too small ({tmp.stat().st_size} bytes)")
        os.replace(tmp, MODEL_PATH)
    finally:
        tmp.unlink(missing_ok=True)


class SileroVAD:
    def __init__(self):
        import onnxruntime as ort
        if not MODEL_PATH.exists():
            _download_model()
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        try:
            self._sess = ort.InferenceSession(
                str(MODEL_PATH), sess_options=opts, providers=["CPUExecutionProvider"])
        except Exception:
            # a corrupt file (e.g. from an old non-atomic download) would
            # otherwise disable VAD forever; drop it so the next run re-downloads
            MODEL_PATH.unlink(missing_ok=True)
            raise
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
