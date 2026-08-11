"""Every OS difference in one place, so the rest of the app stays platform-free.

Windows is the primary target and keeps its exact behavior. macOS and Linux run
the same pipelines with their own audio host API, user-data location and process
naming; Win32-only extras (global hotkeys, the audio-session process picker,
SteamVR) simply report themselves unavailable instead of raising.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

APP_DIR_NAME = "vrclt"

# Audio host APIs to try, best first. On Windows WASAPI has the lowest latency,
# and DirectSound/MME are fallbacks that tolerate a device another app already
# opened (VRChat holding the same physical mic). The other platforms have one
# real choice each, with alternates only for unusual setups.
_HOST_API_ORDER = {
    "win32": ("Windows WASAPI", "Windows DirectSound", "MME"),
    "darwin": ("Core Audio",),
    "linux": ("PulseAudio", "ALSA", "JACK Audio Connection Kit"),
}

# The loopback device that carries translated voice into the target app's mic.
# VB-Cable is Windows-only; BlackHole is the macOS equivalent.
_LOOPBACK_HINT = {
    "win32": "CABLE Input",
    "darwin": "BlackHole",
    "linux": "",          # PulseAudio/PipeWire route without a virtual device
}


def host_api_order() -> tuple[str, ...]:
    """Preferred sounddevice host API names for this platform, best first."""
    return _HOST_API_ORDER.get(_key(), ())


def default_loopback_device() -> str:
    """Default `outbound.tts_device` substring for this platform."""
    return _LOOPBACK_HINT.get(_key(), "")


def _key() -> str:
    if IS_WINDOWS:
        return "win32"
    if IS_MACOS:
        return "darwin"
    return "linux" if IS_LINUX else ""


def app_data_dir() -> Path:
    """Per-user directory for config, logs and the downloaded VAD model."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        return Path(base if base else ".") / APP_DIR_NAME
    if IS_MACOS:
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_DIR_NAME


def executable_suffix() -> str:
    """Suffix worn by executable names in this platform's process list."""
    return ".exe" if IS_WINDOWS else ""


def process_name(basename: str) -> str:
    """'VRChat' -> 'VRChat.exe' on Windows, 'VRChat' elsewhere."""
    return f"{basename}{executable_suffix()}"


def process_name_aliases(name: str) -> set[str]:
    """The spellings of `name` that should match a running process.

    Windows process names carry '.exe' and users type it either way, so both
    forms match there. Elsewhere the name is compared as written - a macOS
    binary may legitimately contain a dot ('Google Chrome Helper').
    """
    name = (name or "").strip().lower()
    if not name:
        return set()
    if not IS_WINDOWS:
        return {name}
    if name.endswith(".exe"):
        return {name, name[:-4]}
    return {name, f"{name}.exe"}


def supports_global_hotkeys() -> bool:
    """Win32 RegisterHotKey. macOS would need an Accessibility-permission
    event tap, which is not wired up yet."""
    return IS_WINDOWS


def supports_audio_session_picker() -> bool:
    """The Core Audio session enumeration behind the capture-process picker."""
    return IS_WINDOWS or IS_MACOS


def supports_steamvr() -> bool:
    """SteamVR overlays. Valve discontinued the macOS runtime, and vrclt has
    never been exercised on Linux SteamVR."""
    return IS_WINDOWS
