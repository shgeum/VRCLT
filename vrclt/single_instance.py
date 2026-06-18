"""Single-instance guard for the Windows desktop app."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

ERROR_ALREADY_EXISTS = 183
MB_ICONINFORMATION = 0x00000040
MB_OK = 0x00000000


class SingleInstance:
    """Prevent duplicate app instances in the current Windows user session."""

    def __init__(self, name: str = "vrclt") -> None:
        self._name = f"Local\\{name}.single-instance"
        self._handle = None
        self.acquired = False

    def __enter__(self) -> "SingleInstance":
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()

    def acquire(self) -> bool:
        if os.name != "nt":
            self.acquired = True
            return True
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, True, self._name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        already_exists = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        if already_exists:
            kernel32.CloseHandle(handle)
            self.acquired = False
            return False
        self._handle = handle
        self.acquired = True
        return True

    def release(self) -> None:
        if os.name == "nt" and self._handle:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel32.ReleaseMutex.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.ReleaseMutex(self._handle)
            kernel32.CloseHandle(self._handle)
        self._handle = None
        self.acquired = False

    @staticmethod
    def notify_duplicate() -> None:
        message = "vrclt is already running."
        if os.name == "nt":
            try:
                ctypes.windll.user32.MessageBoxW(None, message, "vrclt", MB_OK | MB_ICONINFORMATION)
                return
            except Exception:
                pass
        print(message)
