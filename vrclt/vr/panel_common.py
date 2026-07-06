"""Helpers shared by the VR overlay panels (wrist menu, subtitles, dashboard).

Pure functions only - panels stay independent classes and pick what they need.
Interaction-specific logic (ray hits, gaze, drag/resize) intentionally stays
per-panel: the semantics differ and the dashboard panel gets SteamVR-provided
mouse events instead.
"""
import json
import logging
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ..languages import KNOWN_LANGUAGE_NAMES, canonical_language_code

log = logging.getLogger(__name__)

LASER_TEX_W, LASER_TEX_H = 4, 512
LASER_WIDTH_M = 0.004
LASER_LEN_M = LASER_WIDTH_M * LASER_TEX_H / LASER_TEX_W  # 0.512 m

COL_BG = (16, 18, 24, 235)
COL_BTN = (38, 42, 54, 255)
COL_ON = (46, 160, 67, 255)
COL_OFF = (120, 84, 30, 255)
COL_SUB_ON = (40, 110, 170, 255)
COL_TEXT = (240, 240, 240, 255)
COL_DIM = (150, 150, 150, 255)
COL_DRAG = (70, 110, 180, 255)


# ---------------- overlays / input ----------------
def create_overlay_set(ovl, specs, label: str):
    """Create the given (key, name) overlays; None if the keys are already
    owned by another vrclt instance, raising on any other failure."""
    created = []
    try:
        for key, name in specs:
            created.append(ovl.createOverlay(key, name))
    except Exception as e:
        for h in created:
            try:
                ovl.destroyOverlay(h)
            except Exception:
                pass
        if "KeyInUse" in type(e).__name__:
            log.warning("%s: overlay key in use - another vrclt instance running?", label)
            return None
        raise
    return created


def haptic(vrsys, openvr, device_idx, micros: int) -> None:
    if device_idx == openvr.k_unTrackedDeviceIndexInvalid:
        return
    try:
        vrsys.triggerHapticPulse(device_idx, 0, micros)
    except Exception:
        pass


def cycle(langs: list[str], cur: str, step: int) -> str:
    idx = langs.index(cur) if cur in langs else 0
    return langs[(idx + step) % len(langs)]


def language_label(code: str) -> str:
    code = canonical_language_code(code)
    return KNOWN_LANGUAGE_NAMES.get(code, code)


# ---------------- textures ----------------
def laser_texture() -> Image.Image:
    img = Image.new("RGBA", (LASER_TEX_W, LASER_TEX_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(LASER_TEX_H):
        a = int(220 * (1.0 - y / LASER_TEX_H))
        d.line([(0, y), (LASER_TEX_W, y)], fill=(120, 180, 255, a))
    return img


def cursor_texture() -> Image.Image:
    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, s - 4, s - 4), outline=(255, 255, 255, 230), width=6)
    d.ellipse((22, 22, s - 22, s - 22), fill=(120, 180, 255, 255))
    return img


# ---------------- text layout ----------------
def line_height(draw, font) -> int:
    try:
        return font.line_height(draw)
    except Exception:
        return max(1, int(getattr(font, "size", 20)))


def wrap_to_width(draw, text: str, font, max_width: float) -> list[str]:
    if font.textlength(draw, text) <= max_width:
        return [text]

    if " " in text:
        parts = text.split(" ")
        sep = " "
    else:
        parts = list(text)
        sep = ""

    lines: list[str] = []
    line = ""
    for part in parts:
        candidate = part if not line else f"{line}{sep}{part}"
        if font.textlength(draw, candidate) <= max_width:
            line = candidate
            continue
        if line:
            lines.append(line)
            line = ""
        if font.textlength(draw, part) <= max_width:
            line = part
            continue
        chunk = ""
        for ch in part:
            candidate = f"{chunk}{ch}"
            if chunk and font.textlength(draw, candidate) > max_width:
                lines.append(chunk)
                chunk = ch
            else:
                chunk = candidate
        line = chunk
    if line:
        lines.append(line)
    return lines or [text]


def clip_line(draw, text: str, font, max_width: float) -> str:
    if font.textlength(draw, text) <= max_width:
        return text
    suffix = "..."
    while text and font.textlength(draw, text + suffix) > max_width:
        text = text[:-1]
    return (text + suffix) if text else suffix


def draw_fit_text(d, box, text: str, *, fonts, fill=COL_TEXT,
                  max_lines: int = 1, pad_x: int = 8, pad_y: int = 4,
                  line_spacing: int = 2) -> None:
    """Draw text centered in box, picking the largest font (of `fonts`,
    big-to-small) whose wrapped lines fit; clips with '...' as a last resort."""
    x0, y0, x1, y1 = box
    max_width = max(1, x1 - x0 - pad_x * 2)
    max_height = max(1, y1 - y0 - pad_y * 2)

    chosen_font = fonts[-1]
    chosen_lines = [text]
    chosen_spacing = 0
    for font in fonts:
        line_h = line_height(d, font)
        spacing = line_spacing if max_lines > 1 else 0
        lines = wrap_to_width(d, text, font, max_width)
        if len(lines) > max_lines:
            continue
        total_h = len(lines) * line_h + max(0, len(lines) - 1) * spacing
        if total_h <= max_height and all(font.textlength(d, line) <= max_width
                                         for line in lines):
            chosen_font = font
            chosen_lines = lines
            chosen_spacing = spacing
            break

    line_h = line_height(d, chosen_font)
    lines = wrap_to_width(d, text, chosen_font, max_width)
    truncated = len(lines) > max_lines
    lines = lines[:max_lines]
    if truncated and lines:
        lines[-1] = clip_line(d, lines[-1], chosen_font, max_width)
    lines = [clip_line(d, line, chosen_font, max_width) for line in lines]
    total_h = len(lines) * line_h + max(0, len(lines) - 1) * chosen_spacing
    while len(lines) > 1 and total_h > max_height:
        lines = lines[:-1]
        lines[-1] = clip_line(d, lines[-1], chosen_font, max_width)
        total_h = len(lines) * line_h + max(0, len(lines) - 1) * chosen_spacing
    y = (y0 + y1 - total_h) / 2
    cx = (x0 + x1) / 2
    for line in lines:
        chosen_font.draw(d, (cx, y + line_h / 2), line, fill=fill, anchor="mm")
        y += line_h + chosen_spacing


# ---------------- matrices ----------------
def matrix_from_rows(rows) -> np.ndarray:
    m = np.identity(4)
    for r in range(3):
        for c in range(4):
            m[r][c] = float(rows[r][c])
    return m


def coerce_transform(rows, label: str) -> np.ndarray | None:
    if not rows:
        return None
    try:
        return matrix_from_rows(rows)
    except Exception:
        log.warning("%s: invalid configured transform - ignoring", label, exc_info=True)
        return None


def load_saved_transform(path: Path, label: str) -> np.ndarray | None:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        m = matrix_from_rows(rows)
        log.info("%s: restored saved position", label)
        return m
    except FileNotFoundError:
        return None
    except Exception:
        log.warning("%s: invalid saved transform - using defaults", label, exc_info=True)
        return None


def save_transform(m: np.ndarray, path: Path, label: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [[float(m[r][c]) for c in range(4)] for r in range(3)]
        path.write_text(json.dumps(rows), encoding="utf-8")
    except Exception:
        log.warning("%s: failed to save transform to %s", label, path, exc_info=True)


def translate(x: float, y: float, z: float) -> np.ndarray:
    m = np.identity(4)
    m[0][3], m[1][3], m[2][3] = x, y, z
    return m


def pointer_matrix(pointer_tilt_deg: float) -> np.ndarray:
    a = math.radians(-pointer_tilt_deg)
    m = np.identity(4)
    m[1][1] = math.cos(a)
    m[1][2] = -math.sin(a)
    m[2][1] = math.sin(a)
    m[2][2] = math.cos(a)
    return m


def laser_base() -> np.ndarray:
    a = math.radians(-90.0)
    m = np.identity(4)
    m[1][1] = math.cos(a)
    m[1][2] = -math.sin(a)
    m[2][1] = math.sin(a)
    m[2][2] = math.cos(a)
    m[2][3] = -LASER_LEN_M / 2
    return m


def pose_to_np(pose) -> np.ndarray:
    m = pose.mDeviceToAbsoluteTracking
    out = np.identity(4)
    for r in range(3):
        for c in range(4):
            out[r][c] = m[r][c]
    return out


def np_to_hmd34(openvr, m: np.ndarray):
    t = openvr.HmdMatrix34_t()
    for r in range(3):
        for c in range(4):
            t[r][c] = float(m[r][c])
    return t
