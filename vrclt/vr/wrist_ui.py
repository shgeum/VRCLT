"""XSOverlay-style wrist menu panel (component of the VR render thread).

Interaction (no SteamVR input capture - the game keeps full control):
- gaze gate: panel fades opaque + our own laser appears only while LOOKING
  at the watch up close
- TRIGGER pressed AND released on the same button: click (press/release
  matching, like the dashboard panel - sweeping through with the trigger
  held no longer misfires); GRIP anywhere on the panel: grab & move
  (release saves; Reset button resets)
- the laser points 'pointer_tilt_deg' below the controller's raw forward,
  matching the natural pistol-grip pointing direction

Textures are persistent OpenGL textures (see vr/render.py for why). The GL
texture is updated in place (glTexSubImage2D), so re-rendering on hover /
pressed changes cannot flicker - renders happen only when the hover target
or pressed widget changes, never per-frame.
"""
import logging
import math
import threading
import time

import numpy as np
from PIL import Image, ImageDraw

from ..config import APPDATA_DIR, OVERLAY_FONT_MAX, OVERLAY_FONT_MIN
from ..resources import bundled_font, resolve_font_path
from ..state import AppState
from ..i18n import tr, LANGS as UI_LANGS, UI_LANG_LABELS
from .button_table import Widget, draw_page, is_enabled, widget_at
from .font_fallback import load_fallback_font
from .panel_common import (
    COL_BG, COL_BTN, COL_DIM, COL_DRAG, COL_INSET, COL_OFF, COL_ON,
    COL_SUB_ON, COL_TEXT,
    coerce_transform, create_overlay_set, cycle, draw_fit_text, haptic,
    language_label, laser_base, load_saved_transform, np_to_hmd34,
    pointer_matrix, pose_to_np, ray_plane_hit, save_transform,
    setup_pointer_overlays, status_dot_color, translate,
)
from .render import GlTexture, flip_bounds

log = logging.getLogger(__name__)

TEX_W, TEX_H = 640, 648
MAX_RAY_M = 1.2

GAZE_ON_DEG = 22.0
GAZE_OFF_DEG = 35.0
GAZE_DIST_M = 0.95

TRANSFORM_PATH = APPDATA_DIR / "wrist_transform.json"

BTN_UILANG = (108, 14, 196, 66)      # cycles the UI display language
BTN_TEXT_ONLY = (204, 14, 336, 66)
BTN_EDIT = (344, 14, 432, 66)
BTN_SUB_EDIT = (440, 14, 528, 66)
BTN_RESET = (536, 14, 624, 66)
BTN_TOGGLE = (16, 86, 306, 302)
BTN_PREV = (322, 86, 388, 302)
BTN_LANG = (388, 86, 556, 302)       # label only
BTN_NEXT = (556, 86, 624, 302)
BTN_SUB_TOGGLE = (16, 322, 306, 538)
BTN_SUB_PREV = (322, 322, 388, 538)
BTN_SUB_LANG = (388, 322, 556, 538)  # label only
BTN_SUB_NEXT = (556, 322, 624, 538)
# bottom row: restart + subtitle font size (mirrors the dashboard panel)
BTN_RESTART = (16, 554, 200, 630)
BTN_FONT_MINUS = (216, 554, 296, 630)
LBL_FONT_SIZE = (304, 554, 404, 630)   # label only
BTN_FONT_PLUS = (412, 554, 492, 630)
LBL_STATUS = (508, 554, 624, 630)      # label only: non-nominal status text

CURSOR_SIZE_M = 0.016


def _center(rect) -> tuple[int, int]:
    return (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2


def _arrow_draw(glyph: str):
    def draw(panel, d, w, lang):
        col = COL_TEXT if is_enabled(w, panel) else COL_DIM
        panel._font_mid.draw(d, _center(w.rect), glyph, fill=col, anchor="mm")
    return draw


def _toggle_draw(on_key: str, off_key: str, caption_key: str, is_on):
    """The two big toggles: state line on top, pipeline caption below."""
    def draw(panel, d, w, lang):
        x0, y0, x1, y1 = w.rect
        cy = (y0 + y1) // 2
        draw_fit_text(d, (x0 + 10, y0 + 36, x1 - 10, cy + 16),
                      tr(lang, on_key if is_on(panel) else off_key),
                      fonts=(panel._font_mid, panel._font_small, panel._font_tiny),
                      max_lines=1, pad_x=0, pad_y=0)
        draw_fit_text(d, (x0 + 10, cy + 18, x1 - 10, y1 - 22),
                      tr(lang, caption_key),
                      fonts=(panel._font_small, panel._font_tiny),
                      max_lines=1, pad_x=0, pad_y=0, line_spacing=0)
    return draw


def _lang_label_draw(code_of, caption_key: str):
    """Inset language name + dim caption (arrows are separate widgets)."""
    def draw(panel, d, w, lang):
        box = w.rect
        draw_fit_text(d, (box[0] + 4, box[1] + 20, box[2] - 4, box[3] - 54),
                      language_label(code_of(panel)),
                      fonts=(panel._font_big, panel._font_mid,
                             panel._font_small, panel._font_tiny),
                      max_lines=1, pad_x=2, pad_y=2)
        draw_fit_text(d, (box[0] + 4, box[3] - 54, box[2] - 4, box[3] - 8),
                      tr(lang, caption_key),
                      fonts=(panel._font_tiny,), fill=COL_DIM, max_lines=1,
                      pad_x=2, pad_y=1, line_spacing=0)
    return draw


def _font_size_draw(panel, d, w, lang):
    box = w.rect
    draw_fit_text(d, (box[0], box[1] + 6, box[2], box[1] + 44),
                  str(int(panel._get_font_size())),
                  fonts=(panel._font_small,), max_lines=1, pad_x=4, pad_y=2)
    draw_fit_text(d, (box[0], box[3] - 30, box[2], box[3] - 6),
                  tr(lang, "dash_font_size"),
                  fonts=(panel._font_tiny,), fill=COL_DIM, max_lines=1,
                  pad_x=2, pad_y=1, line_spacing=0)


def _build_widgets() -> tuple:
    """Main-page widget table: single source for draw AND hit-test rects."""
    return (
        Widget("uilang", BTN_UILANG,
               label=lambda p, lang: UI_LANG_LABELS.get(lang, lang)),
        Widget("text_only", BTN_TEXT_ONLY,
               fill=lambda p: COL_SUB_ON if p._state.text_only else COL_BTN,
               label=lambda p, lang: tr(lang, "btn_text_only_on"
                                        if p._state.text_only else "btn_text_only_off")),
        Widget("edit", BTN_EDIT,
               fill=lambda p: COL_DRAG if p._state.wrist_edit_mode else COL_BTN,
               label=lambda p, lang: tr(lang, "wrist_move")),
        Widget("sub_edit", BTN_SUB_EDIT,
               fill=lambda p: COL_DRAG if p._state.edit_mode else COL_BTN,
               label=lambda p, lang: tr(lang, "sub_move")),
        # dual-purpose by design: resets whichever placement is being edited;
        # the dynamic label + tint make the active target visible
        Widget("reset", BTN_RESET,
               fill=lambda p: COL_DRAG if p._state.edit_mode else COL_BTN,
               label=lambda p, lang: tr(lang, "reset_sub_pos"
                                        if p._state.edit_mode else "reset_watch_pos")),
        Widget("toggle", BTN_TOGGLE, radius=18,
               fill=lambda p: COL_ON if p._state.translation_on else COL_OFF,
               draw=_toggle_draw("btn_trans_on", "btn_trans_off", "my_to_other",
                                 lambda p: p._state.translation_on)),
        Widget("prev", BTN_PREV, radius=16, draw=_arrow_draw("◀")),
        Widget("lang", BTN_LANG, kind="label", radius=16,
               fill=lambda p: COL_INSET,
               draw=_lang_label_draw(lambda p: p._state.target_language,
                                     "out_lang")),
        Widget("next", BTN_NEXT, radius=16, draw=_arrow_draw("▶")),
        Widget("sub_toggle", BTN_SUB_TOGGLE, radius=18,
               fill=lambda p: COL_SUB_ON if p._state.subtitles_on else COL_BTN,
               draw=_toggle_draw("btn_sub_on", "btn_sub_off", "other_to_sub",
                                 lambda p: p._state.subtitles_on)),
        Widget("sub_prev", BTN_SUB_PREV, radius=16, draw=_arrow_draw("◀")),
        Widget("sub_lang", BTN_SUB_LANG, kind="label", radius=16,
               fill=lambda p: COL_INSET,
               draw=_lang_label_draw(lambda p: p._state.inbound_language,
                                     "sub_lang")),
        Widget("sub_next", BTN_SUB_NEXT, radius=16, draw=_arrow_draw("▶")),
        Widget("restart", BTN_RESTART,
               enabled=lambda p: not p._restart_pending,
               label=lambda p, lang: tr(lang, "btn_restarting"
                                        if p._restart_pending
                                        else "btn_restart_runtime")),
        Widget("font_minus", BTN_FONT_MINUS,
               enabled=lambda p: int(p._get_font_size()) > OVERLAY_FONT_MIN,
               draw=_arrow_draw("−")),
        Widget("font_size", LBL_FONT_SIZE, kind="label",
               fill=lambda p: COL_INSET, draw=_font_size_draw),
        Widget("font_plus", BTN_FONT_PLUS,
               enabled=lambda p: int(p._get_font_size()) < OVERLAY_FONT_MAX,
               draw=_arrow_draw("+")),
    )


class WristPanel:
    def __init__(self, state: AppState, languages: list[str], *,
                 inbound_languages: list[str] | None = None,
                 hand: str = "left", width_m: float = 0.16,
                 offset=(0.0, 0.02, 0.12), tilt_deg: float = 0.0,
                 roll_deg: float | None = None,
                 transform=None,
                 pointer_tilt_deg: float = 50.0,
                 font_path: str = bundled_font("NotoSansCJKkr-Bold.otf"),
                 on_text_only_toggle=lambda enabled: None,
                 on_transform_changed=lambda matrix, reset=False: None,
                 get_status_info=lambda: (False, "status_stopped", ""),
                 on_restart=lambda: None,
                 on_font_size=lambda size: None,
                 get_font_size=lambda: 27):
        self._state = state
        self._languages = languages or ["en"]
        self._inbound_languages = inbound_languages or ["ko", "en"]
        self._hand = hand
        self._width_m = width_m
        self._height_m = width_m * TEX_H / TEX_W
        self._offset = tuple(offset)
        self._tilt_deg = tilt_deg
        self._roll_deg = roll_deg if roll_deg is not None else (90.0 if hand == "left" else -90.0)
        self._configured_transform = coerce_transform(transform, "wrist panel")
        self._on_transform_changed = on_transform_changed
        self._pointer_mat = pointer_matrix(pointer_tilt_deg)
        self._get_status_info = get_status_info
        self._on_text_only_toggle = on_text_only_toggle
        self._on_restart = on_restart
        self._on_font_size = on_font_size
        self._get_font_size = get_font_size
        font_path = resolve_font_path(font_path, "NotoSansCJKkr-Bold.otf")
        self._font_big = load_fallback_font(font_path, 54, bold=True)
        self._font_mid = load_fallback_font(font_path, 36, bold=True)
        self._font_small = load_fallback_font(font_path, 24, bold=True)
        self._font_tiny = load_fallback_font(font_path, 18, bold=True)

        self._widgets = _build_widgets()
        self._page = "main"
        self._hover = None
        self._pressed_name = None
        self._engaged = False
        self._dragging = False
        self._restart_pending = False
        self._restart_started = 0.0
        self._restart_seen_transition = False
        self._click_handlers = {
            "toggle": self._toggle_translation,
            "sub_toggle": self._toggle_subtitles,
            "prev": lambda: self._cycle_out_lang(-1),
            "next": lambda: self._cycle_out_lang(1),
            "sub_prev": lambda: self._cycle_in_lang(-1),
            "sub_next": lambda: self._cycle_in_lang(1),
            "edit": self._toggle_wrist_edit,
            "sub_edit": self._toggle_sub_edit,
            "uilang": self._cycle_ui_lang,
            "text_only": self._toggle_text_only,
            "restart": self._restart,
            "font_minus": lambda: self._bump_font(-2),
            "font_plus": lambda: self._bump_font(2),
            "reset": self._reset,
        }

        self._dirty = threading.Event()
        self._dirty.set()
        self._reset_requested = False
        state.subscribe(self._on_state)

        self._h = self._h_laser = self._h_cursor = None
        self._tex = None

    def _on_state(self, field: str, _value) -> None:
        if field == "reset_positions":
            self._reset_requested = True
        self._dirty.set()

    def detach(self) -> None:
        """Drop the AppState subscription (the state outlives panels)."""
        self._state.unsubscribe(self._on_state)

    # ---------------- component lifecycle ----------------
    def setup(self, ctx) -> bool:
        openvr, ovl = ctx.openvr, ctx.ovl
        created = create_overlay_set(ovl, (("vrclt.wrist", "vrclt wrist menu"),
                                           ("vrclt.laser", "vrclt laser"),
                                           ("vrclt.cursor", "vrclt cursor")), "wrist panel")
        if created is None:
            return False
        self._h, self._h_laser, self._h_cursor = created

        bounds = flip_bounds(openvr)
        ovl.setOverlayWidthInMeters(self._h, self._width_m)
        ovl.setOverlayAlpha(self._h, 0.55)
        ovl.setOverlayTextureBounds(self._h, bounds)
        self._tex = GlTexture(TEX_W, TEX_H)

        self._laser_tex, self._cursor_tex = setup_pointer_overlays(
            openvr, ovl, self._h_laser, self._h_cursor,
            laser_sort=200, cursor_sort=201, cursor_size_m=CURSOR_SIZE_M)

        ovl.showOverlay(self._h)
        log.info("wrist panel ready (hand=%s, GL texture)", self._hand)

        self._wrist_role = openvr.TrackedControllerRole_LeftHand if self._hand == "left" \
            else openvr.TrackedControllerRole_RightHand
        self._finger_role = openvr.TrackedControllerRole_RightHand if self._hand == "left" \
            else openvr.TrackedControllerRole_LeftHand
        self._trigger_mask = 1 << int(openvr.k_EButton_SteamVR_Trigger)
        self._grip_mask = 1 << int(openvr.k_EButton_Grip)
        self._invalid = openvr.k_unTrackedDeviceIndexInvalid

        self._overlay_mat = self._load_transform()
        self._overlay_mat_inv = np.linalg.inv(self._overlay_mat)
        if self._configured_transform is not None or TRANSFORM_PATH.exists():
            self._on_transform_changed(self._overlay_mat, False)
        self._wrist_idx = self._finger_idx = self._invalid
        self._attached_to = self._invalid
        self._laser_attached_to = self._invalid
        self._last_role_check = 0.0
        self._hover = None
        self._engaged = False
        self._laser_visible = False
        self._cursor_visible = False
        self._dragging = False
        self._drag_offset = None
        self._prev_trigger = True   # require a fresh press after start
        self._prev_grip = True
        self._input_ok_logged = False
        self._last_status = None
        self._dirty.set()
        return True

    def teardown(self, ctx) -> None:
        ovl = ctx.ovl
        for h in (self._h, self._h_laser, self._h_cursor):
            if h is not None:
                try:
                    ovl.destroyOverlay(h)
                except Exception:
                    pass
        self._h = self._h_laser = self._h_cursor = None
        for tex in (self._tex, getattr(self, "_laser_tex", None), getattr(self, "_cursor_tex", None)):
            if tex is not None:
                tex.delete()
        self._tex = None

    # ---------------- per-frame ----------------
    def tick(self, ctx, now: float) -> None:
        openvr, ovl, vrsys, poses = ctx.openvr, ctx.ovl, ctx.vrsys, ctx.poses

        if (now - self._last_role_check) > 1.0:
            self._last_role_check = now
            self._wrist_idx = vrsys.getTrackedDeviceIndexForControllerRole(self._wrist_role)
            self._finger_idx = vrsys.getTrackedDeviceIndexForControllerRole(self._finger_role)
            if self._wrist_idx != self._invalid and self._wrist_idx != self._attached_to:
                ovl.setOverlayTransformTrackedDeviceRelative(
                    self._h, self._wrist_idx, np_to_hmd34(openvr, self._overlay_mat))
                self._attached_to = self._wrist_idx
                log.info("wrist panel attached to controller %d", self._wrist_idx)
            if self._finger_idx != self._invalid and self._finger_idx != self._laser_attached_to:
                ovl.setOverlayTransformTrackedDeviceRelative(
                    self._h_laser, self._finger_idx,
                    np_to_hmd34(openvr, self._pointer_mat @ laser_base()))
                self._laser_attached_to = self._finger_idx
            if self._finger_idx == self._invalid:
                # pointer controller gone: drop stale edge/hover state so a
                # held button isn't remembered across the gap
                self._prev_trigger = self._prev_grip = True
                self._hover = None
                self._pressed_name = None
            # status poll shares the 1 Hz gate (the dashboard panel already
            # throttles the same call; 30 Hz was needless render-thread work)
            status = self._get_status_info()
            if status != self._last_status:
                self._last_status = status
                self._dirty.set()
            self._update_restart_pending(status, now)
        status = self._last_status or (False, "status_stopped", "")

        new_hover = None
        if self._wrist_idx != self._invalid:
            hp = poses[openvr.k_unTrackedDeviceIndex_Hmd]
            wp = poses[self._wrist_idx]
            poses_ok = hp.bPoseIsValid and wp.bPoseIsValid

            if poses_ok:
                self._update_gaze(ovl, hp, wp)

            if self._engaged and poses_ok and self._finger_idx != self._invalid:
                fp = poses[self._finger_idx]
                if fp.bPoseIsValid:
                    w4 = pose_to_np(wp)
                    f4 = pose_to_np(fp)
                    new_hover, on_panel, hit_xy = self._ray_hit(w4, f4)

                    trigger = grip = False
                    try:
                        ok, cs = vrsys.getControllerState(self._finger_idx)
                        if ok:
                            if not self._input_ok_logged:
                                self._input_ok_logged = True
                                log.info("wrist panel: controller input OK")
                            trigger = bool(cs.ulButtonPressed & self._trigger_mask)
                            grip = bool(cs.ulButtonPressed & self._grip_mask)
                    except Exception:
                        pass

                    # The wrist panel has its own move mode so subtitle
                    # placement is not affected by watch adjustments.
                    if grip and not self._prev_grip and on_panel and \
                            not self._dragging and self._state.wrist_edit_mode:
                        self._drag_offset = np.linalg.inv(f4) @ w4 @ self._overlay_mat
                        self._dragging = True
                        haptic(vrsys, openvr, self._finger_idx, 2000)
                        self._dirty.set()
                        log.info("wrist panel grabbed")
                    if self._dragging:
                        if grip and self._drag_offset is not None:
                            self._overlay_mat = np.linalg.inv(w4) @ f4 @ self._drag_offset
                            ovl.setOverlayTransformTrackedDeviceRelative(
                                self._h, self._wrist_idx,
                                np_to_hmd34(openvr, self._overlay_mat))
                        else:
                            self._dragging = False
                            self._overlay_mat_inv = np.linalg.inv(self._overlay_mat)
                            save_transform(self._overlay_mat, TRANSFORM_PATH, "wrist panel")
                            self._on_transform_changed(self._overlay_mat, False)
                            haptic(vrsys, openvr, self._finger_idx, 3000)
                            self._dirty.set()
                            log.info("wrist panel placed (saved)")
                        new_hover = None

                    if not self._dragging:
                        # press/release matching: the click fires only when
                        # the trigger is released on the widget it went down on
                        if trigger and not self._prev_trigger and \
                                new_hover is not None:
                            self._pressed_name = new_hover
                            haptic(vrsys, openvr, self._finger_idx, 1500)
                            self._dirty.set()
                        elif not trigger and self._prev_trigger and \
                                self._pressed_name is not None:
                            if new_hover == self._pressed_name:
                                self._on_click(self._pressed_name)
                                haptic(vrsys, openvr, self._finger_idx, 3000)
                            self._pressed_name = None
                            self._dirty.set()

                    self._prev_trigger, self._prev_grip = trigger, grip

                    if hit_xy is not None:
                        cur = self._overlay_mat @ translate(hit_xy[0], hit_xy[1], 0.004)
                        ovl.setOverlayTransformTrackedDeviceRelative(
                            self._h_cursor, self._wrist_idx, np_to_hmd34(openvr, cur))
                        if not self._cursor_visible:
                            ovl.showOverlay(self._h_cursor)
                            self._cursor_visible = True
                    elif self._cursor_visible:
                        ovl.hideOverlay(self._h_cursor)
                        self._cursor_visible = False

        want_laser = (self._engaged or self._dragging) and self._finger_idx != self._invalid
        if want_laser != self._laser_visible:
            self._laser_visible = want_laser
            (ovl.showOverlay if want_laser else ovl.hideOverlay)(self._h_laser)
        if not self._engaged and self._cursor_visible:
            ovl.hideOverlay(self._h_cursor)
            self._cursor_visible = False

        if new_hover != self._hover:
            if new_hover is not None:
                haptic(vrsys, openvr, self._finger_idx, 600)
            self._hover = new_hover
            # renders happen only on target change (bounded by pointer
            # travel), and the GL texture updates in place - no flicker
            if not self._dragging:
                self._dirty.set()

        if self._reset_requested and not self._dragging:
            self._reset_requested = False
            self._overlay_mat = self._default_watch_matrix()
            self._overlay_mat_inv = np.linalg.inv(self._overlay_mat)
            if self._attached_to != self._invalid:
                ovl.setOverlayTransformTrackedDeviceRelative(
                    self._h, self._attached_to, np_to_hmd34(openvr, self._overlay_mat))
            try:
                TRANSFORM_PATH.unlink(missing_ok=True)
            except OSError:
                pass
            self._on_transform_changed(self._overlay_mat, True)
            log.info("wrist panel position reset to defaults")

        if self._dirty.is_set():
            self._dirty.clear()
            self._tex.update(self._render(status, self._dragging))
            ovl.setOverlayTexture(self._h, self._tex.vr_texture(openvr))

    # ---------------- gaze ----------------
    def _update_gaze(self, ovl, hp, wp) -> None:
        h4 = pose_to_np(hp)
        w4 = pose_to_np(wp)
        center = (w4 @ self._overlay_mat @ np.array([0.0, 0.0, 0.0, 1.0]))[:3]
        eye = h4[:3, 3]
        fwd = -h4[:3, 2]
        v = center - eye
        dist = float(np.linalg.norm(v))
        ang = 180.0
        if dist > 1e-6:
            cosang = float(np.dot(fwd, v / dist))
            ang = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
        if self._dragging:
            want = True
        elif self._engaged:
            want = ang < GAZE_OFF_DEG and dist < GAZE_DIST_M * 1.3
        else:
            want = ang < GAZE_ON_DEG and dist < GAZE_DIST_M
        if want != self._engaged:
            self._engaged = want
            ovl.setOverlayAlpha(self._h, 0.96 if want else 0.55)
            if not want:
                self._hover = None
                self._pressed_name = None
                # edges are only updated while engaged; require a fresh
                # press after re-engaging instead of trusting stale state
                self._prev_trigger = self._prev_grip = True

    # ---------------- interaction ----------------
    def _ray_hit(self, w4: np.ndarray, f4: np.ndarray):
        to_overlay = self._overlay_mat_inv @ np.linalg.inv(w4) @ f4 @ self._pointer_mat
        xy = ray_plane_hit(to_overlay, MAX_RAY_M)
        if xy is None:
            return None, False, None
        x, y = xy
        half_w, half_h = self._width_m / 2, self._height_m / 2
        if abs(x) > half_w + 0.015 or abs(y) > half_h + 0.015:
            return None, False, None
        u = (x + half_w) / self._width_m
        v = 1.0 - (y + half_h) / self._height_m
        px, py = u * TEX_W, v * TEX_H
        return widget_at(self._widgets, self, px, py, self._page), True, (x, y)

    def _on_click(self, button: str) -> None:
        log.info("wrist panel click: %s", button)
        handler = self._click_handlers.get(button)
        if handler is not None:
            handler()

    # ---------------- click handlers ----------------
    def _toggle_translation(self) -> None:
        self._state.translation_on = not self._state.translation_on

    def _toggle_subtitles(self) -> None:
        self._state.subtitles_on = not self._state.subtitles_on

    def _cycle_out_lang(self, step: int) -> None:
        st = self._state
        st.target_language = cycle(self._languages, st.target_language, step)

    def _cycle_in_lang(self, step: int) -> None:
        st = self._state
        st.inbound_language = cycle(self._inbound_languages,
                                    st.inbound_language, step)

    def _toggle_wrist_edit(self) -> None:
        self._state.wrist_edit_mode = not self._state.wrist_edit_mode

    def _toggle_sub_edit(self) -> None:
        self._state.edit_mode = not self._state.edit_mode

    def _cycle_ui_lang(self) -> None:
        self._state.ui_lang = cycle(UI_LANGS, self._state.ui_lang, 1)

    def _toggle_text_only(self) -> None:
        self._on_text_only_toggle(not self._state.text_only)

    def _restart(self) -> None:
        if self._restart_pending:
            return
        self._restart_pending = True
        self._restart_started = time.time()
        self._restart_seen_transition = False
        self._on_restart()

    def _update_restart_pending(self, status: tuple, now: float) -> None:
        """Clear the pending-restart state once the runtime came back up
        (status left running, e.g. 'Starting', then returned) - the same
        async-caption shape as the dashboard device pickers. 30 s timeout
        so a crashed restart doesn't pin the button; the status label then
        shows the failure."""
        if not self._restart_pending:
            return
        _connected, key, _detail = status
        if key != "status_running":
            self._restart_seen_transition = True
        if (self._restart_seen_transition and key == "status_running") or \
                (now - self._restart_started) > 30.0:
            self._restart_pending = False
            self._dirty.set()

    def _bump_font(self, delta: int) -> None:
        self._on_font_size(int(self._get_font_size()) + delta)

    def _reset(self) -> None:
        # resets whichever placement is being edited (label shows which)
        if self._state.edit_mode:
            self._state.request_position_reset()
        else:
            self._reset_requested = True

    # ---------------- rendering ----------------
    def label_fonts(self) -> tuple:
        """Default font ladder for table widgets drawn via `label`."""
        return (self._font_small, self._font_tiny)

    def _render(self, info: tuple, dragging: bool) -> Image.Image:
        connected, status_key, _detail = info
        lang = self._state.ui_lang
        wrist_edit = self._state.wrist_edit_mode
        sub_edit = self._state.edit_mode
        img = Image.new("RGBA", (TEX_W, TEX_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, TEX_W - 1, TEX_H - 1), 30, fill=COL_BG,
                            outline=COL_DRAG if (dragging or wrist_edit or sub_edit) else None,
                            width=4)

        dot = status_dot_color(connected, status_key)
        d.ellipse((20, 28, 44, 52), fill=dot)
        self._font_tiny.draw(d, (54, 40), "vrclt", fill=COL_TEXT, anchor="lm")

        draw_page(self, d, self._widgets, lang, page=self._page,
                  hover=self._hover if self._engaged else None,
                  pressed=self._pressed_name)

        if self._page == "main" and status_key != "status_running":
            draw_fit_text(d, LBL_STATUS, tr(lang, status_key),
                          fonts=(self._font_tiny,), fill=dot, max_lines=2,
                          pad_x=2, pad_y=2)
        return img

    # ---------------- transforms ----------------
    def _load_transform(self) -> np.ndarray:
        if self._configured_transform is not None:
            log.info("wrist panel: restored configured position")
            return self._configured_transform.copy()
        m = load_saved_transform(TRANSFORM_PATH, "wrist panel")
        return m if m is not None else self._watch_matrix()

    def _watch_matrix(self) -> np.ndarray:
        a = math.radians(-90.0 + self._tilt_deg)
        r = math.radians(self._roll_deg)
        rx = np.array([
            [1.0, 0.0, 0.0],
            [0.0, math.cos(a), -math.sin(a)],
            [0.0, math.sin(a), math.cos(a)],
        ])
        rz = np.array([
            [math.cos(r), -math.sin(r), 0.0],
            [math.sin(r), math.cos(r), 0.0],
            [0.0, 0.0, 1.0],
        ])
        m = np.identity(4)
        m[:3, :3] = rx @ rz
        m[0][3], m[1][3], m[2][3] = self._offset
        return m

    def _default_watch_matrix(self) -> np.ndarray:
        if self._configured_transform is not None:
            return self._configured_transform.copy()
        return self._watch_matrix()
