"""Windows global hotkeys for the desktop UI."""
from __future__ import annotations

import ctypes
import logging
import os
import string
import threading
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "option": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
    "meta": MOD_WIN,
    "super": MOD_WIN,
    "cmd": MOD_WIN,
    "command": MOD_WIN,
}

_VK_NAMES = {
    "backspace": 0x08,
    "tab": 0x09,
    "return": 0x0D,
    "enter": 0x0D,
    "pause": 0x13,
    "capslock": 0x14,
    "caps": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "spacebar": 0x20,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "arrowleft": 0x25,
    "up": 0x26,
    "arrowup": 0x26,
    "right": 0x27,
    "arrowright": 0x27,
    "down": 0x28,
    "arrowdown": 0x28,
    "insert": 0x2D,
    "ins": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "print": 0x2C,
    "printscreen": 0x2C,
    "prtsc": 0x2C,
    "scrolllock": 0x91,
    "numlock": 0x90,
    "semicolon": 0xBA,
    ";": 0xBA,
    "=": 0xBB,
    "equal": 0xBB,
    "+": 0xBB,
    ",": 0xBC,
    "comma": 0xBC,
    "-": 0xBD,
    "minus": 0xBD,
    ".": 0xBE,
    "period": 0xBE,
    "/": 0xBF,
    "slash": 0xBF,
    "`": 0xC0,
    "grave": 0xC0,
    "[": 0xDB,
    "bracketleft": 0xDB,
    "\\": 0xDC,
    "backslash": 0xDC,
    "]": 0xDD,
    "bracketright": 0xDD,
    "'": 0xDE,
    "quote": 0xDE,
}

for _idx in range(1, 25):
    _VK_NAMES[f"f{_idx}"] = 0x70 + _idx - 1
for _idx in range(10):
    _VK_NAMES[f"numpad{_idx}"] = 0x60 + _idx
for _letter in string.ascii_lowercase:
    _VK_NAMES[_letter] = ord(_letter.upper())
for _digit in string.digits:
    _VK_NAMES[_digit] = ord(_digit)


@dataclass(frozen=True)
class ParsedHotkey:
    modifiers: int
    vk: int


@dataclass(frozen=True)
class HotkeyRegistration:
    hotkey_id: int
    name: str
    sequence: str
    callback: Callable[[], None]


class HotkeyError(ValueError):
    pass


def _clean_token(value: str) -> str:
    return value.strip().lower().replace(" ", "").replace("_", "")


def parse_hotkey(sequence: str) -> ParsedHotkey | None:
    """Parse a portable Qt key sequence into RegisterHotKey values.

    Empty strings are treated as disabled hotkeys.
    """
    sequence = (sequence or "").strip()
    if not sequence:
        return None

    parts = [part for part in sequence.split("+") if part.strip()]
    modifiers = 0
    key_name = ""
    for raw in parts:
        token = _clean_token(raw)
        if token in _MODIFIERS:
            modifiers |= _MODIFIERS[token]
            continue
        if key_name:
            raise HotkeyError(f"too many keys in {sequence!r}")
        key_name = token

    if not key_name:
        raise HotkeyError(f"missing key in {sequence!r}")
    vk = _VK_NAMES.get(key_name)
    if vk is None:
        raise HotkeyError(f"unsupported key {key_name!r}")
    return ParsedHotkey(modifiers=modifiers, vk=vk)


class WindowsGlobalHotkeys:
    """Register process-wide hotkeys with a private Win32 message loop."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._registrations: list[HotkeyRegistration] = []
        self._lock = threading.Lock()

    def configure(self, registrations: list[HotkeyRegistration]) -> None:
        self.stop()
        registrations = [reg for reg in registrations if (reg.sequence or "").strip()]
        if not registrations:
            return
        if os.name != "nt":
            log.warning("global hotkeys are only supported on Windows")
            return

        with self._lock:
            self._registrations = list(registrations)
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="vrclt-hotkeys")
            self._thread.start()
        self._ready.wait(2.0)

    def stop(self) -> None:
        thread = self._thread
        thread_id = self._thread_id
        if thread is not None and thread.is_alive() and thread_id:
            try:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            except Exception:
                log.debug("failed to stop hotkey message loop", exc_info=True)
            thread.join(timeout=2.0)
        with self._lock:
            self._thread = None
            self._thread_id = 0
            self._registrations = []
            self._ready.set()

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", ctypes.c_void_p),
                ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t),
                ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_ulong),
                ("pt", ctypes.c_long * 2),
            ]

        user32.RegisterHotKey.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        user32.RegisterHotKey.restype = ctypes.c_bool
        user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.UnregisterHotKey.restype = ctypes.c_bool
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        user32.GetMessageW.restype = ctypes.c_int
        user32.PeekMessageW.argtypes = [
            ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        user32.PeekMessageW.restype = ctypes.c_bool

        self._thread_id = int(kernel32.GetCurrentThreadId())
        msg = MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)

        by_id: dict[int, HotkeyRegistration] = {}
        registered_ids: list[int] = []
        try:
            for reg in self._registrations:
                try:
                    parsed = parse_hotkey(reg.sequence)
                except HotkeyError as exc:
                    log.warning("invalid %s hotkey %r: %s", reg.name, reg.sequence, exc)
                    continue
                if parsed is None:
                    continue
                ok = user32.RegisterHotKey(
                    None, reg.hotkey_id, parsed.modifiers | MOD_NOREPEAT, parsed.vk)
                if not ok:
                    err = ctypes.get_last_error()
                    log.warning("failed to register %s hotkey %r (winerr=%s)",
                                reg.name, reg.sequence, err)
                    continue
                registered_ids.append(reg.hotkey_id)
                by_id[reg.hotkey_id] = reg

            self._ready.set()
            while True:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                if msg.message != WM_HOTKEY:
                    continue
                reg = by_id.get(int(msg.wParam))
                if reg is None:
                    continue
                try:
                    reg.callback()
                except Exception:
                    log.exception("hotkey callback failed: %s", reg.name)
        finally:
            for hotkey_id in registered_ids:
                try:
                    user32.UnregisterHotKey(None, hotkey_id)
                except Exception:
                    log.debug("failed to unregister hotkey %s", hotkey_id, exc_info=True)
            self._ready.set()
