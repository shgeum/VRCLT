"""Shared, refcounted OpenVR context.

openvr.init/shutdown are process-global; with both the wrist menu and the
subtitle overlay running on their own threads, init must happen exactly once
and shutdown only when the last user releases.
"""
import logging
import threading

log = logging.getLogger(__name__)

_lock = threading.Lock()
_count = 0


def acquire():
    """Init OpenVR (overlay app) if needed; returns the openvr module.
    Raises if SteamVR is not available."""
    global _count
    import openvr
    with _lock:
        if _count == 0:
            openvr.init(openvr.VRApplication_Overlay)
            log.info("OpenVR initialized")
        _count += 1
        return openvr


def release() -> None:
    global _count
    with _lock:
        if _count == 0:
            return
        _count -= 1
        if _count == 0:
            try:
                import openvr
                openvr.shutdown()
                log.info("OpenVR shut down")
            except Exception:
                pass
