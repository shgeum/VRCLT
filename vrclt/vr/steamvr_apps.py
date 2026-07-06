"""SteamVR application registration (vrmanifest + auto-launch).

Registering the manifest lists vrclt in SteamVR Settings > Startup/Overlay
Apps; SteamVR itself stores the auto-launch on/off choice, so we only call
setApplicationAutoLaunch when the user flips the toggle - never on startup -
to avoid overriding a choice made in SteamVR's own settings UI.

The release exe filename changes every release (vrclt-v<ver>-windows-x64.exe), so
the manifest content is rewritten on every frozen launch; its *path* is stable
so SteamVR's stored registration stays valid.

All OpenVR calls go through the refcounted openvr_ctx (init/shutdown are
process-global; a private init here would tear down the render thread's
context). Every public function is best-effort and never raises.
"""
import json
import logging
import os
import sys
import tempfile
import threading

from ..config import APPDATA_DIR
from . import openvr_ctx

log = logging.getLogger(__name__)

APP_KEY = "shgeum.vrclt"
MANIFEST_PATH = APPDATA_DIR / "vrclt.vrmanifest"


def registration_supported() -> bool:
    """Only frozen builds register: a dev venv python path in SteamVR's app
    list would break as soon as the venv moves. VRCLT_DEV_VRMANIFEST=1
    overrides for development testing."""
    return bool(getattr(sys, "frozen", False) or os.environ.get("VRCLT_DEV_VRMANIFEST"))


def _manifest_dict() -> dict:
    return {
        "source": "builtin",
        "applications": [{
            "app_key": APP_KEY,
            "launch_type": "binary",
            "binary_path_windows": str(sys.executable),
            "arguments": "run",
            "is_dashboard_overlay": True,  # required for setApplicationAutoLaunch
            "strings": {
                "en_us": {"name": "vrclt",
                          "description": "VRChat / Discord live translator"},
                "ko_kr": {"name": "vrclt",
                          "description": "VRChat / Discord 실시간 번역기"},
                "ja_jp": {"name": "vrclt",
                          "description": "VRChat / Discord リアルタイム翻訳"},
                "zh_cn": {"name": "vrclt",
                          "description": "VRChat / Discord 实时翻译"},
            },
        }],
    }


def write_manifest() -> bool:
    """Atomically (re)write the manifest so the binary path always tracks the
    currently running exe. Needs no OpenVR; safe without SteamVR."""
    try:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(MANIFEST_PATH.parent),
                                   prefix=".vrmanifest-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(_manifest_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, MANIFEST_PATH)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except Exception:
        log.warning("failed to write %s", MANIFEST_PATH, exc_info=True)
        return False


def register() -> bool:
    """Add the manifest to SteamVR (idempotent). SteamVR must be running."""
    if not write_manifest():
        return False
    try:
        openvr = openvr_ctx.acquire()
        try:
            apps = openvr.VRApplications()
            apps.addApplicationManifest(str(MANIFEST_PATH))
            log.info("SteamVR app manifest registered (%s)", APP_KEY)
            return True
        finally:
            openvr_ctx.release()
    except Exception:
        log.warning("SteamVR app registration failed", exc_info=True)
        return False


def unregister() -> bool:
    try:
        openvr = openvr_ctx.acquire()
        try:
            apps = openvr.VRApplications()
            if apps.isApplicationInstalled(APP_KEY):
                apps.setApplicationAutoLaunch(APP_KEY, False)
            apps.removeApplicationManifest(str(MANIFEST_PATH))
            log.info("SteamVR app manifest removed (%s)", APP_KEY)
            return True
        finally:
            openvr_ctx.release()
    except Exception:
        log.warning("SteamVR app unregistration failed", exc_info=True)
        return False


def get_auto_launch() -> bool | None:
    """Live auto-launch state from SteamVR; None when unavailable."""
    try:
        openvr = openvr_ctx.acquire()
        try:
            return bool(openvr.VRApplications().getApplicationAutoLaunch(APP_KEY))
        finally:
            openvr_ctx.release()
    except Exception:
        return None


def set_auto_launch(enabled: bool) -> bool:
    """Flip auto-launch in SteamVR (registers the manifest first so the app
    key exists). Called only on explicit user action."""
    try:
        openvr = openvr_ctx.acquire()
        try:
            apps = openvr.VRApplications()
            if not apps.isApplicationInstalled(APP_KEY):
                if not write_manifest():
                    return False
                apps.addApplicationManifest(str(MANIFEST_PATH))
            apps.setApplicationAutoLaunch(APP_KEY, bool(enabled))
            log.info("SteamVR auto-launch set to %s", bool(enabled))
            return True
        finally:
            openvr_ctx.release()
    except Exception:
        log.warning("failed to set SteamVR auto-launch", exc_info=True)
        return False


class SteamVrAppRegistrar:
    """Registers the manifest once SteamVR is up (or removes it when the
    user opted out). Polls in a daemon thread; exits after the first apply."""

    def __init__(self, steamvr_running, poll_sec: float = 20.0):
        self._steamvr_running = steamvr_running
        self._poll_sec = poll_sec
        self._stop = threading.Event()
        self._thread = None

    def start(self, get_enabled) -> None:
        if not registration_supported():
            log.info("SteamVR app registration skipped (dev build)")
            return
        if self._thread is not None:
            return

        def worker():
            while not self._stop.is_set():
                if self._steamvr_running():
                    if get_enabled():
                        register()
                    else:
                        unregister()
                    return
                self._stop.wait(self._poll_sec)

        self._thread = threading.Thread(target=worker, name="steamvr-registrar",
                                        daemon=True)
        self._thread.start()

    def reapply(self, enabled: bool) -> None:
        """One-shot re-apply after a settings change (fire-and-forget)."""
        if not registration_supported():
            return

        def worker():
            if not self._steamvr_running():
                return
            if enabled:
                register()
            else:
                unregister()

        threading.Thread(target=worker, name="steamvr-registrar-reapply",
                         daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
