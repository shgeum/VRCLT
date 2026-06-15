"""Single VR render thread: owns OpenVR + a hidden OpenGL context.

Why GL: setOverlayRaw leaks compositor shared-textures PER CALL (verified on
this machine: after ~150-300 uploads ALL raw uploads from the process fail
permanently with RequestFailed). With setOverlayTexture we create ONE OpenGL
texture per overlay and update it in place - no per-update IPC, no leak.

GL contexts are thread-bound, so both panels (wrist menu + subtitles) are
ticked by this one thread.
"""
import logging
import threading
import time

import glfw
from OpenGL import GL

from . import openvr_ctx

log = logging.getLogger(__name__)

LOOP_HZ = 30.0
RETRY_SEC = 10.0


class GlTexture:
    """Persistent RGBA texture; the GL context must be current on this thread."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.id = int(GL.glGenTextures(1))
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.id)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)

    def update(self, img) -> None:
        """img: PIL RGBA image of exactly (width, height)."""
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.id)
        GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, self.width, self.height,
                           GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, img.tobytes())
        GL.glFlush()  # make the update visible to the compositor

    def vr_texture(self, openvr):
        t = openvr.Texture_t()
        t.handle = int(self.id)
        t.eType = openvr.TextureType_OpenGL
        t.eColorSpace = openvr.ColorSpace_Auto
        return t

    def delete(self) -> None:
        try:
            GL.glDeleteTextures(1, [self.id])
        except Exception:
            pass


def flip_bounds(openvr):
    """GL textures are bottom-up: flip V so PIL images display upright."""
    b = openvr.VRTextureBounds_t()
    b.uMin, b.vMin, b.uMax, b.vMax = 0.0, 1.0, 1.0, 0.0
    return b


class RenderCtx:
    """Shared per-cycle context handed to panel components."""

    def __init__(self, openvr, ovl, vrsys, poses):
        self.openvr = openvr
        self.ovl = ovl
        self.vrsys = vrsys
        self.poses = poses


class VrRenderer:
    """Drives panel components: each implements setup(ctx) -> bool,
    tick(ctx, now), teardown(ctx)."""

    def __init__(self, components: list):
        self._components = components
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._main, daemon=True, name="vrclt-vr")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=4)
            self._thread = None

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def _main(self) -> None:
        while not self._stop.is_set():
            retry = 2.0
            openvr = None
            window = None
            glfw_up = False
            ctx = None
            ready = []
            try:
                openvr = openvr_ctx.acquire()
            except Exception as e:
                log.info("VR renderer: SteamVR not available (%s) - retrying in %.0fs",
                         type(e).__name__, RETRY_SEC)
                if self._stop.wait(RETRY_SEC):
                    return
                continue
            try:
                if not glfw.init():
                    raise RuntimeError("glfw.init failed")
                glfw_up = True
                glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
                window = glfw.create_window(64, 64, "vrclt-gl", None, None)
                if not window:
                    raise RuntimeError("glfw.create_window failed")
                glfw.make_context_current(window)

                ovl = openvr.IVROverlay()
                vrsys = openvr.IVRSystem()
                poses = (openvr.TrackedDevicePose_t * openvr.k_unMaxTrackedDeviceCount)()
                ctx = RenderCtx(openvr, ovl, vrsys, poses)

                for c in self._components:
                    if c.setup(ctx):
                        ready.append(c)
                if not ready:
                    log.warning("VR renderer: no overlays available (another vrclt "
                                "instance running?) - retrying in %.0fs", RETRY_SEC)
                    retry = RETRY_SEC
                else:
                    log.info("VR renderer running (%d panel(s), GL textures)", len(ready))
                    interval = 1.0 / LOOP_HZ
                    while not self._stop.is_set():
                        t0 = time.time()
                        vrsys.getDeviceToAbsoluteTrackingPose(
                            openvr.TrackingUniverseStanding, 0, poses)
                        for c in ready:
                            c.tick(ctx, t0)
                        elapsed = time.time() - t0
                        if elapsed < interval:
                            self._stop.wait(interval - elapsed)
            except Exception:
                log.exception("VR renderer crashed - reinitializing")
            finally:
                for c in ready:
                    try:
                        c.teardown(ctx)
                    except Exception:
                        pass
                if window is not None:
                    try:
                        glfw.destroy_window(window)
                    except Exception:
                        pass
                if glfw_up:
                    try:
                        glfw.terminate()
                    except Exception:
                        pass
                openvr_ctx.release()
            if self._stop.wait(retry):
                return
