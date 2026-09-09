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
from dataclasses import replace

import numpy as np
from PIL import Image, ImageDraw

from ..config import APPDATA_DIR, OVERLAY_FONT_MAX, OVERLAY_FONT_MIN
from ..resources import bundled_font, resolve_font_path
from ..state import AppState
from ..i18n import tr, LANGS as UI_LANGS, UI_LANG_LABELS
from .button_table import (
    Widget, draw_page, glyph_draw, is_enabled, lang_grid_widgets,
    lang_page_count, widget_at,
)
from .font_fallback import load_fallback_font
from .panel_common import (
    COL_DRAG, COL_TEXT,
    clip_line, coerce_transform, create_overlay_set, cycle, draw_fit_text, haptic,
    language_label, laser_base, load_saved_transform, np_to_hmd34,
    pointer_matrix, pose_to_np, ray_plane_hit, save_transform,
    setup_pointer_overlays, status_dot_color, translate,
)
from .render import GlTexture, flip_bounds

log = logging.getLogger(__name__)

TEX_W, TEX_H = 640, 432
MAX_RAY_M = 1.2

GAZE_ON_DEG = 22.0
GAZE_OFF_DEG = 35.0
GAZE_DIST_M = 0.95

TRANSFORM_PATH = APPDATA_DIR / "wrist_transform.json"

# Compact watch: mode and restart stay on Live, with one row per direction.
BTN_RESTART = (456, 16, 620, 68)
BTN_MODE_VOICE = (20, 82, 312, 134)
BTN_MODE_TEXT = (324, 82, 620, 134)
BTN_TOGGLE = (20, 146, 254, 230)
BTN_LANG = (266, 146, 620, 230)
BTN_SUB_TOGGLE = (20, 242, 254, 326)
BTN_SUB_LANG = (266, 242, 620, 326)
BTN_NAV_LIVE = (20, 356, 312, 412)
BTN_NAV_SETTINGS = (324, 356, 620, 412)

BTN_UILANG = (20, 82, 620, 134)
LBL_FONT_CAPTION = (20, 146, 296, 198)
BTN_FONT_MINUS = (308, 146, 380, 198)
LBL_FONT_SIZE = (392, 146, 536, 198)
BTN_FONT_PLUS = (548, 146, 620, 198)
BTN_EDIT = (20, 210, 212, 272)
BTN_SUB_EDIT = (224, 210, 416, 272)
BTN_RESET = (428, 210, 620, 272)
BTN_SPEAKER_CONTEXT = (20, 284, 620, 338)

CURSOR_SIZE_M = 0.012
PICKER_CAPTION = (20, 20, 348, 68)
PICKER_PGPREV = (360, 20, 432, 68)
PICKER_PGNEXT = (440, 20, 512, 68)
PICKER_CLOSE = (532, 20, 620, 68)
PICKER_GRID = (20, 82, 620, 338)
PICKER_COLS, PICKER_ROWS = 3, 3

# Wrist-specific surfaces keep the direction colors as small status accents.
WATCH_SURFACE = (25, 35, 49, 255)
WATCH_INSET = (19, 28, 40, 255)
WATCH_EDGE = (52, 68, 88, 255)
WATCH_MINT = (112, 220, 172, 255)
WATCH_BLUE = (132, 194, 248, 255)
WATCH_DIM = (158, 174, 193, 255)
WATCH_SELECTED = (37, 57, 78, 255)


def _left_text(panel, d, box, text, *, fonts=None, fill=COL_TEXT):
    fonts = fonts or (panel._font_small, panel._font_tiny)
    x0, y0, x1, y1 = box
    font = next((f for f in fonts if f.textlength(d, text) <= x1 - x0
                 and f.line_height(d) <= y1 - y0), fonts[-1])
    text = clip_line(d, text, font, x1 - x0)
    font.draw(d, (x0, (y0 + y1) / 2), text, fill=fill, anchor="lm")


def _border(panel, d, w):
    color = WATCH_BLUE if panel._engaged and panel._hover == w.name else WATCH_EDGE
    d.rounded_rectangle(w.rect, w.radius, outline=color, width=1)


def _label_draw(key, *, state_key=None):
    def draw(panel, d, w, lang):
        _border(panel, d, w)
        label = state_key(panel, lang) if state_key else tr(lang, key)
        draw_fit_text(d, w.rect, label, fonts=panel.label_fonts(),
                      fill=COL_TEXT if is_enabled(w, panel) else WATCH_DIM,
                      max_lines=1, pad_x=10, pad_y=4)
    return draw


def _toggle_draw(title_key, caption_key, is_on, accent):
    def draw(panel, d, w, lang):
        _border(panel, d, w)
        x0, y0, x1, y1 = w.rect
        on = is_on(panel)
        color = accent if on else WATCH_DIM
        d.rounded_rectangle((x0 + 1, y0 + 18, x0 + 4, y1 - 18), 2, fill=color)
        _left_text(panel, d, (x0 + 16, y0 + 9, x1 - 62, y0 + 43),
                   tr(lang, title_key), fonts=(panel._font_mid, panel._font_small))
        panel._font_tiny.draw(d, (x1 - 32, y0 + 27), "ON" if on else "OFF",
                              fill=color, anchor="mm")
        _left_text(panel, d, (x0 + 16, y0 + 47, x1 - 12, y1 - 9),
                   tr(lang, caption_key), fonts=(panel._font_tiny,), fill=WATCH_DIM)
    return draw


def _lang_label_draw(code_of, caption_key):
    def draw(panel, d, w, lang):
        _border(panel, d, w)
        x0, y0, x1, y1 = w.rect
        _left_text(panel, d, (x0 + 18, y0 + 8, x1 - 42, y0 + 31),
                   tr(lang, caption_key), fonts=(panel._font_tiny,), fill=WATCH_DIM)
        _left_text(panel, d, (x0 + 18, y0 + 35, x1 - 42, y1 - 7),
                   language_label(code_of(panel)),
                   fonts=(panel._font_big, panel._font_mid, panel._font_small))
        cy = (y0 + y1) / 2
        d.line(((x1 - 27, cy - 5), (x1 - 21, cy), (x1 - 27, cy + 5)),
               fill=WATCH_DIM, width=2)
    return draw


def _mode_draw(text_only):
    def draw(panel, d, w, lang):
        _border(panel, d, w)
        selected = panel._state.text_only == text_only
        active = selected and is_enabled(w, panel)
        x0, y0, x1, y1 = w.rect
        cy = (y0 + y1) / 2
        d.ellipse((x0 + 18, cy - 5, x0 + 28, cy + 5),
                  fill=WATCH_BLUE if active else None, outline=WATCH_BLUE if active else WATCH_DIM)
        draw_fit_text(d, (x0 + 38, y0, x1 - 10, y1),
                      tr(lang, "dash_applying" if panel._mode_pending and selected else
                         "vr_mode_text" if text_only else "vr_mode_voice"),
                      fonts=panel.label_fonts(),
                      fill=COL_TEXT if active else WATCH_DIM, max_lines=1)
    return draw


def _ui_language_draw(panel, d, w, lang):
    _border(panel, d, w)
    x0, y0, x1, y1 = w.rect
    _left_text(panel, d, (x0 + 18, y0, x0 + 250, y1), tr(lang, "ui_lang"), fill=WATCH_DIM)
    draw_fit_text(d, (x0 + 270, y0, x1 - 18, y1), UI_LANG_LABELS.get(lang, lang),
                  fonts=panel.label_fonts(), max_lines=1)


def _speaker_context_draw(panel, d, w, lang):
    _border(panel, d, w)
    enabled, seconds = panel._get_speaker_context()
    key = ("dash_applying" if panel._speaker_context_pending else
           "dash_apply_failed" if panel._speaker_context_failed else
           "vr_speaker_context_on" if enabled else "vr_speaker_context_off")
    x0, y0, x1, y1 = w.rect
    _left_text(panel, d, (x0 + 16, y0 + 3, x1 - 12, y0 + 29), tr(lang, key),
               fill=WATCH_BLUE if enabled else COL_TEXT)
    timeout = (tr(lang, "soniox_idle_timeout_status").format(seconds=f"{seconds:g}")
               if seconds > 0 else tr(lang, "soniox_idle_timeout_disabled"))
    _left_text(panel, d, (x0 + 16, y0 + 30, x1 - 12, y1 - 2), timeout,
               fonts=(panel._font_tiny,), fill=WATCH_DIM)


def _nav_draw(settings):
    def draw(panel, d, w, lang):
        selected = (panel._page == "settings") == settings
        draw_fit_text(d, w.rect, tr(lang, "vr_nav_settings" if settings else "vr_nav_live"),
                      fonts=panel.label_fonts(), fill=COL_TEXT if selected else WATCH_DIM,
                      max_lines=1)
        if selected:
            x0, y0, x1, y1 = w.rect
            d.rounded_rectangle(((x0+x1)/2 - 18, y1 - 7, (x0+x1)/2 + 18, y1 - 4),
                                2, fill=WATCH_BLUE)
    return draw


def _nav_widgets(page):
    return (
        Widget("nav_live", BTN_NAV_LIVE, page=page, radius=14,
               fill=lambda p: WATCH_SURFACE if p._page != "settings" else WATCH_INSET,
               draw=_nav_draw(False)),
        Widget("nav_settings", BTN_NAV_SETTINGS, page=page, radius=14,
               fill=lambda p: WATCH_SURFACE if p._page == "settings" else WATCH_INSET,
               draw=_nav_draw(True)),
    )


def _build_widgets():
    ready = lambda p: not (p._restart_pending or p._speaker_context_pending or p._mode_pending)
    return (
        Widget("restart", BTN_RESTART, radius=14, enabled=ready, fill=lambda p: WATCH_SURFACE,
               draw=_label_draw("vr_restart", state_key=lambda p, lang: tr(
                   lang, "btn_restarting" if p._restart_pending else "vr_restart"))),
        Widget("mode_voice", BTN_MODE_VOICE, radius=14, enabled=ready,
               fill=lambda p: WATCH_SELECTED if not p._state.text_only else WATCH_INSET,
               draw=_mode_draw(False)),
        Widget("mode_text", BTN_MODE_TEXT, radius=14, enabled=ready,
               fill=lambda p: WATCH_SELECTED if p._state.text_only else WATCH_INSET,
               draw=_mode_draw(True)),
        Widget("toggle", BTN_TOGGLE, radius=16,
               fill=lambda p: (22, 42, 39, 255) if p._state.translation_on else WATCH_SURFACE,
               draw=_toggle_draw("vr_translate", "my_to_other", lambda p: p._state.translation_on, WATCH_MINT)),
        Widget("lang", BTN_LANG, radius=16, fill=lambda p: WATCH_SURFACE,
               draw=_lang_label_draw(lambda p: p._state.target_language, "out_lang")),
        Widget("sub_toggle", BTN_SUB_TOGGLE, radius=16,
               fill=lambda p: (23, 37, 54, 255) if p._state.subtitles_on else WATCH_SURFACE,
               draw=_toggle_draw("vr_subtitles", "other_to_sub", lambda p: p._state.subtitles_on, WATCH_BLUE)),
        Widget("sub_lang", BTN_SUB_LANG, radius=16, fill=lambda p: WATCH_SURFACE,
               draw=_lang_label_draw(lambda p: p._state.inbound_language, "sub_lang")),
    ) + _nav_widgets("main")


def _build_settings_widgets(*, soniox):
    widgets = (
        Widget("uilang", BTN_UILANG, page="settings", fill=lambda p: WATCH_SURFACE, draw=_ui_language_draw),
        Widget("font_caption", LBL_FONT_CAPTION, kind="label", page="settings", fill=lambda p: WATCH_INSET,
               label=lambda p, lang: tr(lang, "dash_font_size")),
        Widget("font_minus", BTN_FONT_MINUS, page="settings", fill=lambda p: WATCH_SURFACE,
               enabled=lambda p: int(p._get_font_size()) > OVERLAY_FONT_MIN, draw=glyph_draw("−")),
        Widget("font_size", LBL_FONT_SIZE, kind="label", page="settings", fill=lambda p: WATCH_INSET,
               label=lambda p, lang: str(int(p._get_font_size()))),
        Widget("font_plus", BTN_FONT_PLUS, page="settings", fill=lambda p: WATCH_SURFACE,
               enabled=lambda p: int(p._get_font_size()) < OVERLAY_FONT_MAX, draw=glyph_draw("+")),
        Widget("edit", BTN_EDIT, page="settings",
               fill=lambda p: WATCH_SELECTED if p._state.wrist_edit_mode else WATCH_SURFACE,
               draw=_label_draw("vr_move_wrist")),
        Widget("sub_edit", BTN_SUB_EDIT, page="settings",
               fill=lambda p: WATCH_SELECTED if p._state.edit_mode else WATCH_SURFACE,
               draw=_label_draw("vr_move_subtitles")),
        Widget("reset", BTN_RESET, page="settings", fill=lambda p: WATCH_SURFACE,
               draw=_label_draw("", state_key=lambda p, lang: tr(
                   lang, "reset_sub_pos" if p._state.edit_mode else "reset_watch_pos"))),
    )
    if soniox:
        widgets += (Widget("speaker_context", BTN_SPEAKER_CONTEXT, page="settings", radius=14,
                           enabled=lambda p: not (p._speaker_context_pending or p._restart_pending or p._mode_pending),
                           fill=lambda p: WATCH_INSET, draw=_speaker_context_draw),)
    return widgets + _nav_widgets("settings")


class WristPanel:
    def __init__(self, state: AppState, languages: list[str], *,
                 inbound_languages: list[str] | None = None,
                 hand: str = "left", width_m: float = 0.14,
                 offset=(0.0, 0.02, 0.12), tilt_deg: float = 0.0,
                 roll_deg: float | None = None,
                 transform=None,
                 pointer_tilt_deg: float = 50.0,
                 font_path: str = bundled_font("NotoSansCJKkr-Bold.otf"),
                 on_text_only_toggle=lambda enabled, on_done: on_done(False),
                 on_transform_changed=lambda matrix, reset=False: None,
                 get_status_info=lambda: (False, "status_stopped", ""),
                 on_restart=lambda: None,
                 on_font_size=lambda size: None,
                 get_font_size=lambda: 27,
                 get_provider=lambda: "gemini",
                 get_speaker_context=lambda: (True, 60.0),
                 set_speaker_context=lambda enabled, on_done: on_done(False)):
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
        self._get_provider = get_provider
        self._get_speaker_context = get_speaker_context
        self._set_speaker_context = set_speaker_context
        font_path = resolve_font_path(font_path, "NotoSansCJKkr-Bold.otf")
        self._font_big = load_fallback_font(font_path, 32, bold=True)
        self._font_mid = load_fallback_font(font_path, 26, bold=True)
        self._font_small = load_fallback_font(font_path, 22, bold=True)
        self._font_tiny = load_fallback_font(font_path, 18, bold=False)

        self._widgets = _build_widgets()
        self._settings_widgets = {
            False: _build_settings_widgets(soniox=False),
            True: _build_settings_widgets(soniox=True),
        }
        self._page = "main"
        self._hover = None
        self._pressed_name = None
        self._engaged = False
        self._dragging = False
        self._restart_pending = False
        self._mode_pending = False
        self._restart_started = 0.0
        self._restart_seen_transition = False
        self._speaker_context_pending = False
        self._speaker_context_failed = False
        self._speaker_context_error_until = 0.0
        self._speaker_context_failure_state = None
        self._last_controls = None
        self._click_handlers = {
            "toggle": self._toggle_translation,
            "sub_toggle": self._toggle_subtitles,
            "edit": self._toggle_wrist_edit,
            "sub_edit": self._toggle_sub_edit,
            "uilang": self._cycle_ui_lang,
            "mode_voice": lambda: self._set_text_only(False),
            "mode_text": lambda: self._set_text_only(True),
            "restart": self._restart,
            "font_minus": lambda: self._bump_font(-2),
            "font_plus": lambda: self._bump_font(2),
            "reset": self._reset,
            "speaker_context": self._toggle_speaker_context,
            "nav_live": lambda: self._set_page("main"),
            "nav_settings": lambda: self._set_page("settings"),
            "lang": lambda: self._open_picker("out"),
            "sub_lang": lambda: self._open_picker("in"),
            "picker_close": self._close_picker,
            "picker_pgprev": lambda: self._flip_picker_page(-1),
            "picker_pgnext": lambda: self._flip_picker_page(1),
        }
        self._picker_idx = 0
        self._picker_cache: dict = {}

        self._dirty = threading.Event()
        self._dirty.set()
        self._reset_requested = False
        state.subscribe(self._on_state)

        self._h = self._h_laser = self._h_cursor = None
        self._tex = None

    def _on_state(self, field: str, _value) -> None:
        if field == "reset_positions":
            self._reset_requested = True
            self._page = "main"
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
        self._page = "main"
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
            # These values can also change from the desktop UI without an
            # AppState event. Refresh the visible controls at the same 1 Hz.
            controls = (self._get_provider(), self._get_speaker_context(),
                        int(self._get_font_size()))
            if controls != self._last_controls:
                self._last_controls = controls
                self._dirty.set()
            self._update_restart_pending(status, now)
            self._update_context_feedback(now)
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
                # don't strand an open picker on an unwatched wrist
                self._close_picker()

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
        return (widget_at(self._active_widgets(), self, px, py, self._page),
                True, (x, y))

    def _on_click(self, button: str) -> None:
        widget = next((w for w in self._active_widgets()
                       if w.name == button and w.page == self._page
                       and w.kind == "button"), None)
        if widget is None or not is_enabled(widget, self):
            return
        log.info("wrist panel click: %s", button)
        if button.startswith("pick_out:"):
            self._state.target_language = button.split(":", 1)[1]
            self._close_picker()
            return
        if button.startswith("pick_in:"):
            self._state.inbound_language = button.split(":", 1)[1]
            self._close_picker()
            return
        handler = self._click_handlers.get(button)
        if handler is not None:
            handler()

    # ---------------- language grid picker ----------------
    def _set_page(self, page: str) -> None:
        self._page = page
        self._hover = None
        self._pressed_name = None
        self._dirty.set()

    def _open_picker(self, kind: str) -> None:
        langs = self._languages if kind == "out" else self._inbound_languages
        current = (self._state.target_language if kind == "out"
                   else self._state.inbound_language)
        per_page = PICKER_COLS * PICKER_ROWS
        self._picker_idx = (langs.index(current) // per_page
                            if current in langs else 0)
        self._set_page("lang_out" if kind == "out" else "lang_in")

    def _close_picker(self) -> None:
        if self._page in ("lang_out", "lang_in"):
            self._set_page("main")

    def _flip_picker_page(self, step: int) -> None:
        langs = (self._languages if self._page == "lang_out"
                 else self._inbound_languages)
        n_pages = lang_page_count(langs, PICKER_COLS, PICKER_ROWS)
        self._picker_idx = max(0, min(self._picker_idx + step, n_pages - 1))
        self._dirty.set()

    def _active_widgets(self) -> tuple:
        if self._page == "main":
            return self._widgets
        if self._page == "settings":
            return self._settings_widgets[self._get_provider() == "soniox"]
        key = (self._page, self._picker_idx)
        cached = self._picker_cache.get(key)
        if cached is None:
            cached = self._picker_cache[key] = self._build_picker_page(*key)
        return cached

    def _build_picker_page(self, page: str, page_idx: int) -> tuple:
        out = page == "lang_out"
        langs = self._languages if out else self._inbound_languages
        n_pages = lang_page_count(langs, PICKER_COLS, PICKER_ROWS)
        widgets = [
            Widget("picker_caption", PICKER_CAPTION, kind="label", page=page,
                   fill=lambda p: WATCH_INSET,
                   label=lambda p, lang, k=("out_lang" if out else "sub_lang"):
                       tr(lang, k)),
            Widget("picker_close", PICKER_CLOSE, page=page,
                   fill=lambda p: WATCH_SURFACE, draw=glyph_draw("×")),
        ]
        if n_pages > 1:
            widgets.append(Widget("picker_pgprev", PICKER_PGPREV, page=page,
                                  fill=lambda p: WATCH_SURFACE,
                                  enabled=lambda p: p._picker_idx > 0,
                                  draw=glyph_draw("◀")))
            widgets.append(Widget("picker_pgnext", PICKER_PGNEXT, page=page,
                                  fill=lambda p: WATCH_SURFACE,
                                  enabled=lambda p, n=n_pages: p._picker_idx < n - 1,
                                  draw=glyph_draw("▶")))
        choices = lang_grid_widgets(
            page=page, languages=langs, page_idx=page_idx, area=PICKER_GRID,
            cols=PICKER_COLS, rows=PICKER_ROWS,
            name_prefix="pick_out" if out else "pick_in",
            current_of=(lambda p: p._state.target_language) if out
                       else (lambda p: p._state.inbound_language),
            accent=WATCH_SELECTED)
        for choice in choices:
            widgets.append(replace(
                choice, radius=14,
                fill=lambda p, original=choice.fill: (
                    WATCH_SELECTED if original(p) == WATCH_SELECTED else WATCH_SURFACE),
                draw=_label_draw("", state_key=choice.label)))
        return tuple(widgets) + _nav_widgets(page)

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

    def _set_text_only(self, enabled: bool) -> None:
        if self._speaker_context_pending or self._restart_pending or self._mode_pending \
                or self._state.text_only == enabled:
            return
        self._mode_pending = True
        self._dirty.set()

        def done(_ok: bool) -> None:
            self._mode_pending = False
            self._dirty.set()

        try:
            self._on_text_only_toggle(enabled, done)
        except Exception:
            log.exception("wrist panel: mode update failed")
            done(False)

    def _toggle_speaker_context(self) -> None:
        if self._get_provider() != "soniox" or self._speaker_context_pending \
                or self._restart_pending or self._mode_pending:
            return
        self._speaker_context_pending = True
        self._speaker_context_failed = False
        self._dirty.set()

        def done(ok: bool) -> None:
            self._speaker_context_error_until = 0.0 if ok else time.time() + 5.0
            self._speaker_context_failure_state = self._get_speaker_context()
            self._speaker_context_pending = False
            self._speaker_context_failed = not ok
            self._dirty.set()

        try:
            self._set_speaker_context(not self._get_speaker_context()[0], done)
        except Exception:
            log.exception("wrist panel: speaker context update failed")
            done(False)

    def _update_context_feedback(self, now: float) -> None:
        if self._speaker_context_failed and (
                now >= self._speaker_context_error_until
                or self._get_speaker_context() != self._speaker_context_failure_state):
            self._speaker_context_failed = False
            self._dirty.set()

    def _restart(self) -> None:
        if self._restart_pending or self._speaker_context_pending or self._mode_pending:
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
        d.rounded_rectangle((0, 0, TEX_W - 1, TEX_H - 1), 26,
                            fill=(14, 21, 31, 248), outline=WATCH_EDGE, width=1)
        d.rounded_rectangle((6, 6, TEX_W - 7, TEX_H - 7), 22,
                            outline=COL_DRAG if (dragging or wrist_edit or sub_edit) else (27, 39, 54, 255),
                            width=2)
        d.line((20, 345, 620, 345), fill=WATCH_EDGE, width=1)
        dot = status_dot_color(connected, status_key)
        if self._page in ("main", "settings"):
            self._font_small.draw(d, (24, 28), "VRCLT", fill=COL_TEXT, anchor="lm")
            _left_text(self, d, (126, 14, 430, 42), self._get_provider().upper(),
                       fonts=(self._font_tiny,), fill=WATCH_DIM)
            d.ellipse((24, 51, 34, 61), fill=dot)
            _left_text(self, d, (44, 43, 430, 69), tr(lang, status_key),
                       fonts=(self._font_tiny,), fill=WATCH_DIM)
            if self._page == "settings" and self._get_provider() != "soniox":
                draw_fit_text(d, BTN_SPEAKER_CONTEXT, tr(lang, "vr_hint_position"),
                              fonts=(self._font_tiny,), fill=WATCH_DIM, max_lines=2)

        draw_page(self, d, self._active_widgets(), lang, page=self._page,
                  hover=self._hover if self._engaged else None,
                  pressed=self._pressed_name)

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
