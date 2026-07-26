"""Render both VR panels' textures headlessly (no OpenVR/GL): catches
NameErrors, layout crashes, and missing i18n keys across languages/states."""
import sys

import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vrclt.state import AppState
from vrclt.vr.wrist_ui import WristPanel, TEX_W as W_W, TEX_H as W_H
from vrclt.vr.dashboard_panel import DashboardPanel, TEX_W as D_W, TEX_H as D_H


def main():
    st = AppState()
    wrist = WristPanel(st, ["en", "ko", "ja"], inbound_languages=["ko", "en"])
    dash = DashboardPanel(st, ["en", "ko", "ja"], inbound_languages=["ko", "en"],
                          get_provider=lambda: "qwen")
    dash_gem = DashboardPanel(st, ["en"], get_provider=lambda: "gemini")

    for lang in ("en", "ko", "ja", "zh"):
        st.ui_lang = lang
        for status in ((True, "status_running", ""),
                       (False, "status_failed", "boom"),
                       (False, "status_stopped", "")):
            img = wrist._render(status, False)
            assert img.size == (W_W, W_H)
            img = dash._render(status)
            assert img.size == (D_W, D_H)
            img = dash_gem._render(status)
            assert img.size == (D_W, D_H)

    # state variations: edit modes, toggles off, text-only
    st.ui_lang = "ko"
    st.edit_mode = True
    st.wrist_edit_mode = True
    st.translation_on = False
    st.subtitles_on = False
    img = wrist._render((True, "status_running", ""), True)
    assert img.size == (W_W, W_H)
    img = dash._render((True, "status_running", ""))
    assert img.size == (D_W, D_H)

    # clamp dimming paths (font at min => minus disabled)
    wrist2 = WristPanel(st, ["en"], get_font_size=lambda: 18)
    img = wrist2._render((True, "status_running", ""), False)
    dash2 = DashboardPanel(st, ["en"], get_font_size=lambda: 72,
                           get_tts_gain=lambda: 2.0)
    img = dash2._render((True, "status_running", ""))

    # hover/pressed fills actually change pixels
    st2 = AppState()
    w3 = WristPanel(st2, ["en"])
    base = w3._render((True, "status_running", ""), False)
    w3._engaged = True
    w3._hover = "toggle"
    hovered = w3._render((True, "status_running", ""), False)
    assert list(base.getdata()) != list(hovered.getdata()), "hover render identical"
    w3._pressed_name = "uilang"
    pressed = w3._render((True, "status_running", ""), False)
    assert list(hovered.getdata()) != list(pressed.getdata()), "pressed render identical"

    # restart pending: set on click, cleared after Starting -> Running
    calls = []
    w4 = WristPanel(st2, ["en"], on_restart=lambda: calls.append(1))
    w4._restart()
    assert w4._restart_pending and calls == [1]
    w4._restart()  # ignored while pending
    assert calls == [1]
    w4._update_restart_pending((False, "status_starting", ""), 1.0)
    assert w4._restart_pending
    w4._update_restart_pending((True, "status_running", ""), 2.0)
    assert not w4._restart_pending
    # timeout path
    w4._restart()
    w4._update_restart_pending((True, "status_running", ""), 100.0)
    assert w4._restart_pending  # no transition seen yet, not timed out (started ~now)
    w4._restart_started = 0.0
    w4._update_restart_pending((True, "status_running", ""), 31.0)
    assert not w4._restart_pending

    # picker pages render on both panels, all languages
    st3 = AppState()
    many = ["ja", "en", "ko", "zh-Hans", "zh-Hant", "yue", "es", "ru", "fr",
            "de", "it", "pt", "tr", "vi", "th", "id", "hi", "ar", "pl", "nl",
            "sv", "uk"]  # 22 -> multiple pages on both grids
    w5 = WristPanel(st3, many, inbound_languages=many)
    d5 = DashboardPanel(st3, many, inbound_languages=many)
    for lang in ("en", "ko", "ja", "zh"):
        st3.ui_lang = lang
        for kind in ("out", "in"):
            for panel in (w5, d5):
                panel._open_picker(kind)
                img = (panel._render((True, "status_running", ""), False)
                       if panel is w5 else panel._render((True, "status_running", "")))
                panel._flip_picker_page(1)
                img = (panel._render((True, "status_running", ""), False)
                       if panel is w5 else panel._render((True, "status_running", "")))
                panel._close_picker()
    # subtitle overlay: armed pill phases + both-corner resize anchors
    import numpy as np
    from vrclt.subtitles import SubtitleStore
    from vrclt.vr.subtitle_overlay import SubtitlePanel, MAX_TEX_H, TEX_W as S_W

    st4 = AppState()
    store = SubtitleStore()
    sp = SubtitlePanel(store, st4)
    st4.subtitles_on = True

    # empty store + subtitles ON -> armed phase 0, has_content True
    has, sig, finals, partial, edit, phase = sp._render_state()
    assert has and phase == 0, (has, phase)
    img = sp._render(finals, partial, edit, phase)
    assert img.size == (S_W, MAX_TEX_H)
    # phase transitions via backdated timer; sig changes with the phase
    sp._armed_since -= 7.0
    _, sig1, *_rest, phase1 = sp._render_state()
    assert phase1 == 1 and sig1 != sig
    sp._render(finals, partial, edit, phase1)
    sp._armed_since -= 6.0
    *_ignored, phase2 = sp._render_state()
    assert phase2 == 2
    sp._render(finals, partial, edit, phase2)
    # content appears -> pill state resets
    store.add_final("hello", "안녕", "ko")
    has, _sig, finals, partial, edit, phase = sp._render_state()
    assert has and phase is None and sp._armed_since is None
    sp._render(finals, partial, edit, phase)
    # subtitles OFF -> hidden again
    st4.subtitles_on = False
    has, *_r = sp._render_state()
    assert not has

    # edit-mode placeholder renders with both corner brackets, incl. hover
    st4.subtitles_on = True
    st4.edit_mode = True
    sp._dragging = False
    sp._hover_corner = (-1, -1)
    has, _sig, finals, partial, edit, phase = sp._render_state()
    assert has and edit and phase is None
    sp._render(finals, partial, edit, phase)

    # resize anchors: cx=+1 keeps the original top-left anchor; cx=-1 mirrors
    sp._overlay_mat = np.identity(4)
    sp._width_m, sp._height_m = 0.9, 0.225
    sp._start_resize((1, -1))
    assert np.allclose(sp._resize_anchor[:3], [-0.45, 0.1125, 0.0])
    sp._start_resize((-1, -1))
    assert np.allclose(sp._resize_anchor[:3], [0.45, 0.1125, 0.0])

    print("smoke_vr_render: OK")


if __name__ == "__main__":
    main()
