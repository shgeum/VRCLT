"""VR controls: reachable targets, page isolation, and language navigation."""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vrclt.state import AppState
from vrclt.vr import dashboard_panel, wrist_ui
from vrclt.vr.button_table import widget_at, is_enabled


def test_hit_geometry_and_page_isolation():
    for cls, size, pages in ((wrist_ui.WristPanel, (640, 432), ("main", "settings")),
                             (dashboard_panel.DashboardPanel, (1024, 950), ("main", "audio", "layout"))):
        font_changes = []
        panel = cls(AppState(), ["ja", "en", "ko"], get_provider=lambda: "soniox",
                    on_font_size=font_changes.append)
        try:
            for page in pages:
                panel._page = page
                widgets = panel._active_widgets()
                buttons = [w for w in widgets if w.kind == "button" and w.page == page]
                assert buttons
                for w in buttons:
                    x0, y0, x1, y1 = w.rect
                    assert 0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1], w.name
                    assert x1 - x0 >= 60 and y1 - y0 >= 48, w.name
                    hit = widget_at(widgets, panel, (x0+x1)/2, (y0+y1)/2, page)
                    assert hit == (w.name if is_enabled(w, panel) else None), (page, w.name, hit)
                    for other in buttons:
                        if other is w:
                            continue
                        a, b, c, d = other.rect
                        assert min(x1,c) <= max(x0,a) or min(y1,d) <= max(y0,b), (w.name, other.name)
            panel._page = "main"
            assert {w.name for w in panel._active_widgets()} >= {"toggle", "sub_toggle", "lang", "sub_lang"}
            panel._on_click("font_minus")
            assert font_changes == []  # settings actions are unreachable on the live page
        finally:
            panel.detach()


def test_disabled_widgets_are_dead_to_hits():
    panel = dashboard_panel.DashboardPanel(AppState(), ["en"])
    panel._devices_applying = True
    panel._page = "audio"
    x0, y0, x1, y1 = dashboard_panel.BTN_MIC_PREV
    assert panel._button_at(((x0+x1)/2, (y0+y1)/2)) is None
    panel._page = "main"
    x0, y0, x1, y1 = dashboard_panel.BTN_SPEAKER_CONTEXT
    assert panel._button_at(((x0+x1)/2, (y0+y1)/2)) is None
    panel.detach()


def test_lang_grid_widgets():
    from vrclt.vr.button_table import lang_grid_widgets, lang_page_count

    langs = ["ja", "en", "ko", "zh-Hans", "zh-Hant", "yue", "es", "ru",
             "fr", "de", "it", "pt", "tr"]  # 13 -> 2 pages at 3x4
    assert lang_page_count(langs, 3, 4) == 2
    page0 = lang_grid_widgets(page="lang_out", languages=langs, page_idx=0,
                              area=(16, 86, 624, 630), cols=3, rows=4,
                              name_prefix="pick_out",
                              current_of=lambda p: "ko",
                              accent=(46, 160, 67, 255))
    assert len(page0) == 12
    assert page0[0].name == "pick_out:ja"
    page1 = lang_grid_widgets(page="lang_out", languages=langs, page_idx=1,
                              area=(16, 86, 624, 630), cols=3, rows=4,
                              name_prefix="pick_out",
                              current_of=lambda p: "ko",
                              accent=(46, 160, 67, 255))
    assert [w.name for w in page1] == ["pick_out:tr"]
    # cells stay inside the area and don't overlap row/col neighbours
    for w in page0:
        x0, y0, x1, y1 = w.rect
        assert 16 <= x0 < x1 <= 624 and 86 <= y0 < y1 <= 630
    # current language cell uses the accent fill
    ko = next(w for w in page0 if w.name == "pick_out:ko")
    assert ko.fill(None) == (46, 160, 67, 255)
    assert page0[0].fill(None) != (46, 160, 67, 255)


def test_wrist_picker_flow():
    from vrclt.state import AppState
    from vrclt.vr.wrist_ui import WristPanel

    st = AppState()
    p = WristPanel(st, ["ja", "en", "ko"], inbound_languages=["ko", "en"])
    p._open_picker("out")
    assert p._page == "lang_out"
    names = {w.name for w in p._active_widgets()}
    assert "pick_out:ko" in names and "picker_close" in names
    p._on_click("pick_out:ko")
    assert st.target_language == "ko" and p._page == "main"
    p._open_picker("in")
    p._on_click("picker_close")
    assert p._page == "main"
    p.detach()


def test_wrist_physical_ray_hits_main_controls():
    """The shortened texture must agree with the physical panel's ray mapping.

    Aim the tilted controller at each button centre through the real watch
    transform, at both the configured and legacy wrist widths.
    """
    assert (wrist_ui.TEX_W, wrist_ui.TEX_H) == (640, 432)
    expected = {"toggle", "sub_toggle", "lang", "sub_lang", "mode_voice",
                "mode_text", "restart", "nav_live", "nav_settings"}
    for width in (0.14, 0.16):
        state = AppState()
        panel = wrist_ui.WristPanel(state, ["en", "ko"], width_m=width)
        try:
            assert np.isclose(panel._height_m, width * 432 / 640)
            panel._overlay_mat = panel._watch_matrix()
            panel._overlay_mat_inv = np.linalg.inv(panel._overlay_mat)
            wrist_pose = np.identity(4)
            wrist_pose[:3, 3] = (0.2, 1.3, -0.4)
            buttons = [w for w in panel._active_widgets()
                       if w.kind == "button" and w.page == "main"]
            assert {w.name for w in buttons} == expected
            for button in buttons:
                # Give each explicit mode a reason to be selectable if the
                # implementation dims the currently selected choice.
                state.text_only = button.name == "mode_voice"
                x0, y0, x1, y1 = button.rect
                pixel_x, pixel_y = (x0 + x1) / 2, (y0 + y1) / 2
                local_x = (pixel_x / 640 - 0.5) * width
                local_y = (0.5 - pixel_y / 432) * panel._height_m
                ray_pose = np.identity(4)
                ray_pose[:3, 3] = (local_x, local_y, 0.25)
                controller_pose = (wrist_pose @ panel._overlay_mat @ ray_pose
                                   @ np.linalg.inv(panel._pointer_mat))
                hit, on_panel, point = panel._ray_hit(wrist_pose, controller_pose)
                assert on_panel and hit == button.name, (width, button.name, hit)
                assert np.allclose(point, (local_x, local_y))
        finally:
            panel.detach()


if __name__ == "__main__":
    test_hit_geometry_and_page_isolation()
    test_disabled_widgets_are_dead_to_hits()
    test_lang_grid_widgets()
    test_wrist_picker_flow()
    test_wrist_physical_ray_hits_main_controls()
    print("test_vr_button_table: OK")
