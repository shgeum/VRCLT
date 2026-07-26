"""Declarative widget table for the PIL-rendered VR panels.

One table per panel describes every drawn rect: buttons AND inert labels.
The same table drives rendering (draw_page) and hit-testing (widget_at), so
draw rects and hit rects can no longer diverge, and per-widget state
(enabled / fill / dynamic label) lives next to the rect instead of being
scattered through a hand-written render method.

All callables receive the owning panel, so the table itself is built once.
"""
import math
from dataclasses import dataclass
from typing import Callable, Optional

from ..ui import theme
from .panel_common import COL_BTN, COL_DIM, COL_TEXT, draw_fit_text, language_label


@dataclass(frozen=True)
class Widget:
    name: str
    rect: tuple                     # (x0, y0, x1, y1) texture pixels
    kind: str = "button"            # "button" | "label"
    page: str = "main"
    radius: int = 12
    enabled: Optional[Callable] = None   # panel -> bool; None = always
    fill: Optional[Callable] = None      # panel -> RGBA base fill; None = COL_BTN
    draw: Optional[Callable] = None      # (panel, d, widget, lang) -> None (custom body)
    label: Optional[Callable] = None     # (panel, lang) -> str (generic centered text)
    label_fonts: Optional[Callable] = None  # panel -> font ladder for `label`


def is_enabled(widget: Widget, panel) -> bool:
    return widget.enabled is None or bool(widget.enabled(panel))


def widget_at(widgets, panel, px: float, py: float,
              page: str = "main") -> Optional[str]:
    """Topmost enabled button under (px, py) on `page`, else None. Disabled
    and label widgets are transparent to hit-testing."""
    for w in widgets:
        if w.page != page or w.kind != "button":
            continue
        x0, y0, x1, y1 = w.rect
        if x0 <= px <= x1 and y0 <= py <= y1:
            return w.name if is_enabled(w, panel) else None
    return None


def draw_widget(panel, d, w: Widget, lang: str, *,
                hover: Optional[str] = None,
                pressed: Optional[str] = None) -> None:
    enabled = is_enabled(w, panel)
    fill = w.fill(panel) if w.fill is not None else COL_BTN
    if w.kind == "button" and enabled:
        if pressed == w.name:
            fill = theme.darken(fill)
        elif hover == w.name:
            fill = theme.lighten(fill)
    d.rounded_rectangle(w.rect, w.radius, fill=fill)
    if w.draw is not None:
        w.draw(panel, d, w, lang)
    elif w.label is not None:
        fonts = w.label_fonts(panel) if w.label_fonts else panel.label_fonts()
        draw_fit_text(d, w.rect, w.label(panel, lang), fonts=fonts,
                      fill=COL_TEXT if enabled else COL_DIM,
                      max_lines=1, pad_x=5, pad_y=2, line_spacing=0)


def draw_page(panel, d, widgets, lang: str, page: str = "main", *,
              hover: Optional[str] = None,
              pressed: Optional[str] = None) -> None:
    for w in widgets:
        if w.page == page:
            draw_widget(panel, d, w, lang, hover=hover, pressed=pressed)


def glyph_draw(glyph: str):
    """Centered single-glyph body (arrows, +/-, close) in the panel's mid
    font; dims with the widget's enabled state."""
    def draw(panel, d, w, lang):
        col = COL_TEXT if is_enabled(w, panel) else COL_DIM
        panel._font_mid.draw(d, ((w.rect[0] + w.rect[2]) // 2,
                                 (w.rect[1] + w.rect[3]) // 2),
                             glyph, fill=col, anchor="mm")
    return draw


def lang_page_count(languages, cols: int, rows: int) -> int:
    return max(1, math.ceil(len(languages) / (cols * rows)))


def lang_grid_widgets(*, page: str, languages, page_idx: int, area,
                      cols: int, rows: int, name_prefix: str,
                      current_of: Callable, accent, gap: int = 8) -> list:
    """One page of a language grid picker: a Widget per language code,
    named f'{name_prefix}:{code}'. The cell for the currently selected
    language fills with `accent`. Header chrome (caption/close/pager) is
    the caller's, so both panels can lay it out to their own texture."""
    per_page = cols * rows
    n_pages = lang_page_count(languages, cols, rows)
    page_idx = max(0, min(page_idx, n_pages - 1))
    chunk = languages[page_idx * per_page:(page_idx + 1) * per_page]
    x0, y0, x1, y1 = area
    cell_w = (x1 - x0 - (cols - 1) * gap) / cols
    cell_h = (y1 - y0 - (rows - 1) * gap) / rows
    widgets = []
    for i, code in enumerate(chunk):
        row, col = divmod(i, cols)
        cx = x0 + col * (cell_w + gap)
        cy = y0 + row * (cell_h + gap)
        widgets.append(Widget(
            f"{name_prefix}:{code}", (round(cx), round(cy),
                                      round(cx + cell_w), round(cy + cell_h)),
            page=page, radius=16,
            fill=(lambda p, code=code:
                  accent if current_of(p) == code else COL_BTN),
            label=(lambda p, lang, code=code: language_label(code))))
    return widgets
