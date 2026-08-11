"""Enumerate the processes the inbound tap could capture, best candidates first.

Feeds the settings "capture process" picker: instead of typing an exe name, the
user picks from a list of real applications.

Windows lists the owners of an audio session on the render endpoints - exactly
the apps producing sound right now. Implemented on raw ctypes COM (MMDevice /
IAudioSessionManager2) rather than pycaw+comtypes: no extra dependency, and
nothing for the frozen build to miss. The vtable indices below are the
documented method order of each interface; IUnknown occupies slots 0-2 in all
of them. COM runs on a throwaway thread so this never initializes (or tears
down) an apartment on the Qt/VR thread that calls it.

macOS has no equivalent read-only "who is playing" query without extra
entitlements, so it lists running bundled applications (the ones ProcTap's
ScreenCaptureKit backend can resolve to a bundle ID) and reports none of them
as playing.

Anywhere else the list is empty and the picker degrades to a plain text field.
"""
from __future__ import annotations

import ctypes
import logging
import queue
import threading
from ctypes import POINTER, byref, c_int, c_uint32, c_void_p
from ctypes.wintypes import DWORD

import psutil

from .. import platform_support

log = logging.getLogger(__name__)

CLSCTX_ALL = 0x17
COINIT_APARTMENTTHREADED = 0x2
RPC_E_CHANGED_MODE = -2147417850   # 0x80010106
EDATAFLOW_RENDER = 0
DEVICE_STATE_ACTIVE = 0x1
SESSION_STATE_ACTIVE = 1
ENUMERATE_TIMEOUT_SEC = 3.0


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text: str):
        super().__init__()
        ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(self))


def _guids():
    return (_GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"),   # MMDeviceEnumerator
            _GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}"),   # IMMDeviceEnumerator
            _GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}"))   # IAudioSessionManager2


class _Com:
    """Calls a COM method by vtable index and releases the interface."""

    def __init__(self, ptr: c_void_p):
        self.ptr = ptr

    def _vtable(self):
        return ctypes.cast(self.ptr, POINTER(POINTER(c_void_p)))[0]

    def call(self, index: int, argtypes: list, *args) -> None:
        fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(self._vtable()[index])
        fn(self.ptr, *args)   # WINFUNCTYPE raises OSError on a failed HRESULT

    def release(self) -> None:
        if self.ptr:
            ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)(self._vtable()[2])(self.ptr)
            self.ptr = None


def _session_pids() -> list[tuple[int, bool]]:
    """[(pid, active)] over every session on every active render endpoint."""
    ole32 = ctypes.windll.ole32
    clsid_enum, iid_enum, iid_mgr = _guids()
    found: list[tuple[int, bool]] = []
    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    # RPC_E_CHANGED_MODE: someone already picked another apartment for this
    # thread - COM is usable, but the CoUninitialize below must not run
    initialized = hr >= 0
    try:
        ptr = c_void_p()
        if ole32.CoCreateInstance(byref(clsid_enum), None, CLSCTX_ALL,
                                  byref(iid_enum), byref(ptr)) < 0:
            return found
        devices = _Com(ptr)
        collection = ptr = None
        try:
            ptr = c_void_p()
            devices.call(3, [c_int, DWORD, POINTER(c_void_p)],   # EnumAudioEndpoints
                         EDATAFLOW_RENDER, DEVICE_STATE_ACTIVE, byref(ptr))
            collection = _Com(ptr)
            count = c_uint32()
            collection.call(3, [POINTER(c_uint32)], byref(count))   # GetCount
            for i in range(count.value):
                ptr = c_void_p()
                collection.call(4, [c_uint32, POINTER(c_void_p)], i, byref(ptr))  # Item
                device = _Com(ptr)
                try:
                    found.extend(_device_sessions(device, iid_mgr))
                finally:
                    device.release()
        finally:
            if collection is not None:
                collection.release()
            devices.release()
    finally:
        if initialized:
            ole32.CoUninitialize()
    return found


def _device_sessions(device: _Com, iid_mgr: _GUID) -> list[tuple[int, bool]]:
    found: list[tuple[int, bool]] = []
    ptr = c_void_p()
    try:
        device.call(3, [POINTER(_GUID), DWORD, c_void_p, POINTER(c_void_p)],  # Activate
                    byref(iid_mgr), CLSCTX_ALL, None, byref(ptr))
    except OSError:
        # an endpoint can refuse activation (exclusive-mode owner, driver
        # hiccup); the other endpoints are still worth enumerating
        log.debug("audio sessions: endpoint activation failed", exc_info=True)
        return found
    manager = _Com(ptr)
    enumerator = None
    try:
        ptr = c_void_p()
        manager.call(5, [POINTER(c_void_p)], byref(ptr))   # GetSessionEnumerator
        enumerator = _Com(ptr)
        count = c_int()
        enumerator.call(3, [POINTER(c_int)], byref(count))   # GetCount
        for j in range(count.value):
            ptr = c_void_p()
            enumerator.call(4, [c_int, POINTER(c_void_p)], j, byref(ptr))  # GetSession
            control = _Com(ptr)
            try:
                state = c_int()
                control.call(3, [POINTER(c_int)], byref(state))  # GetState
                pid = DWORD()
                control.call(14, [POINTER(DWORD)], byref(pid))   # 2::GetProcessId
                if pid.value:   # 0 = the system-sounds session
                    found.append((pid.value, state.value == SESSION_STATE_ACTIVE))
            except OSError:
                log.debug("audio sessions: session query failed", exc_info=True)
            finally:
                control.release()
    finally:
        if enumerator is not None:
            enumerator.release()
        manager.release()
    return found


def audio_processes() -> list[tuple[str, bool]]:
    """[(process name, currently playing)] for the capture candidates on this
    platform, deduplicated by name, playing ones first. Empty on any failure -
    the picker stays usable as a plain text field.
    """
    if platform_support.IS_MACOS:
        return _macos_applications()
    if not platform_support.IS_WINDOWS:
        return []
    result: queue.Queue = queue.Queue(maxsize=1)

    def work():
        try:
            result.put(_session_pids())
        except Exception:
            log.debug("audio session enumeration failed", exc_info=True)
            result.put([])

    thread = threading.Thread(target=work, daemon=True, name="vrclt-audio-sessions")
    thread.start()
    try:
        pids = result.get(timeout=ENUMERATE_TIMEOUT_SEC)
    except queue.Empty:
        log.warning("audio session enumeration timed out")
        return []
    return _names_for(pids)


def _macos_applications() -> list[tuple[str, bool]]:
    """Running .app bundles, by executable name.

    A macOS GUI application runs from `<Name>.app/Contents/MacOS/<exe>`, which
    is exactly the shape ProcTap's ScreenCaptureKit backend needs to resolve a
    bundle ID from a PID. Helper processes live under the same path, so keep
    only the executable whose name matches its bundle.
    """
    found: dict[str, bool] = {}
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            exe = proc.info.get("exe") or ""
            name = proc.info.get("name") or ""
            if not name or "/Contents/MacOS/" not in exe:
                continue
            bundle = exe.split("/Contents/MacOS/", 1)[0].rsplit("/", 1)[-1]
            if bundle.endswith(".app") and bundle[:-4] == name:
                found.setdefault(name, False)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return sorted(found.items(), key=lambda item: item[0].lower())


def _names_for(pids: list[tuple[int, bool]]) -> list[tuple[str, bool]]:
    active: dict[str, bool] = {}
    for pid, is_active in pids:
        try:
            name = psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        if name:
            # one process tree can hold several sessions: playing anywhere counts
            active[name] = active.get(name, False) or is_active
    return sorted(active.items(), key=lambda item: (not item[1], item[0].lower()))
