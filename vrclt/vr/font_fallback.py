"""Small PIL text helper with Windows font fallbacks for VR overlays."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from PIL import ImageDraw, ImageFont

from ..resources import font_path

log = logging.getLogger(__name__)

_WIN_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def _first_existing(names: list[str]) -> str | None:
    for name in names:
        path = _WIN_FONTS / name
        if path.exists():
            return str(path)
    return None


def _unique(values: list[str | None]) -> list[str]:
    seen = set()
    out: list[str] = []
    for value in values:
        if not value:
            continue
        key = value.replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _bundled(name: str) -> str | None:
    path = font_path(name)
    return str(path) if path.exists() else None


def _font_candidates(bold: bool) -> dict[str, list[str]]:
    segoe = _first_existing(["segoeuib.ttf" if bold else "segoeui.ttf", "segoeui.ttf"])
    cjk_kr = _first_existing(["malgunbd.ttf" if bold else "malgun.ttf", "malgun.ttf"])
    cjk_jp = _first_existing(["meiryob.ttc" if bold else "meiryo.ttc", "meiryo.ttc"])
    cjk_zh = _first_existing(["msyhbd.ttc" if bold else "msyh.ttc", "msyh.ttc", "simsun.ttc"])
    return {
        "cjk": _unique([
            _bundled("NotoSansCJKkr-Bold.otf" if bold else "NotoSansCJKkr-Regular.otf"),
            _bundled("NotoSansCJKsc-Bold.otf" if bold else "NotoSansCJKsc-Regular.otf"),
            cjk_kr,
            cjk_jp,
            cjk_zh,
        ]),
        "thai": _unique([
            _first_existing(["LeelawUI.ttf"]),
            segoe,
        ]),
        "indic": _unique([
            _first_existing(["NirmalaB.ttf" if bold else "Nirmala.ttf", "Nirmala.ttc"]),
            segoe,
        ]),
        "arabic": _unique([
            segoe,
            _first_existing(["tahomabd.ttf" if bold else "tahoma.ttf", "tahoma.ttf"]),
        ]),
        "hebrew": _unique([
            segoe,
            _first_existing(["tahomabd.ttf" if bold else "tahoma.ttf", "tahoma.ttf"]),
        ]),
        "african": _unique([
            _first_existing(["ebrimabd.ttf" if bold else "ebrima.ttf", "ebrima.ttf"]),
            segoe,
        ]),
        "caucasus": _unique([
            _first_existing(["sylfaen.ttf"]),
            segoe,
        ]),
        "symbol": _unique([
            _first_existing(["seguisym.ttf", "SegoeIcons.ttf", "symbol.ttf"]),
            segoe,
        ]),
        "emoji": _unique([
            _first_existing(["seguiemj.ttf", "seguisym.ttf"]),
            segoe,
        ]),
    }


def _script_key(ch: str) -> str | None:
    cp = ord(ch)
    if cp < 0x80 or ch.isspace():
        return None
    if (
        0x1100 <= cp <= 0x11FF
        or 0x2E80 <= cp <= 0x303F
        or 0x3040 <= cp <= 0x30FF
        or 0x3130 <= cp <= 0x318F
        or 0x31F0 <= cp <= 0x31FF
        or 0x3400 <= cp <= 0x9FFF
        or 0xAC00 <= cp <= 0xD7AF
        or 0xF900 <= cp <= 0xFAFF
    ):
        return "cjk"
    if 0x0E00 <= cp <= 0x0EFF:
        return "thai"
    if (
        0x0900 <= cp <= 0x0DFF
        or 0x1000 <= cp <= 0x109F
        or 0x1780 <= cp <= 0x17FF
    ):
        return "indic"
    if 0x0590 <= cp <= 0x05FF:
        return "hebrew"
    if 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F or 0x08A0 <= cp <= 0x08FF:
        return "arabic"
    if 0x0530 <= cp <= 0x058F or 0x10A0 <= cp <= 0x10FF:
        return "caucasus"
    if 0x1200 <= cp <= 0x139F or 0x07C0 <= cp <= 0x07FF or 0x1E900 <= cp <= 0x1E95F:
        return "african"
    if 0x1F000 <= cp <= 0x1FAFF:
        return "emoji"
    # Do not route general punctuation (U+2000-U+206F) to symbol fonts:
    # quotes, ellipses, and dashes need to share the text baseline.
    if 0x2190 <= cp <= 0x27BF or 0xE000 <= cp <= 0xF8FF:
        return "symbol"
    return None


class FallbackFont:
    def __init__(self, primary, script_fonts: dict[str, object], size: int):
        self.primary = primary
        self._script_fonts = script_fonts
        self.size = size

    def font_for_char(self, ch: str):
        key = _script_key(ch)
        return self._script_fonts.get(key) or self.primary

    def runs(self, text: str):
        current_font = None
        current_text = ""
        for ch in str(text):
            font = self.font_for_char(ch)
            if current_font is None:
                current_font = font
                current_text = ch
            elif font is current_font:
                current_text += ch
            else:
                yield current_font, current_text
                current_font = font
                current_text = ch
        if current_text:
            yield current_font, current_text

    def textlength(self, draw: ImageDraw.ImageDraw, text: str) -> float:
        return sum(float(draw.textlength(run, font=font)) for font, run in self.runs(text))

    def _fonts(self) -> list[object]:
        seen = set()
        fonts = []
        for font in (self.primary, *self._script_fonts.values()):
            key = id(font)
            if key in seen:
                continue
            seen.add(key)
            fonts.append(font)
        return fonts

    @staticmethod
    def _font_extents(draw: ImageDraw.ImageDraw, font) -> tuple[int, int]:
        samples = "Ag가日กمअ"
        try:
            box = draw.textbbox((0, 0), samples, font=font, anchor="ls")
            return int(box[1]), int(box[3])
        except Exception:
            try:
                box = draw.textbbox((0, 0), samples, font=font)
                return int(box[1]), int(box[3])
            except Exception:
                return -int(getattr(font, "size", 20)), 0

    def _line_extents(self, draw: ImageDraw.ImageDraw) -> tuple[int, int]:
        top = 0
        bottom = 0
        for font in self._fonts():
            font_top, font_bottom = self._font_extents(draw, font)
            top = min(top, font_top)
            bottom = max(bottom, font_bottom)
        if bottom <= top:
            return -self.size, 0
        return top, bottom

    def line_height(self, draw: ImageDraw.ImageDraw) -> int:
        top, bottom = self._line_extents(draw)
        return max(1, int(bottom - top))

    def draw(self, draw: ImageDraw.ImageDraw, xy, text: str, *, fill, anchor: str = "la",
             stroke_width: int = 0, stroke_fill=None) -> None:
        x, y = xy
        width = self.textlength(draw, text)
        top, bottom = self._line_extents(draw)
        if anchor == "mm":
            left = x - width / 2
            baseline = y - (top + bottom) / 2
        elif anchor == "lm":
            left = x
            baseline = y - (top + bottom) / 2
        elif anchor == "lt":
            left = x
            baseline = y - top
        else:
            left = x
            baseline = y - top
        cur_x = left
        for font, run in self.runs(text):
            try:
                draw.text((cur_x, baseline), run, font=font, fill=fill, anchor="ls",
                          stroke_width=stroke_width, stroke_fill=stroke_fill)
            except Exception:
                draw.text((cur_x, baseline + top), run, font=font, fill=fill, anchor="lt",
                          stroke_width=stroke_width, stroke_fill=stroke_fill)
            cur_x += float(draw.textlength(run, font=font))


def load_fallback_font(primary_path: str, size: int, *, bold: bool = False) -> FallbackFont:
    try:
        primary = ImageFont.truetype(primary_path, size)
    except OSError:
        log.warning("failed to load primary font: %s", primary_path, exc_info=True)
        primary = ImageFont.load_default()

    script_fonts = {}
    for key, paths in _font_candidates(bold).items():
        for path in paths:
            try:
                script_fonts[key] = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
    return FallbackFont(primary, script_fonts, size)
