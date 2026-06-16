"""XSOverlay-style wrist menu panel (component of the VR render thread).

Interaction (no SteamVR input capture - the game keeps full control):
- gaze gate: panel fades opaque + our own laser appears only while LOOKING
  at the watch up close
- TRIGGER on a button: click; GRIP anywhere on the panel: grab & move
  (release saves; [위치 리셋] button resets)
- the laser points 'pointer_tilt_deg' below the controller's raw forward,
  matching the natural pistol-grip pointing direction

Textures are persistent OpenGL textures (see vr/render.py for why).
"""
import json
import logging
import math
import os
import time
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..state import AppState
from ..i18n import tr, LANGS as UI_LANGS, UI_LANG_LABELS
from .render import GlTexture, flip_bounds

log = logging.getLogger(__name__)

TEX_W, TEX_H = 512, 440
MAX_RAY_M = 1.2

GAZE_ON_DEG = 22.0
GAZE_OFF_DEG = 35.0
GAZE_DIST_M = 0.95

TRANSFORM_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "vrclt" / "wrist_transform.json"

BTN_UILANG = (118, 10, 208, 62)      # cycles the UI display language
BTN_EDIT = (216, 10, 360, 62)
BTN_RESET = (368, 10, 496, 62)
BTN_TOGGLE = (16, 76, 248, 248)
BTN_PREV = (264, 76, 320, 248)
BTN_LANG = (320, 76, 440, 248)       # label only
BTN_NEXT = (440, 76, 496, 248)
BTN_SUB_TOGGLE = (16, 260, 248, 432)
BTN_SUB_PREV = (264, 260, 320, 432)
BTN_SUB_LANG = (320, 260, 440, 432)  # label only
BTN_SUB_NEXT = (440, 260, 496, 432)

BUTTONS = (("toggle", BTN_TOGGLE), ("prev", BTN_PREV), ("next", BTN_NEXT),
           ("sub_toggle", BTN_SUB_TOGGLE), ("sub_prev", BTN_SUB_PREV),
           ("sub_next", BTN_SUB_NEXT), ("edit", BTN_EDIT), ("reset", BTN_RESET),
           ("uilang", BTN_UILANG))

LANG_LABELS = {
    "ja": "日本語", "en": "English", "ko": "한국어",
    "zh-Hans": "中文(S)", "zh-Hant": "中文(T)", "yue": "廣東話",
    "es": "Español", "ru": "Русский", "fr": "Français", "de": "Deutsch",
}

COL_BG = (16, 18, 24, 235)
COL_BTN = (38, 42, 54, 255)
COL_ON = (46, 160, 67, 255)
COL_OFF = (120, 84, 30, 255)
COL_SUB_ON = (40, 110, 170, 255)
COL_TEXT = (240, 240, 240, 255)
COL_DIM = (150, 150, 150, 255)
COL_DRAG = (70, 110, 180, 255)

LASER_TEX_W, LASER_TEX_H = 4, 512
LASER_WIDTH_M = 0.004
LASER_LEN_M = LASER_WIDTH_M * LASER_TEX_H / LASER_TEX_W  # 0.512 m
CURSOR_SIZE_M = 0.016


class WristPanel:
    def __init__(self, state: AppState, languages: list[str], *,
                 inbound_languages: list[str] | None = None,
                 hand: str = "left", width_m: float = 0.12,
                 offset=(0.0, 0.02, 0.12), tilt_deg: float = 0.0,
                 roll_deg: float | None = None,
                 pointer_tilt_deg: float = 50.0,
                 font_path: str = "C:/Windows/Fonts/malgunbd.ttf",
                 get_status=lambda: False):
        self._state = state
        self._languages = languages or ["en"]
        self._inbound_languages = inbound_languages or ["ko", "en"]
        self._hand = hand
        self._width_m = width_m
        self._height_m = width_m * TEX_H / TEX_W
        self._offset = tuple(offset)
        self._tilt_deg = tilt_deg
        self._roll_deg = roll_deg if roll_deg is not None else (90.0 if hand == "left" else -90.0)
        a = math.radians(-pointer_tilt_deg)
        self._pointer_mat = np.identity(4)
        self._pointer_mat[1][1] = math.cos(a)
        self._pointer_mat[1][2] = -math.sin(a)
        self._pointer_mat[2][1] = math.sin(a)
        self._pointer_mat[2][2] = math.cos(a)
        self._get_status = get_status
        try:
            self._font_big = ImageFont.truetype(font_path, 52)
            self._font_mid = ImageFont.truetype(font_path, 38)
            self._font_small = ImageFont.truetype(font_path, 26)
        except OSError:
            self._font_big = self._font_mid = self._font_small = ImageFont.load_default()

        self._dirty = threading.Event()
        self._dirty.set()
        self._reset_requested = False
        state.subscribe(lambda *_: self._dirty.set())

        self._h = self._h_laser = self._h_cursor = None
        self._tex = None

    # ---------------- component lifecycle ----------------
    def setup(self, ctx) -> bool:
        openvr, ovl = ctx.openvr, ctx.ovl
        created = []
        try:
            for key, name in (("vrclt.wrist", "vrclt wrist menu"),
                              ("vrclt.laser", "vrclt laser"),
                              ("vrclt.cursor", "vrclt cursor")):
                created.append(ovl.createOverlay(key, name))
        except Exception as e:
            for h in created:
                try:
                    ovl.destroyOverlay(h)
                except Exception:
                    pass
            if "KeyInUse" in type(e).__name__:
                log.warning("wrist panel: overlay key in use - another vrclt instance running?")
                return False
            raise
        self._h, self._h_laser, self._h_cursor = created

        bounds = flip_bounds(openvr)
        ovl.setOverlayWidthInMeters(self._h, self._width_m)
        ovl.setOverlayAlpha(self._h, 0.55)
        ovl.setOverlayTextureBounds(self._h, bounds)
        self._tex = GlTexture(TEX_W, TEX_H)

        ovl.setOverlayWidthInMeters(self._h_laser, LASER_WIDTH_M)
        ovl.setOverlaySortOrder(self._h_laser, 200)
        ovl.setOverlayTextureBounds(self._h_laser, bounds)
        laser_tex = GlTexture(LASER_TEX_W, LASER_TEX_H)
        laser_tex.update(self._laser_texture())
        ovl.setOverlayTexture(self._h_laser, laser_tex.vr_texture(openvr))
        self._laser_tex = laser_tex

        ovl.setOverlayWidthInMeters(self._h_cursor, CURSOR_SIZE_M)
        ovl.setOverlaySortOrder(self._h_cursor, 201)
        ovl.setOverlayTextureBounds(self._h_cursor, bounds)
        cursor_tex = GlTexture(64, 64)
        cursor_tex.update(self._cursor_texture())
        ovl.setOverlayTexture(self._h_cursor, cursor_tex.vr_texture(openvr))
        self._cursor_tex = cursor_tex

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
                    self._h, self._wrist_idx, self._np_to_hmd34(openvr, self._overlay_mat))
                self._attached_to = self._wrist_idx
                log.info("wrist panel attached to controller %d", self._wrist_idx)
            if self._finger_idx != self._invalid and self._finger_idx != self._laser_attached_to:
                ovl.setOverlayTransformTrackedDeviceRelative(
                    self._h_laser, self._finger_idx,
                    self._np_to_hmd34(openvr, self._pointer_mat @ self._laser_base()))
                self._laser_attached_to = self._finger_idx

        status = bool(self._get_status())
        if status != self._last_status:
            self._last_status = status
            self._dirty.set()

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
                    w4 = self._pose_to_np(wp)
                    f4 = self._pose_to_np(fp)
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

                    # panels only move in edit mode - everyday grips (game
                    # grabbing, gestures) must never relocate the UI
                    if grip and not self._prev_grip and on_panel and \
                            not self._dragging and self._state.edit_mode:
                        self._drag_offset = np.linalg.inv(f4) @ w4 @ self._overlay_mat
                        self._dragging = True
                        self._haptic(vrsys, openvr, self._finger_idx, 2000)
                        self._dirty.set()
                        log.info("wrist panel grabbed")
                    if self._dragging:
                        if grip and self._drag_offset is not None:
                            self._overlay_mat = np.linalg.inv(w4) @ f4 @ self._drag_offset
                            ovl.setOverlayTransformTrackedDeviceRelative(
                                self._h, self._wrist_idx,
                                self._np_to_hmd34(openvr, self._overlay_mat))
                        else:
                            self._dragging = False
                            self._overlay_mat_inv = np.linalg.inv(self._overlay_mat)
                            self._save_transform(self._overlay_mat, TRANSFORM_PATH)
                            self._haptic(vrsys, openvr, self._finger_idx, 3000)
                            self._dirty.set()
                            log.info("wrist panel placed (saved)")
                        new_hover = None

                    if not self._dragging and new_hover is not None and \
                            trigger and not self._prev_trigger:
                        self._on_click(new_hover)
                        self._haptic(vrsys, openvr, self._finger_idx, 3000)
                        self._dirty.set()

                    self._prev_trigger, self._prev_grip = trigger, grip

                    if hit_xy is not None:
                        cur = self._overlay_mat @ self._translate(hit_xy[0], hit_xy[1], 0.004)
                        ovl.setOverlayTransformTrackedDeviceRelative(
                            self._h_cursor, self._wrist_idx, self._np_to_hmd34(openvr, cur))
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
                self._haptic(vrsys, openvr, self._finger_idx, 600)
            self._hover = new_hover
            # hover never re-renders the panel (texture swaps can flicker);
            # the cursor dot + haptics are the pointer feedback

        if self._reset_requested and not self._dragging:
            self._reset_requested = False
            self._overlay_mat = self._watch_matrix()
            self._overlay_mat_inv = np.linalg.inv(self._overlay_mat)
            if self._attached_to != self._invalid:
                ovl.setOverlayTransformTrackedDeviceRelative(
                    self._h, self._attached_to, self._np_to_hmd34(openvr, self._overlay_mat))
            try:
                TRANSFORM_PATH.unlink(missing_ok=True)
            except OSError:
                pass
            log.info("wrist panel position reset to defaults")

        if self._dirty.is_set():
            self._dirty.clear()
            self._tex.update(self._render(status, self._dragging))
            ovl.setOverlayTexture(self._h, self._tex.vr_texture(openvr))

    # ---------------- gaze ----------------
    def _update_gaze(self, ovl, hp, wp) -> None:
        h4 = self._pose_to_np(hp)
        w4 = self._pose_to_np(wp)
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

    # ---------------- interaction ----------------
    def _ray_hit(self, w4: np.ndarray, f4: np.ndarray):
        to_overlay = self._overlay_mat_inv @ np.linalg.inv(w4) @ f4 @ self._pointer_mat
        origin = to_overlay @ np.array([0.0, 0.0, 0.0, 1.0])
        direction = to_overlay @ np.array([0.0, 0.0, -1.0, 0.0])
        dz = float(direction[2])
        if abs(dz) < 1e-6:
            return None, False, None
        t = -float(origin[2]) / dz
        if t < 0.0 or t > MAX_RAY_M:
            return None, False, None
        x = float(origin[0] + t * direction[0])
        y = float(origin[1] + t * direction[1])
        half_w, half_h = self._width_m / 2, self._height_m / 2
        if abs(x) > half_w + 0.015 or abs(y) > half_h + 0.015:
            return None, False, None
        u = (x + half_w) / self._width_m
        v = 1.0 - (y + half_h) / self._height_m
        px, py = u * TEX_W, v * TEX_H
        for name, (x0, y0, x1, y1) in BUTTONS:
            if x0 <= px <= x1 and y0 <= py <= y1:
                return name, True, (x, y)
        return None, True, (x, y)

    def _on_click(self, button: str) -> None:
        log.info("wrist panel click: %s", button)
        st = self._state
        if button == "toggle":
            st.translation_on = not st.translation_on
        elif button == "sub_toggle":
            st.subtitles_on = not st.subtitles_on
        elif button in ("prev", "next"):
            st.target_language = self._cycle(self._languages, st.target_language,
                                             1 if button == "next" else -1)
        elif button in ("sub_prev", "sub_next"):
            st.inbound_language = self._cycle(self._inbound_languages, st.inbound_language,
                                              1 if button == "sub_next" else -1)
        elif button == "edit":
            st.edit_mode = not st.edit_mode
        elif button == "uilang":
            st.ui_lang = self._cycle(UI_LANGS, st.ui_lang, 1)
        elif button == "reset":
            self._reset_requested = True
            st.request_position_reset()  # the subtitle panel listens for this

    @staticmethod
    def _cycle(langs: list[str], cur: str, step: int) -> str:
        idx = langs.index(cur) if cur in langs else 0
        return langs[(idx + step) % len(langs)]

    @staticmethod
    def _haptic(vrsys, openvr, device_idx, micros: int) -> None:
        if device_idx == openvr.k_unTrackedDeviceIndexInvalid:
            return
        try:
            vrsys.triggerHapticPulse(device_idx, 0, micros)
        except Exception:
            pass

    # ---------------- rendering ----------------
    @staticmethod
    def _laser_texture() -> Image.Image:
        img = Image.new("RGBA", (LASER_TEX_W, LASER_TEX_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for y in range(LASER_TEX_H):
            a = int(220 * (1.0 - y / LASER_TEX_H))
            d.line([(0, y), (LASER_TEX_W, y)], fill=(120, 180, 255, a))
        return img

    @staticmethod
    def _cursor_texture() -> Image.Image:
        s = 64
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, s - 4, s - 4), outline=(255, 255, 255, 230), width=6)
        d.ellipse((22, 22, s - 22, s - 22), fill=(120, 180, 255, 255))
        return img

    def _fit_font(self, draw, text: str, max_width: float):
        for font in (self._font_big, self._font_mid, self._font_small):
            if draw.textlength(text, font=font) <= max_width:
                return font
        return self._font_small

    def _lang_block(self, d, prev_box, lang_box, next_box, code: str, caption: str) -> None:
        for box, label in ((prev_box, "◀"), (next_box, "▶")):
            d.rounded_rectangle(box, 14, fill=COL_BTN)
            d.text(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2),
                   label, font=self._font_mid, fill=COL_TEXT, anchor="mm")
        d.rounded_rectangle(lang_box, 14, fill=(28, 30, 38, 255))
        label = LANG_LABELS.get(code, code)
        font = self._fit_font(d, label, lang_box[2] - lang_box[0] - 12)
        d.text(((lang_box[0] + lang_box[2]) // 2, (lang_box[1] + lang_box[3]) // 2 - 14),
               label, font=font, fill=COL_TEXT, anchor="mm")
        d.text(((lang_box[0] + lang_box[2]) // 2, lang_box[3] - 24),
               caption, font=self._font_small, fill=COL_DIM, anchor="mm")

    def _render(self, connected: bool, dragging: bool) -> Image.Image:
        lang = self._state.ui_lang
        edit = self._state.edit_mode
        img = Image.new("RGBA", (TEX_W, TEX_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, TEX_W - 1, TEX_H - 1), 24, fill=COL_BG,
                            outline=COL_DRAG if (dragging or edit) else None, width=4)

        dot = COL_ON if connected else (110, 110, 110, 255)
        d.ellipse((20, 22, 44, 46), fill=dot)
        d.text((56, 34), "vrclt", font=self._font_small, fill=COL_TEXT, anchor="lm")
        # UI display-language cycle
        d.rounded_rectangle(BTN_UILANG, 12, fill=COL_BTN)
        ui_label = UI_LANG_LABELS.get(lang, lang)
        d.text(((BTN_UILANG[0] + BTN_UILANG[2]) // 2, (BTN_UILANG[1] + BTN_UILANG[3]) // 2),
               ui_label, font=self._fit_font(d, ui_label, BTN_UILANG[2] - BTN_UILANG[0] - 10),
               fill=COL_TEXT, anchor="mm")
        d.rounded_rectangle(BTN_EDIT, 12, fill=COL_DRAG if edit else COL_BTN)
        d.text(((BTN_EDIT[0] + BTN_EDIT[2]) // 2, (BTN_EDIT[1] + BTN_EDIT[3]) // 2),
               tr(lang, "edit_moving" if dragging else "edit_mode"), font=self._font_small,
               fill=COL_TEXT, anchor="mm")
        d.rounded_rectangle(BTN_RESET, 12, fill=COL_BTN)
        d.text(((BTN_RESET[0] + BTN_RESET[2]) // 2, (BTN_RESET[1] + BTN_RESET[3]) // 2),
               tr(lang, "pos_reset"), font=self._font_small, fill=COL_TEXT, anchor="mm")

        on = self._state.translation_on
        d.rounded_rectangle(BTN_TOGGLE, 18, fill=COL_ON if on else COL_OFF)
        cx = (BTN_TOGGLE[0] + BTN_TOGGLE[2]) // 2
        cy = (BTN_TOGGLE[1] + BTN_TOGGLE[3]) // 2
        d.text((cx, cy - 18), tr(lang, "btn_trans_on" if on else "btn_trans_off"),
               font=self._font_mid, fill=COL_TEXT, anchor="mm")
        d.text((cx, cy + 30), tr(lang, "my_to_other"), font=self._font_small,
               fill=COL_TEXT, anchor="mm")
        self._lang_block(d, BTN_PREV, BTN_LANG, BTN_NEXT,
                         self._state.target_language, tr(lang, "out_lang"))

        sub_on = self._state.subtitles_on
        d.rounded_rectangle(BTN_SUB_TOGGLE, 18, fill=COL_SUB_ON if sub_on else COL_BTN)
        cx = (BTN_SUB_TOGGLE[0] + BTN_SUB_TOGGLE[2]) // 2
        cy = (BTN_SUB_TOGGLE[1] + BTN_SUB_TOGGLE[3]) // 2
        d.text((cx, cy - 18), tr(lang, "btn_sub_on" if sub_on else "btn_sub_off"),
               font=self._font_mid, fill=COL_TEXT, anchor="mm")
        d.text((cx, cy + 30), tr(lang, "other_to_sub"), font=self._font_small,
               fill=COL_TEXT, anchor="mm")
        self._lang_block(d, BTN_SUB_PREV, BTN_SUB_LANG, BTN_SUB_NEXT,
                         self._state.inbound_language, tr(lang, "sub_lang"))
        return img

    # ---------------- transforms ----------------
    def _load_transform(self) -> np.ndarray:
        try:
            rows = json.loads(TRANSFORM_PATH.read_text(encoding="utf-8"))
            m = np.identity(4)
            for r in range(3):
                for c in range(4):
                    m[r][c] = float(rows[r][c])
            log.info("wrist panel: restored saved position")
            return m
        except FileNotFoundError:
            return self._watch_matrix()
        except Exception:
            log.warning("wrist panel: invalid saved transform - using defaults", exc_info=True)
            return self._watch_matrix()

    @staticmethod
    def _save_transform(m: np.ndarray, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = [[float(m[r][c]) for c in range(4)] for r in range(3)]
            path.write_text(json.dumps(rows), encoding="utf-8")
        except Exception:
            log.warning("failed to save transform to %s", path, exc_info=True)

    @staticmethod
    def _translate(x: float, y: float, z: float) -> np.ndarray:
        m = np.identity(4)
        m[0][3], m[1][3], m[2][3] = x, y, z
        return m

    @staticmethod
    def _laser_base() -> np.ndarray:
        a = math.radians(-90.0)
        m = np.identity(4)
        m[1][1] = math.cos(a)
        m[1][2] = -math.sin(a)
        m[2][1] = math.sin(a)
        m[2][2] = math.cos(a)
        m[2][3] = -LASER_LEN_M / 2
        return m

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

    @staticmethod
    def _pose_to_np(pose) -> np.ndarray:
        m = pose.mDeviceToAbsoluteTracking
        out = np.identity(4)
        for r in range(3):
            for c in range(4):
                out[r][c] = m[r][c]
        return out

    @staticmethod
    def _np_to_hmd34(openvr, m: np.ndarray):
        t = openvr.HmdMatrix34_t()
        for r in range(3):
            for c in range(4):
                t[r][c] = float(m[r][c])
        return t
