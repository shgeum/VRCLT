"""Declarative widget table for the PIL-rendered VR panels.

One table per panel describes every drawn rect: buttons AND inert labels.
The same table drives rendering (draw_page) and hit-testing (widget_at), so
draw rects and hit rects can no longer diverge, and per-widget state
(enabled / fill / dynamic label) lives next to the rect instead of being
scattered through a hand-written render method.

All callables receive the owning panel, so the table itself is built once.
"""
from dataclasses import dataclass
from typing import Callable, Optional

from ..ui import theme
from .panel_common import COL_BTN, COL_DIM, COL_TEXT, draw_fit_text


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
