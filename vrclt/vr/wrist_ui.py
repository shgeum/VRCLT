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

from ..resources import bundled_font, resolve_font_path
from ..state import AppState
from ..i18n import tr, LANGS as UI_LANGS, UI_LANG_LABELS
from .render import GlTexture, flip_bounds

log = logging.getLogger(__name__)

TEX_W, TEX_H = 640, 560
MAX_RAY_M = 1.2

GAZE_ON_DEG = 22.0
GAZE_OFF_DEG = 35.0
GAZE_DIST_M = 0.95

TRANSFORM_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "vrclt" / "wrist_transform.json"

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

BUTTONS = (("toggle", BTN_TOGGLE), ("prev", BTN_PREV), ("next", BTN_NEXT),
           ("sub_toggle", BTN_SUB_TOGGLE), ("sub_prev", BTN_SUB_PREV),
           ("sub_next", BTN_SUB_NEXT), ("edit", BTN_EDIT), ("sub_edit", BTN_SUB_EDIT),
           ("reset", BTN_RESET),
           ("uilang", BTN_UILANG), ("text_only", BTN_TEXT_ONLY))

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
                 hand: str = "left", width_m: float = 0.18,
                 offset=(0.0, 0.02, 0.12), tilt_deg: float = 0.0,
                 roll_deg: float | None = None,
                 transform=None,
                 pointer_tilt_deg: float = 50.0,
                 font_path: str = bundled_font("NotoSansCJKkr-Bold.otf"),
                 on_text_only_toggle=lambda enabled: None,
                 on_transform_changed=lambda matrix, reset=False: None,
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
        self._configured_transform = self._coerce_transform(transform)
        self._on_transform_changed = on_transform_changed
        a = math.radians(-pointer_tilt_deg)
        self._pointer_mat = np.identity(4)
        self._pointer_mat[1][1] = math.cos(a)
        self._pointer_mat[1][2] = -math.sin(a)
        self._pointer_mat[2][1] = math.sin(a)
        self._pointer_mat[2][2] = math.cos(a)
        self._get_status = get_status
        self._on_text_only_toggle = on_text_only_toggle
        font_path = resolve_font_path(font_path, "NotoSansCJKkr-Bold.otf")
        try:
            self._font_big = ImageFont.truetype(font_path, 54)
            self._font_mid = ImageFont.truetype(font_path, 36)
            self._font_small = ImageFont.truetype(font_path, 24)
            self._font_tiny = ImageFont.truetype(font_path, 18)
        except OSError:
            fallback = ImageFont.load_default()
            self._font_big = self._font_mid = self._font_small = self._font_tiny = fallback

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

                    # The wrist panel has its own move mode so subtitle
                    # placement is not affected by watch adjustments.
                    if grip and not self._prev_grip and on_panel and \
                            not self._dragging and self._state.wrist_edit_mode:
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
                            self._on_transform_changed(self._overlay_mat, False)
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
            self._overlay_mat = self._default_watch_matrix()
            self._overlay_mat_inv = np.linalg.inv(self._overlay_mat)
            if self._attached_to != self._invalid:
                ovl.setOverlayTransformTrackedDeviceRelative(
                    self._h, self._attached_to, self._np_to_hmd34(openvr, self._overlay_mat))
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
            st.wrist_edit_mode = not st.wrist_edit_mode
        elif button == "sub_edit":
            st.edit_mode = not st.edit_mode
        elif button == "uilang":
            st.ui_lang = self._cycle(UI_LANGS, st.ui_lang, 1)
        elif button == "text_only":
            self._on_text_only_toggle(not st.text_only)
        elif button == "reset":
            if st.edit_mode:
                st.request_position_reset()
            else:
                self._reset_requested = True

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

    def _fit_font(self, draw, text: str, max_width: float, fonts=None):
        for font in (fonts or (self._font_big, self._font_mid, self._font_small, self._font_tiny)):
            if draw.textlength(text, font=font) <= max_width:
                return font
        return self._font_tiny

    @staticmethod
    def _line_height(draw, font) -> int:
        try:
            box = draw.textbbox((0, 0), "Ag", font=font)
            return max(1, int(box[3] - box[1]))
        except Exception:
            return max(1, int(getattr(font, "size", 20)))

    def _wrap_to_width(self, draw, text: str, font, max_width: float) -> list[str]:
        if draw.textlength(text, font=font) <= max_width:
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
            if draw.textlength(candidate, font=font) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            if draw.textlength(part, font=font) <= max_width:
                line = part
                continue
            chunk = ""
            for ch in part:
                candidate = f"{chunk}{ch}"
                if chunk and draw.textlength(candidate, font=font) > max_width:
                    lines.append(chunk)
                    chunk = ch
                else:
                    chunk = candidate
            line = chunk
        if line:
            lines.append(line)
        return lines or [text]

    def _clip_line(self, draw, text: str, font, max_width: float) -> str:
        if draw.textlength(text, font=font) <= max_width:
            return text
        suffix = "..."
        while text and draw.textlength(text + suffix, font=font) > max_width:
            text = text[:-1]
        return (text + suffix) if text else suffix

    def _draw_fit_text(self, d, box, text: str, *, fonts=None, fill=COL_TEXT,
                       max_lines: int = 1, pad_x: int = 8, pad_y: int = 4,
                       line_spacing: int = 2) -> None:
        x0, y0, x1, y1 = box
        max_width = max(1, x1 - x0 - pad_x * 2)
        max_height = max(1, y1 - y0 - pad_y * 2)
        candidates = fonts or (self._font_mid, self._font_small, self._font_tiny)

        chosen_font = candidates[-1]
        chosen_lines = [text]
        chosen_spacing = 0
        for font in candidates:
            line_h = self._line_height(d, font)
            spacing = line_spacing if max_lines > 1 else 0
            lines = self._wrap_to_width(d, text, font, max_width)
            if len(lines) > max_lines:
                continue
            total_h = len(lines) * line_h + max(0, len(lines) - 1) * spacing
            if total_h <= max_height and all(d.textlength(line, font=font) <= max_width
                                             for line in lines):
                chosen_font = font
                chosen_lines = lines
                chosen_spacing = spacing
                break

        line_h = self._line_height(d, chosen_font)
        lines = self._wrap_to_width(d, text, chosen_font, max_width)
        truncated = len(lines) > max_lines
        lines = lines[:max_lines]
        if truncated and lines:
            lines[-1] = self._clip_line(d, lines[-1], chosen_font, max_width)
        lines = [self._clip_line(d, line, chosen_font, max_width) for line in lines]
        total_h = len(lines) * line_h + max(0, len(lines) - 1) * chosen_spacing
        while len(lines) > 1 and total_h > max_height:
            lines = lines[:-1]
            lines[-1] = self._clip_line(d, lines[-1], chosen_font, max_width)
            total_h = len(lines) * line_h + max(0, len(lines) - 1) * chosen_spacing
        y = (y0 + y1 - total_h) / 2
        cx = (x0 + x1) / 2
        for line in lines:
            d.text((cx, y + line_h / 2), line, font=chosen_font, fill=fill, anchor="mm")
            y += line_h + chosen_spacing

    def _lang_block(self, d, prev_box, lang_box, next_box, code: str, caption: str) -> None:
        for box, label in ((prev_box, "◀"), (next_box, "▶")):
            d.rounded_rectangle(box, 16, fill=COL_BTN)
            d.text(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2),
                   label, font=self._font_mid, fill=COL_TEXT, anchor="mm")
        d.rounded_rectangle(lang_box, 16, fill=(28, 30, 38, 255))
        label = LANG_LABELS.get(code, code)
        self._draw_fit_text(
            d, (lang_box[0] + 4, lang_box[1] + 20, lang_box[2] - 4, lang_box[3] - 54),
            label, fonts=(self._font_big, self._font_mid, self._font_small, self._font_tiny),
            max_lines=1, pad_x=2, pad_y=2)
        self._draw_fit_text(
            d, (lang_box[0] + 4, lang_box[3] - 54, lang_box[2] - 4, lang_box[3] - 8),
            caption, fonts=(self._font_tiny,), fill=COL_DIM, max_lines=1,
            pad_x=2, pad_y=1, line_spacing=0)

    def _render(self, connected: bool, dragging: bool) -> Image.Image:
        lang = self._state.ui_lang
        wrist_edit = self._state.wrist_edit_mode
        sub_edit = self._state.edit_mode
        img = Image.new("RGBA", (TEX_W, TEX_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, TEX_W - 1, TEX_H - 1), 30, fill=COL_BG,
                            outline=COL_DRAG if (dragging or wrist_edit or sub_edit) else None,
                            width=4)

        dot = COL_ON if connected else (110, 110, 110, 255)
        d.ellipse((20, 28, 44, 52), fill=dot)
        d.text((54, 40), "vrclt", font=self._font_tiny, fill=COL_TEXT, anchor="lm")
        # UI display-language cycle
        d.rounded_rectangle(BTN_UILANG, 12, fill=COL_BTN)
        ui_label = UI_LANG_LABELS.get(lang, lang)
        self._draw_fit_text(d, BTN_UILANG, ui_label,
                            fonts=(self._font_small, self._font_tiny), max_lines=1,
                            pad_x=5, pad_y=2, line_spacing=0)
        text_only = self._state.text_only
        d.rounded_rectangle(BTN_TEXT_ONLY, 12, fill=COL_SUB_ON if text_only else COL_BTN)
        text_label = tr(lang, "btn_text_only_on" if text_only else "btn_text_only_off")
        self._draw_fit_text(d, BTN_TEXT_ONLY, text_label,
                            fonts=(self._font_small, self._font_tiny), max_lines=1,
                            pad_x=6, pad_y=2, line_spacing=0)
        d.rounded_rectangle(BTN_EDIT, 12, fill=COL_DRAG if wrist_edit else COL_BTN)
        edit_label = tr(lang, "wrist_moving" if dragging else "wrist_move")
        self._draw_fit_text(d, BTN_EDIT, edit_label,
                            fonts=(self._font_small, self._font_tiny), max_lines=1,
                            pad_x=5, pad_y=2, line_spacing=0)
        d.rounded_rectangle(BTN_SUB_EDIT, 12, fill=COL_DRAG if sub_edit else COL_BTN)
        self._draw_fit_text(d, BTN_SUB_EDIT, tr(lang, "sub_move"),
                            fonts=(self._font_small, self._font_tiny), max_lines=1,
                            pad_x=5, pad_y=2, line_spacing=0)
        d.rounded_rectangle(BTN_RESET, 12, fill=COL_BTN)
        self._draw_fit_text(d, BTN_RESET, tr(lang, "pos_reset"),
                            fonts=(self._font_small, self._font_tiny), max_lines=1,
                            pad_x=5, pad_y=2, line_spacing=0)

        on = self._state.translation_on
        d.rounded_rectangle(BTN_TOGGLE, 18, fill=COL_ON if on else COL_OFF)
        cx = (BTN_TOGGLE[0] + BTN_TOGGLE[2]) // 2
        cy = (BTN_TOGGLE[1] + BTN_TOGGLE[3]) // 2
        self._draw_fit_text(d, (BTN_TOGGLE[0] + 10, BTN_TOGGLE[1] + 36,
                               BTN_TOGGLE[2] - 10, cy + 16),
                            tr(lang, "btn_trans_on" if on else "btn_trans_off"),
                            fonts=(self._font_mid, self._font_small, self._font_tiny),
                            max_lines=1, pad_x=0, pad_y=0)
        self._draw_fit_text(d, (BTN_TOGGLE[0] + 10, cy + 18,
                               BTN_TOGGLE[2] - 10, BTN_TOGGLE[3] - 22),
                            tr(lang, "my_to_other"),
                            fonts=(self._font_small, self._font_tiny),
                            max_lines=1, pad_x=0, pad_y=0, line_spacing=0)
        self._lang_block(d, BTN_PREV, BTN_LANG, BTN_NEXT,
                         self._state.target_language, tr(lang, "out_lang"))

        sub_on = self._state.subtitles_on
        d.rounded_rectangle(BTN_SUB_TOGGLE, 18, fill=COL_SUB_ON if sub_on else COL_BTN)
        cx = (BTN_SUB_TOGGLE[0] + BTN_SUB_TOGGLE[2]) // 2
        cy = (BTN_SUB_TOGGLE[1] + BTN_SUB_TOGGLE[3]) // 2
        self._draw_fit_text(d, (BTN_SUB_TOGGLE[0] + 10, BTN_SUB_TOGGLE[1] + 36,
                               BTN_SUB_TOGGLE[2] - 10, cy + 16),
                            tr(lang, "btn_sub_on" if sub_on else "btn_sub_off"),
                            fonts=(self._font_mid, self._font_small, self._font_tiny),
                            max_lines=1, pad_x=0, pad_y=0)
        self._draw_fit_text(d, (BTN_SUB_TOGGLE[0] + 10, cy + 18,
                               BTN_SUB_TOGGLE[2] - 10, BTN_SUB_TOGGLE[3] - 22),
                            tr(lang, "other_to_sub"),
                            fonts=(self._font_small, self._font_tiny),
                            max_lines=1, pad_x=0, pad_y=0, line_spacing=0)
        self._lang_block(d, BTN_SUB_PREV, BTN_SUB_LANG, BTN_SUB_NEXT,
                         self._state.inbound_language, tr(lang, "sub_lang"))
        return img

    # ---------------- transforms ----------------
    def _load_transform(self) -> np.ndarray:
        if self._configured_transform is not None:
            log.info("wrist panel: restored configured position")
            return self._configured_transform.copy()
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
    def _coerce_transform(rows) -> np.ndarray | None:
        if not rows:
            return None
        try:
            m = np.identity(4)
            for r in range(3):
                for c in range(4):
                    m[r][c] = float(rows[r][c])
            return m
        except Exception:
            log.warning("wrist panel: invalid configured transform - ignoring", exc_info=True)
            return None

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

    def _default_watch_matrix(self) -> np.ndarray:
        if self._configured_transform is not None:
            return self._configured_transform.copy()
        return self._watch_matrix()

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
