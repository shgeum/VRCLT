"""Audio device enumeration and lookup, pinned to the platform's best host API.

Devices are resolved through `platform_support.host_api_order()` (WASAPI on
Windows, Core Audio on macOS, PulseAudio/ALSA on Linux) rather than a fixed
name, and every lookup degrades to "any host API" if none of the preferred ones
are present - an unusual PortAudio build must not make the app unusable.
"""
import logging

import sounddevice as sd

from .. import platform_support

log = logging.getLogger(__name__)


def preferred_host_api() -> int | None:
    """Index of the best available host API, or None if PortAudio reports
    none of them (then callers fall back to searching every device)."""
    try:
        apis = sd.query_hostapis()
    except Exception:
        log.exception("host API enumeration failed")
        return None
    for name in platform_support.host_api_order():
        for i, api in enumerate(apis):
            if api["name"] == name:
                return i
    return None


def host_api_name(index: int | None) -> str:
    if index is None:
        return "all host APIs"
    try:
        return sd.query_hostapis(index)["name"]
    except Exception:
        return str(index)


def _find(name_substr: str, channels_key: str, default_key: str) -> int | None:
    hi = preferred_host_api()
    if not name_substr:
        if hi is None:
            return None
        idx = sd.query_hostapis(hi)[default_key]
        return idx if idx is not None and idx >= 0 else None
    fallback = None
    for idx, dev in enumerate(sd.query_devices()):
        if dev[channels_key] <= 0 or name_substr.lower() not in dev["name"].lower():
            continue
        if hi is None or dev["hostapi"] == hi:
            return idx
        if fallback is None:
            fallback = idx   # right device, other host API - better than nothing
    return fallback


def find_output(name_substr: str) -> int | None:
    """Output device index whose name contains name_substr ('' = default)."""
    return _find(name_substr, "max_output_channels", "default_output_device")


def find_input(name_substr: str) -> int | None:
    """Input device index whose name contains name_substr ('' = default)."""
    return _find(name_substr, "max_input_channels", "default_input_device")


def find_input_candidates(name_substr: str) -> list[tuple[int, str]]:
    """Return [(device_index, host_api_name), ...] for the mic across host APIs,
    best first. '' = each API's default input device."""
    apis = sd.query_hostapis()
    devs = sd.query_devices()
    out: list[tuple[int, str]] = []
    for api_name in platform_support.host_api_order():
        ai = next((i for i, a in enumerate(apis) if a["name"] == api_name), None)
        if ai is None:
            continue
        if not name_substr:
            di = apis[ai]["default_input_device"]
            if di is not None and di >= 0:
                out.append((di, api_name))
        else:
            for idx, dev in enumerate(devs):
                if dev["hostapi"] == ai and dev["max_input_channels"] > 0 \
                        and name_substr.lower() in dev["name"].lower():
                    out.append((idx, api_name))
                    break
    if out:
        return out
    # no preferred host API carries this mic: accept any that does, so an
    # unexpected PortAudio build still opens the device
    for idx, dev in enumerate(devs):
        if dev["max_input_channels"] > 0 and \
                (not name_substr or name_substr.lower() in dev["name"].lower()):
            out.append((idx, apis[dev["hostapi"]]["name"]))
            break
    return out


def extra_settings(host_api: str | None = None):
    """Host-API-specific stream options, or None where there are none.
    WASAPI auto_convert lets the device pick its own mix format."""
    if not platform_support.IS_WINDOWS:
        return None
    if host_api is not None and host_api != "Windows WASAPI":
        return None
    try:
        return sd.WasapiSettings(auto_convert=True)
    except Exception:
        return None


def device_names() -> tuple[list[str], list[str]]:
    """Full device names for UI pickers: (inputs, outputs). Preferred host API
    only when available, deduped by name, '' (system default) first in each
    list. Never raises - returns ([""], [""]) on enumeration failure."""
    try:
        hi = preferred_host_api()
        ins, outs, seen_i, seen_o = [""], [""], {""}, {""}
        for d in sd.query_devices():
            if hi is not None and d["hostapi"] != hi:
                continue
            name = d["name"]
            if d["max_input_channels"] > 0 and name not in seen_i:
                seen_i.add(name)
                ins.append(name)
            if d["max_output_channels"] > 0 and name not in seen_o:
                seen_o.add(name)
                outs.append(name)
        return ins, outs
    except Exception:
        log.exception("device enumeration failed")
        return [""], [""]


def list_devices() -> str:
    hi = preferred_host_api()
    api = sd.query_hostapis(hi) if hi is not None else None
    lines = [f"{host_api_name(hi)} devices  (* = default)"]
    defaults = (api["default_input_device"], api["default_output_device"]) if api else ()
    for idx, dev in enumerate(sd.query_devices()):
        if hi is not None and dev["hostapi"] != hi:
            continue
        kind = []
        if dev["max_input_channels"] > 0:
            kind.append(f"in:{dev['max_input_channels']}")
        if dev["max_output_channels"] > 0:
            kind.append(f"out:{dev['max_output_channels']}")
        mark = "*" if idx in defaults else " "
        lines.append(f"{mark} [{idx:3}] {dev['name']}  ({', '.join(kind)}, {int(dev['default_samplerate'])} Hz)")
    loopback = platform_support.default_loopback_device()
    lines.append("")
    if loopback:
        found = find_output(loopback)
        lines.append(f"{loopback}: "
                     f"{'FOUND (device %d)' % found if found is not None else 'NOT INSTALLED'}")
    return "\n".join(lines)


def sine_test(device_substr: str, seconds: float = 1.5, freq: float = 440.0) -> None:
    import numpy as np
    idx = find_output(device_substr)
    if idx is None:
        raise RuntimeError(f"output device not found: {device_substr!r}")
    rate = 48000
    t = np.arange(int(rate * seconds)) / rate
    wave = (0.3 * np.sin(2 * np.pi * freq * t) * 32767).astype("int16")
    log.info("sine test -> [%d] %s", idx, sd.query_devices(idx)["name"])
    sd.play(wave, samplerate=rate, device=idx, blocking=True,
            extra_settings=extra_settings())
