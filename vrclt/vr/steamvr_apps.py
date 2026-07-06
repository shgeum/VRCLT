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
from pathlib import Path

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


def _launch_arguments() -> str:
    if getattr(sys, "frozen", False):
        return "run"
    # dev override: sys.executable is the venv python, which needs the script
    script = Path(__file__).resolve().parents[2] / "run_vrclt.py"
    return f'"{script}" run'


def _manifest_dict() -> dict:
    return {
        "source": "builtin",
        "applications": [{
            "app_key": APP_KEY,
            "launch_type": "binary",
            "binary_path_windows": str(sys.executable),
            "arguments": _launch_arguments(),
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
    """Live auto-launch state from SteamVR; None when unavailable or the
    app is not registered (so an opted-out install shows 'unknown', not
    a toggle that would silently re-register)."""
    try:
        openvr = openvr_ctx.acquire()
        try:
            apps = openvr.VRApplications()
            if not apps.isApplicationInstalled(APP_KEY):
                return None
            return bool(apps.getApplicationAutoLaunch(APP_KEY))
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
    """Keeps SteamVR's app registration in sync with the desired state.

    A single worker thread applies the latest desired value (register or
    unregister) once SteamVR is up, retrying on failure; rapid toggles are
    serialized so the final state always matches the last request."""

    def __init__(self, steamvr_running, poll_sec: float = 20.0):
        self._steamvr_running = steamvr_running
        self._poll_sec = poll_sec
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._desired = None          # bool once known
        self._worker_running = False

    def start(self, get_enabled) -> None:
        if not registration_supported():
            log.info("SteamVR app registration skipped (dev build)")
            return
        # keep binary_path_windows current even if SteamVR never starts
        # this session (the release exe filename changes per version)
        write_manifest()
        self.reapply(bool(get_enabled()))

    def reapply(self, enabled: bool) -> None:
        """Set the desired registration state; applied asynchronously."""
        if not registration_supported() or self._stop.is_set():
            return
        with self._lock:
            self._desired = bool(enabled)
            if self._worker_running:
                return
            self._worker_running = True
        threading.Thread(target=self._worker, name="steamvr-registrar",
                         daemon=True).start()

    def _worker(self) -> None:
        while True:
            if self._stop.is_set():
                with self._lock:
                    self._worker_running = False
                return
            with self._lock:
                desired = self._desired
            if self._steamvr_running():
                ok = register() if desired else unregister()
            else:
                ok = False
            # exit decision and the running flag flip must be atomic, or a
            # reapply() racing the exit could be dropped
            with self._lock:
                if ok and self._desired == desired:
                    self._worker_running = False
                    return
            self._stop.wait(self._poll_sec)

    def stop(self) -> None:
        self._stop.set()
