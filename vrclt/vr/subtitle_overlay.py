"""HMD-locked subtitle panel (component of the VR render thread).

- Fixed-size dark panel, newest lines at the bottom, live partial in grey.
  Hidden when empty or subtitles are OFF.
- Transform: LOOK at the panel (it brightens), hold GRIP inside to move.
  Hold TRIGGER on the bottom-right handle to resize freely.
- A visible laser/cursor is shown in subtitle edit mode for targeting.
- Texture is a persistent OpenGL texture (see vr/render.py for why), updated
  only when the visible content actually changes.
"""
import json
import logging
import math
import os
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ..i18n import tr
from ..resources import bundled_font, resolve_font_path
from ..state import AppState
from ..subtitles import SubtitleStore
from .font_fallback import load_fallback_font
from .render import GlTexture, flip_bounds

log = logging.getLogger(__name__)

TEX_W, TEX_H = 960, 240
LASER_TEX_W, LASER_TEX_H = 4, 512
LASER_WIDTH_M = 0.004
LASER_LEN_M = LASER_WIDTH_M * LASER_TEX_H / LASER_TEX_W
CURSOR_SIZE_M = 0.018
MIN_WIDTH_M = 0.45
MAX_WIDTH_M = 1.6
MIN_HEIGHT_M = 0.10
MAX_HEIGHT_M = 0.60
MIN_TEX_H = 96
MAX_TEX_H = 720
HANDLE_PX = 46
HANDLE_M = 0.07
RESIZE_HANDLE_M = 0.12

GAZE_ON_DEG = 25.0
GAZE_OFF_DEG = 40.0

TRANSFORM_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "vrclt" / "subtitle_transform.json"

COL_FINAL = (255, 255, 255, 255)
COL_PARTIAL = (190, 190, 190, 255)
COL_SRC = (160, 170, 200, 255)
STROKE = (0, 0, 0, 255)


class SubtitlePanel:
    def __init__(self, store: SubtitleStore, state: AppState, *,
                 hand: str = "left",  # watch hand; the OTHER hand grabs
                 width_m: float = 0.9, height_m: float | None = None,
                 distance_m: float = 1.2, below_m: float = 0.35,
                 tilt_deg: float = -15.0,
                 transform=None,
                 pointer_tilt_deg: float = 50.0,
                 font_path: str = bundled_font("NotoSansCJKkr-Regular.otf"),
                 font_size: int = 36, show_source: bool = False,
                 on_transform_changed=lambda matrix, reset=False: None,
                 on_size_changed=lambda width_m, height_m: None):
        self._store = store
        self._state = state
        self._pointer_hand = "right" if hand == "left" else "left"
        try:
            width_val = float(width_m)
        except Exception:
            width_val = 0.9
        try:
            fallback_height = width_val * TEX_H / TEX_W
            height_val = float(height_m or fallback_height)
        except Exception:
            height_val = width_val * TEX_H / TEX_W
        self._width_m, self._height_m, self._tex_h = self._clamp_size_to_texture(
            width_val, height_val)
        self._distance_m = distance_m
        self._below_m = below_m
        self._tilt_deg = tilt_deg
        self._show_source = show_source
        self._configured_transform = self._coerce_transform(transform)
        self._on_transform_changed = on_transform_changed
        self._on_size_changed = on_size_changed
        a = math.radians(-pointer_tilt_deg)
        self._pointer_mat = np.identity(4)
        self._pointer_mat[1][1] = math.cos(a)
        self._pointer_mat[1][2] = -math.sin(a)
        self._pointer_mat[2][1] = math.sin(a)
        self._pointer_mat[2][2] = math.cos(a)
        font_path = resolve_font_path(font_path, "NotoSansCJKkr-Regular.otf")
        self._font = load_fallback_font(font_path, font_size)
        self._font_small = load_fallback_font(font_path, max(20, font_size - 14))

        self._dirty = threading.Event()
        self._reset_requested = False
        self._resize_dirty = False
        self._texture_dirty = False
        store.subscribe(self._dirty.set)
        state.subscribe(self._on_state)

        self._h = self._h_laser = self._h_cursor = None
        self._tex = None

    def _on_state(self, field: str, _value) -> None:
        if field == "reset_positions":
            self._reset_requested = True
        elif field == "edit_mode" and _value:
            self._prev_grip = False
            self._prev_trigger = True
        self._dirty.set()

    # ---------------- component lifecycle ----------------
    def setup(self, ctx) -> bool:
        openvr, ovl = ctx.openvr, ctx.ovl
        created = []
        try:
            for key, name in (("vrclt.subtitles", "vrclt subtitles"),
                              ("vrclt.subtitles.laser", "vrclt subtitle laser"),
                              ("vrclt.subtitles.cursor", "vrclt subtitle cursor")):
                created.append(ovl.createOverlay(key, name))
        except Exception as e:
            for h in created:
                try:
                    ovl.destroyOverlay(h)
                except Exception:
                    pass
            if "KeyInUse" in type(e).__name__:
                log.warning("subtitle panel: overlay key in use - another vrclt instance running?")
                return False
            raise
        self._h, self._h_laser, self._h_cursor = created

        bounds = flip_bounds(openvr)
        ovl.setOverlayWidthInMeters(self._h, self._width_m)
        ovl.setOverlayAlpha(self._h, 0.92)
        ovl.setOverlayTextureBounds(self._h, bounds)
        self._tex = GlTexture(TEX_W, MAX_TEX_H)

        ovl.setOverlayWidthInMeters(self._h_laser, LASER_WIDTH_M)
        ovl.setOverlaySortOrder(self._h_laser, 210)
        ovl.setOverlayTextureBounds(self._h_laser, bounds)
        laser_tex = GlTexture(LASER_TEX_W, LASER_TEX_H)
        laser_tex.update(self._laser_texture())
        ovl.setOverlayTexture(self._h_laser, laser_tex.vr_texture(openvr))
        self._laser_tex = laser_tex

        ovl.setOverlayWidthInMeters(self._h_cursor, CURSOR_SIZE_M)
        ovl.setOverlaySortOrder(self._h_cursor, 211)
        ovl.setOverlayTextureBounds(self._h_cursor, bounds)
        cursor_tex = GlTexture(64, 64)
        cursor_tex.update(self._cursor_texture())
        ovl.setOverlayTexture(self._h_cursor, cursor_tex.vr_texture(openvr))
        self._cursor_tex = cursor_tex

        self._overlay_mat = self._load_transform()
        if self._configured_transform is not None or TRANSFORM_PATH.exists():
            self._on_transform_changed(self._overlay_mat, False)
        ovl.setOverlayTransformTrackedDeviceRelative(
            self._h, openvr.k_unTrackedDeviceIndex_Hmd,
            self._np_to_hmd34(openvr, self._overlay_mat))

        self._pointer_role = openvr.TrackedControllerRole_RightHand \
            if self._pointer_hand == "right" else openvr.TrackedControllerRole_LeftHand
        self._trigger_mask = 1 << int(openvr.k_EButton_SteamVR_Trigger)
        self._grip_mask = 1 << int(openvr.k_EButton_Grip)
        self._invalid = openvr.k_unTrackedDeviceIndexInvalid

        self._visible = False
        self._engaged = False
        self._dragging = False
        self._drag_mode = ""
        self._drag_offset = None
        self._resize_corner = None
        self._resize_anchor = None
        self._resize_basis = None
        self._resize_center = None
        self._resize_base_width = self._width_m
        self._resize_base_height = self._height_m
        self._prev_trigger = True
        self._prev_grip = True
        self._pointer_idx = self._invalid
        self._laser_attached_to = self._invalid
        self._laser_visible = False
        self._cursor_visible = False
        self._last_role_check = 0.0
        self._last_check = 0.0
        self._last_sig = object()  # sentinel != None so the first check renders
        self._dirty.set()
        log.info("subtitle panel ready (GL texture)")
        return True

    def teardown(self, ctx) -> None:
        for h in (self._h, self._h_laser, self._h_cursor):
            if h is None:
                continue
            try:
                ctx.ovl.destroyOverlay(h)
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

        if self._resize_dirty:
            self._resize_dirty = False
            ovl.setOverlayWidthInMeters(self._h, self._width_m)
            log.info("subtitle panel size set to %.2fm x %.2fm", self._width_m, self._height_m)
        self._apply_texture_resize(openvr, ovl)

        if (now - self._last_role_check) > 1.0:
            self._last_role_check = now
            self._pointer_idx = vrsys.getTrackedDeviceIndexForControllerRole(self._pointer_role)
            if self._pointer_idx != self._invalid and self._pointer_idx != self._laser_attached_to:
                ovl.setOverlayTransformTrackedDeviceRelative(
                    self._h_laser, self._pointer_idx,
                    self._np_to_hmd34(openvr, self._pointer_mat @ self._laser_base()))
                self._laser_attached_to = self._pointer_idx

        # ---- gaze + grab (only while visible) ----
        if self._visible:
            hp = poses[openvr.k_unTrackedDeviceIndex_Hmd]
            if hp.bPoseIsValid:
                center = self._overlay_mat @ np.array([0.0, 0.0, 0.0, 1.0])
                dist = float(np.linalg.norm(center[:3]))
                ang = 180.0
                if dist > 1e-6:
                    cosang = float(-center[2] / dist)  # vs HMD forward (-z)
                    ang = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
                if self._dragging:
                    want = True
                elif self._engaged:
                    want = ang < GAZE_OFF_DEG
                else:
                    want = ang < GAZE_ON_DEG
                if want != self._engaged:
                    self._engaged = want
                    ovl.setOverlayAlpha(self._h, 0.98 if want else 0.92)

            # Panel transforms are only active in edit mode - everyday grips
            # (game grabbing, gestures) must never move or resize subtitles.
            if self._state.edit_mode and self._pointer_idx != self._invalid:
                fp = poses[self._pointer_idx]
                if hp.bPoseIsValid and fp.bPoseIsValid:
                    trigger = grip = False
                    try:
                        ok, cs = vrsys.getControllerState(self._pointer_idx)
                        if ok:
                            trigger = bool(cs.ulButtonPressed & self._trigger_mask)
                            grip = bool(cs.ulButtonPressed & self._grip_mask)
                    except Exception:
                        pass
                    h4 = self._pose_to_np(hp)
                    f4 = self._pose_to_np(fp)
                    hit = self._ray_hit(h4, f4)
                    if hit is not None:
                        _mode, _corner, hit_xy = hit
                        cur = self._overlay_mat @ self._translate(hit_xy[0], hit_xy[1], 0.004)
                        ovl.setOverlayTransformTrackedDeviceRelative(
                            self._h_cursor, openvr.k_unTrackedDeviceIndex_Hmd,
                            self._np_to_hmd34(openvr, cur))
                        if not self._cursor_visible:
                            ovl.showOverlay(self._h_cursor)
                            self._cursor_visible = True
                    elif self._cursor_visible:
                        ovl.hideOverlay(self._h_cursor)
                        self._cursor_visible = False
                    if not self._dragging:
                        mode, corner, hit_xy = hit if hit is not None else ("", None, None)
                        if trigger and mode == "resize" and corner is not None:
                            self._start_resize(corner)
                            self._dragging = True
                            self._drag_mode = "resize"
                            self._haptic(vrsys, openvr, self._pointer_idx, 2000)
                            log.info("subtitle panel resize grabbed")
                        elif grip and not self._prev_grip and hit is not None:
                            pointer4 = f4 @ self._pointer_mat
                            self._drag_offset = np.linalg.inv(pointer4) @ h4 @ self._overlay_mat
                            self._dragging = True
                            self._drag_mode = "move"
                            self._haptic(vrsys, openvr, self._pointer_idx, 2000)
                            log.info("subtitle panel grabbed")
                    if self._dragging:
                        active = trigger if self._drag_mode == "resize" else grip
                        if active:
                            if self._drag_mode == "resize":
                                if self._resize_from_ray(h4, f4):
                                    ovl.setOverlayWidthInMeters(self._h, self._width_m)
                                    ovl.setOverlayTransformTrackedDeviceRelative(
                                        self._h, openvr.k_unTrackedDeviceIndex_Hmd,
                                        self._np_to_hmd34(openvr, self._overlay_mat))
                            elif self._drag_offset is not None:
                                self._overlay_mat = (
                                    np.linalg.inv(h4) @ f4 @ self._pointer_mat @ self._drag_offset
                                )
                                ovl.setOverlayTransformTrackedDeviceRelative(
                                    self._h, openvr.k_unTrackedDeviceIndex_Hmd,
                                    self._np_to_hmd34(openvr, self._overlay_mat))
                        else:
                            resized = self._drag_mode == "resize"
                            self._dragging = False
                            self._drag_mode = ""
                            self._drag_offset = None
                            self._resize_corner = None
                            self._resize_anchor = None
                            self._resize_basis = None
                            self._resize_center = None
                            self._save_transform(self._overlay_mat)
                            self._on_transform_changed(self._overlay_mat, False)
                            if resized:
                                self._on_size_changed(self._width_m, self._height_m)
                            self._haptic(vrsys, openvr, self._pointer_idx, 3000)
                            log.info("subtitle panel transformed (saved)"
                                     if resized else "subtitle panel placed (saved)")
                    self._prev_trigger, self._prev_grip = trigger, grip

        want_laser = self._visible and self._state.edit_mode and self._pointer_idx != self._invalid
        if want_laser != self._laser_visible:
            self._laser_visible = want_laser
            (ovl.showOverlay if want_laser else ovl.hideOverlay)(self._h_laser)
        if not want_laser and self._cursor_visible:
            ovl.hideOverlay(self._h_cursor)
            self._cursor_visible = False
        self._apply_texture_resize(openvr, ovl)

        if self._reset_requested and not self._dragging:
            self._reset_requested = False
            self._distance_m = 1.2
            self._below_m = 0.35
            self._tilt_deg = -15.0
            self._configured_transform = None
            self._overlay_mat = self._hmd_matrix()
            ovl.setOverlayTransformTrackedDeviceRelative(
                self._h, openvr.k_unTrackedDeviceIndex_Hmd,
                self._np_to_hmd34(openvr, self._overlay_mat))
            try:
                TRANSFORM_PATH.unlink(missing_ok=True)
            except OSError:
                pass
            self._on_transform_changed(self._overlay_mat, True)
            log.info("subtitle panel position reset to defaults")

        # ---- content updates (texture updated only on real changes) ----
        if self._dirty.is_set() or (now - self._last_check) > 1.0:
            self._dirty.clear()
            self._last_check = now
            has_content, sig, finals, partial, edit = self._render_state()
            if sig != self._last_sig:
                self._last_sig = sig
                if has_content:
                    self._tex.update(self._render(finals, partial, edit))
                    ovl.setOverlayTexture(self._h, self._tex.vr_texture(openvr))
                    if not self._visible:
                        ovl.showOverlay(self._h)
                        self._visible = True
                elif self._visible:
                    ovl.hideOverlay(self._h)
                    self._visible = False
                    self._engaged = False

    def _apply_texture_resize(self, openvr, ovl) -> None:
        if not self._texture_dirty:
            return
        self._texture_dirty = False
        try:
            if self._tex is None:
                self._tex = GlTexture(TEX_W, MAX_TEX_H)
            has_content, sig, finals, partial, edit = self._render_state()
            if has_content:
                self._tex.update(self._render(finals, partial, edit))
                ovl.setOverlayTextureBounds(self._h, flip_bounds(openvr))
                ovl.setOverlayTexture(self._h, self._tex.vr_texture(openvr))
                self._last_sig = sig
                if not self._visible:
                    ovl.showOverlay(self._h)
                    self._visible = True
            else:
                self._last_sig = None
                if self._visible:
                    ovl.hideOverlay(self._h)
                    self._visible = False
                    self._engaged = False
        except Exception:
            log.warning("subtitle panel: failed to redraw resized texture", exc_info=True)

    def _render_state(self):
        edit = self._state.edit_mode
        finals, partial = ([], ("", ""))
        if self._state.subtitles_on:
            finals, partial = self._store.snapshot()
        # In edit mode the panel stays visible (placeholder) so it can be
        # positioned even while nobody is speaking.
        has_content = bool(finals or partial[0] or partial[1]) or edit
        sig = (tuple(finals), partial, edit, self._tex_h) if has_content else None
        return has_content, sig, finals, partial, edit

    @property
    def width_m(self) -> float:
        return self._width_m

    @property
    def height_m(self) -> float:
        return self._height_m

    @staticmethod
    def _texture_height_for_size(width_m: float, height_m: float) -> int:
        aspect_h = max(1e-6, float(height_m)) / max(1e-6, float(width_m))
        return max(MIN_TEX_H, min(MAX_TEX_H, int(round(TEX_W * aspect_h))))

    @staticmethod
    def _clamp_size_to_texture(width_m: float, height_m: float) -> tuple[float, float, int]:
        width_m = max(MIN_WIDTH_M, min(MAX_WIDTH_M, width_m))
        min_h = max(MIN_HEIGHT_M, width_m * MIN_TEX_H / TEX_W)
        max_h = min(MAX_HEIGHT_M, width_m * MAX_TEX_H / TEX_W)
        if max_h < min_h:
            max_h = min_h
        height_m = max(min_h, min(max_h, height_m))
        tex_h = SubtitlePanel._texture_height_for_size(width_m, height_m)
        height_m = width_m * tex_h / TEX_W
        return width_m, height_m, tex_h

    def set_width_m(self, width_m: float) -> float:
        aspect = self._height_m / max(1e-6, self._width_m)
        try:
            width_val = float(width_m)
        except Exception:
            width_val = self._width_m
        self.set_size_m(width_val, width_val * aspect)
        return self._width_m

    def set_size_m(self, width_m: float, height_m: float) -> tuple[float, float]:
        try:
            width_m = float(width_m)
        except Exception:
            width_m = self._width_m
        try:
            height_m = float(height_m)
        except Exception:
            height_m = self._height_m
        width_m, height_m, new_tex_h = self._clamp_size_to_texture(width_m, height_m)
        width_m = self._width_m if abs(width_m - self._width_m) < 1e-6 else round(width_m, 2)
        height_m = self._height_m if abs(height_m - self._height_m) < 1e-6 else round(height_m, 3)
        new_tex_h = self._texture_height_for_size(width_m, height_m)
        if (abs(width_m - self._width_m) < 1e-6
                and abs(height_m - self._height_m) < 1e-6
                and new_tex_h == self._tex_h):
            return self._width_m, self._height_m
        self._width_m = width_m
        self._height_m = height_m
        if new_tex_h != self._tex_h:
            self._tex_h = new_tex_h
            self._texture_dirty = True
        self._resize_dirty = True
        if hasattr(self, "_last_sig"):
            self._last_sig = object()
        self._dirty.set()
        return self._width_m, self._height_m

    def _ray_hit(self, h4: np.ndarray, f4: np.ndarray):
        to_overlay = np.linalg.inv(self._overlay_mat) @ np.linalg.inv(h4) @ f4 @ self._pointer_mat
        origin = to_overlay @ np.array([0.0, 0.0, 0.0, 1.0])
        direction = to_overlay @ np.array([0.0, 0.0, -1.0, 0.0])
        dz = float(direction[2])
        if abs(dz) < 1e-6:
            return None
        t = -float(origin[2]) / dz
        if t < 0.0 or t > 2.0:
            return None
        x = float(origin[0] + t * direction[0])
        y = float(origin[1] + t * direction[1])
        half_w, half_h = self._width_m / 2, self._height_m / 2
        margin = max(0.04, RESIZE_HANDLE_M * 0.55)
        if abs(x) > half_w + margin or abs(y) > half_h + margin:
            return None
        handle_x = min(max(RESIZE_HANDLE_M, half_w * 0.25), half_w + margin)
        handle_y = min(max(0.055, half_h * 0.55), half_h + margin)
        if x >= half_w - handle_x and y <= -half_h + handle_y:
            return "resize", (1, -1), (x, y)
        return "move", None, (x, y)

    def _start_resize(self, corner: tuple[int, int]) -> None:
        self._resize_corner = corner
        self._resize_basis = self._overlay_mat[:3, :3].copy()
        self._resize_center = self._overlay_mat[:3, 3].copy()
        half_w, half_h = self._width_m / 2, self._height_m / 2
        anchor_local = np.array([-half_w, half_h, 0.0, 1.0])
        self._resize_anchor = self._overlay_mat @ anchor_local
        self._resize_base_width = self._width_m
        self._resize_base_height = self._height_m

    def _resize_from_ray(self, h4: np.ndarray, f4: np.ndarray) -> bool:
        if (self._resize_corner is None or self._resize_basis is None
                or self._resize_anchor is None or self._resize_center is None):
            return False
        pointer_h = np.linalg.inv(h4) @ f4 @ self._pointer_mat
        origin_h = (pointer_h @ np.array([0.0, 0.0, 0.0, 1.0]))[:3]
        direction_h = (pointer_h @ np.array([0.0, 0.0, -1.0, 0.0]))[:3]
        normal_h = self._resize_basis[:, 2]
        denom = float(np.dot(direction_h, normal_h))
        if abs(denom) < 1e-6:
            return False
        t = float(np.dot(self._resize_anchor[:3] - origin_h, normal_h) / denom)
        if t < 0.0 or t > 2.5:
            return False
        hit_h = origin_h + direction_h * t
        local_from_anchor = self._resize_basis.T @ (hit_h - self._resize_anchor[:3])
        width_m = float(local_from_anchor[0])
        height_m = -float(local_from_anchor[1])
        old_width, old_height, old_tex_h = self._width_m, self._height_m, self._tex_h
        width_m, height_m = self.set_size_m(width_m, height_m)
        center_delta = np.array([width_m / 2, -height_m / 2, 0.0])
        center_h = self._resize_anchor[:3] + self._resize_basis @ center_delta
        self._overlay_mat[:3, :3] = self._resize_basis
        self._overlay_mat[:3, 3] = center_h
        return (abs(old_width - self._width_m) > 1e-6
                or abs(old_height - self._height_m) > 1e-6
                or old_tex_h != self._tex_h)

    def _draw_resize_handle(self, d: ImageDraw.ImageDraw) -> None:
        active_h = self._tex_h
        top = (MAX_TEX_H - active_h) // 2
        inset = max(10, min(18, active_h // 6))
        length = min(HANDLE_PX * 2, max(24, active_h // 3))
        width = 6
        color = (120, 180, 255, 230)
        x, y = TEX_W - inset, top + active_h - inset
        d.line([(x - length, y), (x, y)], fill=color, width=width)
        d.line([(x, y - length), (x, y)], fill=color, width=width)

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

    def _wrap(self, draw, text: str, font, max_width: int) -> list[str]:
        lines = []
        line = ""
        for ch in text:
            if font.textlength(draw, line + ch) > max_width or ch == "\n":
                if line:
                    lines.append(line)
                line = "" if ch == "\n" else ch
            else:
                line += ch
        if line:
            lines.append(line)
        return lines

    def _render(self, finals, partial, edit: bool = False) -> Image.Image:
        tex_h = self._tex_h
        top = (MAX_TEX_H - tex_h) // 2
        bottom = top + tex_h
        img = Image.new("RGBA", (TEX_W, MAX_TEX_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # FIXED-size panel: no size jumps between updates -> no flicker
        d.rounded_rectangle((4, top + 4, TEX_W - 4, bottom - 4), 20,
                            fill=(10, 10, 12, 185),
                            outline=(70, 110, 180, 255) if edit else None, width=4)
        if edit:
            self._draw_resize_handle(d)

        rows: list[tuple[str, tuple, object]] = []
        for src, dst, _lang in finals:
            if self._show_source and src:
                rows.append((src, COL_SRC, self._font_small))
            rows.append((dst or src, COL_FINAL, self._font))
        p_src, p_dst = partial
        if p_dst or p_src:
            rows.append(((p_dst or p_src), COL_PARTIAL, self._font))
        if edit and not rows:
            rows.append((tr(self._state.ui_lang, "sub_placeholder"), COL_PARTIAL, self._font))

        wrapped: list[tuple[str, tuple, object]] = []
        for text, color, font in rows:
            for line in self._wrap(d, text, font, TEX_W - 56):
                wrapped.append((line, color, font))
        line_h = int(self._font.line_height(d) * 1.3)
        max_rows = max(1, (tex_h - 28) // line_h)
        wrapped = wrapped[-max_rows:]

        y = top + tex_h - 16 - len(wrapped) * line_h
        for line, color, font in wrapped:
            font.draw(d, (TEX_W // 2, y + line_h // 2), line, fill=color,
                      anchor="mm", stroke_width=2, stroke_fill=STROKE)
            y += line_h
        return img

    # ---------------- transforms ----------------
    def _load_transform(self) -> np.ndarray:
        if self._configured_transform is not None:
            log.info("subtitle panel: restored configured position")
            return self._configured_transform.copy()
        try:
            rows = json.loads(TRANSFORM_PATH.read_text(encoding="utf-8"))
            m = np.identity(4)
            for r in range(3):
                for c in range(4):
                    m[r][c] = float(rows[r][c])
            log.info("subtitle panel: restored saved position")
            return m
        except FileNotFoundError:
            return self._hmd_matrix()
        except Exception:
            log.warning("subtitle panel: invalid saved transform - using defaults",
                        exc_info=True)
            return self._hmd_matrix()

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
            log.warning("subtitle panel: invalid configured transform - ignoring", exc_info=True)
            return None

    @staticmethod
    def _save_transform(m: np.ndarray) -> None:
        try:
            TRANSFORM_PATH.parent.mkdir(parents=True, exist_ok=True)
            rows = [[float(m[r][c]) for c in range(4)] for r in range(3)]
            TRANSFORM_PATH.write_text(json.dumps(rows), encoding="utf-8")
        except Exception:
            log.warning("subtitle panel: failed to save transform", exc_info=True)

    def _hmd_matrix(self) -> np.ndarray:
        a = math.radians(self._tilt_deg)
        m = np.identity(4)
        m[1][1] = math.cos(a)
        m[1][2] = -math.sin(a)
        m[2][1] = math.sin(a)
        m[2][2] = math.cos(a)
        m[1][3] = -self._below_m
        m[2][3] = -self._distance_m
        return m

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
