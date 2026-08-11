"""Platform abstraction test.

The macOS/Linux branches cannot be exercised by running on them here, so each
is checked in a subprocess with `sys.platform` faked before vrclt is imported -
which is exactly when platform_support and the config defaults read it. That
catches the mechanical mistakes (wrong path, wrong host API, a Win32-only
feature reported as available); it does not prove the audio stack works on a
real Mac.

The host-API fallback is tested for real against this machine's PortAudio.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PROBE = """
import sys
sys.platform = {platform!r}
sys.path.insert(0, {root!r})
from vrclt import platform_support as ps
from vrclt import config
print(repr(dict(
    windows=ps.IS_WINDOWS, macos=ps.IS_MACOS, linux=ps.IS_LINUX,
    data_dir=str(ps.app_data_dir()).replace(chr(92), "/"),
    host_apis=ps.host_api_order(),
    loopback=ps.default_loopback_device(),
    vrchat=config.DEFAULTS["app"]["profiles"]["vrchat"]["process"],
    discord=config.DEFAULTS["app"]["profiles"]["discord"]["process"],
    tts=config.DEFAULTS["outbound"]["tts_device"],
    aliases=sorted(ps.process_name_aliases("Discord.exe")),
    plain=sorted(ps.process_name_aliases("Google Chrome")),
    hotkeys=ps.supports_global_hotkeys(),
    picker=ps.supports_audio_session_picker(),
    steamvr=ps.supports_steamvr(),
)))
"""


def probe(platform: str) -> dict:
    out = subprocess.run(
        [sys.executable, "-c", PROBE.format(platform=platform, root=str(ROOT))],
        capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0, f"{platform} import failed:\n{out.stderr}"
    return eval(out.stdout.strip())


def check_windows():
    w = probe("win32")
    assert (w["windows"], w["macos"], w["linux"]) == (True, False, False)
    assert w["host_apis"][0] == "Windows WASAPI", w["host_apis"]
    assert w["vrchat"] == "VRChat.exe" and w["discord"] == "Discord.exe"
    assert w["tts"] == "CABLE Input", w["tts"]
    assert w["loopback"] == "CABLE Input"
    assert w["aliases"] == ["discord", "discord.exe"], w["aliases"]
    # a name without .exe still matches the running process on Windows
    assert w["plain"] == ["google chrome", "google chrome.exe"], w["plain"]
    assert w["hotkeys"] and w["picker"] and w["steamvr"]
    assert w["data_dir"].endswith("/vrclt"), w["data_dir"]


def check_macos():
    m = probe("darwin")
    assert (m["windows"], m["macos"], m["linux"]) == (False, True, False)
    assert m["host_apis"] == ("Core Audio",), m["host_apis"]
    # no .exe on macOS process names, and BlackHole replaces VB-Cable
    assert m["vrchat"] == "VRChat" and m["discord"] == "Discord", m
    assert m["tts"] == "BlackHole" == m["loopback"], m["tts"]
    # names are compared as written: a mac binary may contain a dot
    assert m["aliases"] == ["discord.exe"], m["aliases"]
    assert m["plain"] == ["google chrome"], m["plain"]
    # Win32-only features must report themselves off, never raise later
    assert not m["hotkeys"] and not m["steamvr"], m
    assert m["picker"], "macOS lists running .app bundles"
    assert m["data_dir"].endswith("/Library/Application Support/vrclt"), m["data_dir"]


def check_linux():
    ln = probe("linux")
    assert (ln["windows"], ln["macos"], ln["linux"]) == (False, False, True)
    assert ln["host_apis"][0] == "PulseAudio", ln["host_apis"]
    assert ln["vrchat"] == "VRChat" and ln["tts"] == "", ln
    assert not ln["hotkeys"] and not ln["steamvr"] and not ln["picker"]
    assert ln["data_dir"].endswith("/vrclt"), ln["data_dir"]


def check_host_api_fallback():
    """A PortAudio build without the preferred host API must degrade, not raise.
    This one runs for real against the local audio stack."""
    from vrclt import platform_support
    from vrclt.audio import devices

    assert devices.preferred_host_api() is not None, "WASAPI missing on Windows?"
    real_names = devices.device_names()

    original = platform_support.host_api_order
    platform_support.host_api_order = lambda: ("No Such Host API",)
    try:
        assert devices.preferred_host_api() is None
        assert devices.host_api_name(None) == "all host APIs"
        # every lookup still answers instead of raising
        ins, outs = devices.device_names()
        assert len(ins) >= len(real_names[0]), (len(ins), len(real_names[0]))
        assert devices.find_output("") is None       # no API -> no default
        assert devices.extra_settings("No Such Host API") is None
        assert devices.list_devices()                # must not raise
        # a named device is still found through the any-host-API fallback
        named = next((n for n in outs if n), "")
        if named:
            assert devices.find_output(named) is not None, named
        assert devices.find_input_candidates("") , "fallback must offer a mic"
    finally:
        platform_support.host_api_order = original

    assert devices.preferred_host_api() is not None, "restore failed"


def main():
    check_windows()
    check_macos()
    check_linux()
    check_host_api_fallback()
    print("smoke_platform: OK")


main()
