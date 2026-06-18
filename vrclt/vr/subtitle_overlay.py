"""HMD-locked subtitle panel (component of the VR render thread).

- Fixed-size dark panel, newest lines at the bottom, live partial in grey.
  Hidden when empty or subtitles are OFF.
- Reposition: LOOK at the panel (it brightens), hold GRIP on the pointer
  hand to grab; release to drop (saved; reset via the wrist panel button).
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
from PIL import Image, ImageDraw, ImageFont

from ..i18n import tr
from ..resources import bundled_font, resolve_font_path
from ..state import AppState
from ..subtitles import SubtitleStore
from .render import GlTexture, flip_bounds

log = logging.getLogger(__name__)

TEX_W, TEX_H = 960, 240

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
                 width_m: float = 0.9, distance_m: float = 1.2, below_m: float = 0.35,
                 tilt_deg: float = -15.0,
                 transform=None,
                 font_path: str = bundled_font("NotoSansCJKkr-Regular.otf"),
                 font_size: int = 36, show_source: bool = False,
                 on_transform_changed=lambda matrix, reset=False: None):
        self._store = store
        self._state = state
        self._pointer_hand = "right" if hand == "left" else "left"
        self._width_m = width_m
        self._height_m = width_m * TEX_H / TEX_W
        self._distance_m = distance_m
        self._below_m = below_m
        self._tilt_deg = tilt_deg
        self._show_source = show_source
        self._configured_transform = self._coerce_transform(transform)
        self._on_transform_changed = on_transform_changed
        font_path = resolve_font_path(font_path, "NotoSansCJKkr-Regular.otf")
        try:
            self._font = ImageFont.truetype(font_path, font_size)
            self._font_small = ImageFont.truetype(font_path, max(20, font_size - 14))
        except OSError:
            self._font = self._font_small = ImageFont.load_default()

        self._dirty = threading.Event()
        self._reset_requested = False
        store.subscribe(self._dirty.set)
        state.subscribe(self._on_state)

        self._h = None
        self._tex = None

    def _on_state(self, field: str, _value) -> None:
        if field == "reset_positions":
            self._reset_requested = True
        self._dirty.set()

    # ---------------- component lifecycle ----------------
    def setup(self, ctx) -> bool:
        openvr, ovl = ctx.openvr, ctx.ovl
        try:
            self._h = ovl.createOverlay("vrclt.subtitles", "vrclt subtitles")
        except Exception as e:
            if "KeyInUse" in type(e).__name__:
                log.warning("subtitle panel: overlay key in use - another vrclt instance running?")
                return False
            raise
        ovl.setOverlayWidthInMeters(self._h, self._width_m)
        ovl.setOverlayAlpha(self._h, 0.92)
        ovl.setOverlayTextureBounds(self._h, flip_bounds(openvr))
        self._tex = GlTexture(TEX_W, TEX_H)

        self._overlay_mat = self._load_transform()
        if self._configured_transform is not None or TRANSFORM_PATH.exists():
            self._on_transform_changed(self._overlay_mat, False)
        ovl.setOverlayTransformTrackedDeviceRelative(
            self._h, openvr.k_unTrackedDeviceIndex_Hmd,
            self._np_to_hmd34(openvr, self._overlay_mat))

        self._pointer_role = openvr.TrackedControllerRole_RightHand \
            if self._pointer_hand == "right" else openvr.TrackedControllerRole_LeftHand
        self._grip_mask = 1 << int(openvr.k_EButton_Grip)
        self._invalid = openvr.k_unTrackedDeviceIndexInvalid

        self._visible = False
        self._engaged = False
        self._dragging = False
        self._drag_offset = None
        self._prev_grip = True
        self._pointer_idx = self._invalid
        self._last_role_check = 0.0
        self._last_check = 0.0
        self._last_sig = object()  # sentinel != None so the first check renders
        self._dirty.set()
        log.info("subtitle panel ready (GL texture)")
        return True

    def teardown(self, ctx) -> None:
        if self._h is not None:
            try:
                ctx.ovl.destroyOverlay(self._h)
            except Exception:
                pass
            self._h = None
        if self._tex is not None:
            self._tex.delete()
            self._tex = None

    # ---------------- per-frame ----------------
    def tick(self, ctx, now: float) -> None:
        openvr, ovl, vrsys, poses = ctx.openvr, ctx.ovl, ctx.vrsys, ctx.poses

        if (now - self._last_role_check) > 1.0:
            self._last_role_check = now
            self._pointer_idx = vrsys.getTrackedDeviceIndexForControllerRole(self._pointer_role)

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

            # panels only move in edit mode - everyday grips (game grabbing,
            # gestures) must never relocate the subtitles
            if self._state.edit_mode and self._pointer_idx != self._invalid:
                fp = poses[self._pointer_idx]
                if hp.bPoseIsValid and fp.bPoseIsValid:
                    grip = False
                    try:
                        ok, cs = vrsys.getControllerState(self._pointer_idx)
                        grip = bool(ok) and bool(cs.ulButtonPressed & self._grip_mask)
                    except Exception:
                        pass
                    h4 = self._pose_to_np(hp)
                    f4 = self._pose_to_np(fp)
                    if grip and not self._prev_grip and not self._dragging:
                        self._drag_offset = np.linalg.inv(f4) @ h4 @ self._overlay_mat
                        self._dragging = True
                        self._haptic(vrsys, openvr, self._pointer_idx, 2000)
                        log.info("subtitle panel grabbed")
                    if self._dragging:
                        if grip and self._drag_offset is not None:
                            self._overlay_mat = np.linalg.inv(h4) @ f4 @ self._drag_offset
                            ovl.setOverlayTransformTrackedDeviceRelative(
                                self._h, openvr.k_unTrackedDeviceIndex_Hmd,
                                self._np_to_hmd34(openvr, self._overlay_mat))
                        else:
                            self._dragging = False
                            self._save_transform(self._overlay_mat)
                            self._on_transform_changed(self._overlay_mat, False)
                            self._haptic(vrsys, openvr, self._pointer_idx, 3000)
                            log.info("subtitle panel placed (saved)")
                    self._prev_grip = grip

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
            edit = self._state.edit_mode
            finals, partial = ([], ("", ""))
            if self._state.subtitles_on:
                finals, partial = self._store.snapshot()
            # in edit mode the panel stays visible (placeholder) so it can be
            # positioned even while nobody is speaking
            has_content = bool(finals or partial[0] or partial[1]) or edit
            sig = (tuple(finals), partial, edit) if has_content else None
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

    @staticmethod
    def _haptic(vrsys, openvr, device_idx, micros: int) -> None:
        if device_idx == openvr.k_unTrackedDeviceIndexInvalid:
            return
        try:
            vrsys.triggerHapticPulse(device_idx, 0, micros)
        except Exception:
            pass

    # ---------------- rendering ----------------
    def _wrap(self, draw, text: str, font, max_width: int) -> list[str]:
        lines = []
        line = ""
        for ch in text:
            if draw.textlength(line + ch, font=font) > max_width or ch == "\n":
                if line:
                    lines.append(line)
                line = "" if ch == "\n" else ch
            else:
                line += ch
        if line:
            lines.append(line)
        return lines

    def _render(self, finals, partial, edit: bool = False) -> Image.Image:
        img = Image.new("RGBA", (TEX_W, TEX_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # FIXED-size panel: no size jumps between updates -> no flicker
        d.rounded_rectangle((4, 4, TEX_W - 4, TEX_H - 4), 20, fill=(10, 10, 12, 185),
                            outline=(70, 110, 180, 255) if edit else None, width=4)

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
        line_h = int(self._font.size * 1.3)
        max_rows = max(1, (TEX_H - 28) // line_h)
        wrapped = wrapped[-max_rows:]

        y = TEX_H - 16 - len(wrapped) * line_h
        for line, color, font in wrapped:
            d.text((TEX_W // 2, y + line_h // 2), line, font=font, fill=color,
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
