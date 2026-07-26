"""Regression guard for the VR panels' declarative widget tables.

The tables replaced hand-maintained BUTTONS tuples; these snapshots pin the
pre-refactor names and rects so a table edit can't silently shift a hit area.
Pure Python - no OpenVR/GL runtime needed (module import only).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrclt.vr import dashboard_panel, wrist_ui
from vrclt.vr.button_table import widget_at

# pre-refactor BUTTONS snapshot (wrist panel)
WRIST_BUTTONS = {
    "toggle": (16, 86, 306, 302),
    "prev": (322, 86, 388, 302),
    "next": (556, 86, 624, 302),
    "sub_toggle": (16, 322, 306, 538),
    "sub_prev": (322, 322, 388, 538),
    "sub_next": (556, 322, 624, 538),
    "edit": (344, 14, 432, 66),
    "sub_edit": (440, 14, 528, 66),
    "reset": (536, 14, 624, 66),
    "uilang": (108, 14, 196, 66),
    "text_only": (204, 14, 336, 66),
    "restart": (16, 554, 200, 630),
    "font_minus": (216, 554, 296, 630),
    "font_plus": (412, 554, 492, 630),
}

# pre-refactor BUTTONS snapshot (dashboard panel)
DASH_BUTTONS = {
    "toggle": (16, 94, 500, 300),
    "prev": (516, 94, 596, 300),
    "next": (932, 94, 1008, 300),
    "sub_toggle": (16, 320, 500, 526),
    "sub_prev": (516, 320, 596, 526),
    "sub_next": (932, 320, 1008, 526),
    "text_only": (16, 662, 240, 740),
    "font_minus": (264, 662, 344, 740),
    "font_plus": (460, 662, 540, 740),
    "sub_edit": (564, 662, 724, 740),
    "wrist_edit": (748, 662, 908, 740),
    "reset": (924, 662, 1008, 740),
    "uilang": (560, 14, 668, 74),
    "autostart": (684, 14, 856, 74),
    "restart": (872, 14, 1008, 74),
    "mic_prev": (16, 546, 80, 642),
    "mic_next": (432, 546, 496, 642),
    "out_prev": (528, 546, 592, 642),
    "out_next": (944, 546, 1008, 642),
    "vol_minus": (16, 760, 96, 838),
    "vol_plus": (252, 760, 332, 838),
    "src_prev": (16, 858, 80, 936),
    "src_next": (432, 858, 496, 936),
    "insrc_prev": (528, 858, 592, 936),
    "insrc_next": (944, 858, 1008, 936),
}


class _PermissivePanel:
    """Stub panel where every `enabled` function returns True."""
    class _St:
        translation_on = subtitles_on = text_only = True
        edit_mode = wrist_edit_mode = False

    _state = _St()
    _restart_pending = False
    _devices_applying = False

    def _get_font_size(self):
        return 27

    def _get_tts_gain(self):
        return 1.0

    def _get_provider(self):
        return "qwen"

    def _get_auto_launch(self):
        return True


def _buttons_of(widgets):
    return {w.name: w.rect for w in widgets
            if w.kind == "button" and w.page == "main"}


def test_wrist_table_matches_snapshot():
    got = _buttons_of(wrist_ui._build_widgets())
    assert got == WRIST_BUTTONS


def test_dashboard_table_matches_snapshot():
    got = _buttons_of(dashboard_panel._build_widgets())
    assert got == DASH_BUTTONS


def test_hit_test_centers():
    panel = _PermissivePanel()
    for widgets, snapshot in (
            (wrist_ui._build_widgets(), WRIST_BUTTONS),
            (dashboard_panel._build_widgets(), DASH_BUTTONS)):
        for name, (x0, y0, x1, y1) in snapshot.items():
            hit = widget_at(widgets, panel, (x0 + x1) / 2, (y0 + y1) / 2)
            assert hit == name, (name, hit)


def test_disabled_widgets_are_dead_to_hits():
    panel = _PermissivePanel()
    panel._devices_applying = True
    widgets = dashboard_panel._build_widgets()
    x0, y0, x1, y1 = DASH_BUTTONS["mic_prev"]
    assert widget_at(widgets, panel, (x0 + x1) / 2, (y0 + y1) / 2) is None


if __name__ == "__main__":
    test_wrist_table_matches_snapshot()
    test_dashboard_table_matches_snapshot()
    test_hit_test_centers()
    test_disabled_widgets_are_dead_to_hits()
    print("test_vr_button_table: OK")
