"""Audio device enumeration and lookup (WASAPI-pinned)."""
import logging

import sounddevice as sd

log = logging.getLogger(__name__)


def wasapi_index() -> int:
    for i, api in enumerate(sd.query_hostapis()):
        if api["name"] == "Windows WASAPI":
            return i
    raise RuntimeError("Windows WASAPI host API not found")


def find_output(name_substr: str) -> int | None:
    """WASAPI output device index whose name contains name_substr ('' = default)."""
    wi = wasapi_index()
    if not name_substr:
        idx = sd.query_hostapis(wi)["default_output_device"]
        return idx if idx >= 0 else None
    for idx, dev in enumerate(sd.query_devices()):
        if dev["hostapi"] == wi and dev["max_output_channels"] > 0 \
                and name_substr.lower() in dev["name"].lower():
            return idx
    return None


def find_input(name_substr: str) -> int | None:
    """WASAPI input device index whose name contains name_substr ('' = default)."""
    wi = wasapi_index()
    if not name_substr:
        idx = sd.query_hostapis(wi)["default_input_device"]
        return idx if idx >= 0 else None
    for idx, dev in enumerate(sd.query_devices()):
        if dev["hostapi"] == wi and dev["max_input_channels"] > 0 \
                and name_substr.lower() in dev["name"].lower():
            return idx
    return None


# WASAPI first (lowest latency); DirectSound then MME are fallbacks that
# tolerate a device already opened by another app (e.g. VRChat using the same
# physical mic). DirectSound has lower latency than MME, so it's tried first.
_INPUT_API_ORDER = ["Windows WASAPI", "Windows DirectSound", "MME"]


def find_input_candidates(name_substr: str) -> list[tuple[int, str]]:
    """Return [(device_index, host_api_name), ...] for the mic across host APIs,
    WASAPI first. '' = each API's default input device."""
    apis = sd.query_hostapis()
    devs = sd.query_devices()
    out: list[tuple[int, str]] = []
    for api_name in _INPUT_API_ORDER:
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
    return out


def list_devices() -> str:
    wi = wasapi_index()
    api = sd.query_hostapis(wi)
    lines = ["WASAPI devices  (* = default)"]
    for idx, dev in enumerate(sd.query_devices()):
        if dev["hostapi"] != wi:
            continue
        kind = []
        if dev["max_input_channels"] > 0:
            kind.append(f"in:{dev['max_input_channels']}")
        if dev["max_output_channels"] > 0:
            kind.append(f"out:{dev['max_output_channels']}")
        mark = "*" if idx in (api["default_input_device"], api["default_output_device"]) else " "
        lines.append(f"{mark} [{idx:3}] {dev['name']}  ({', '.join(kind)}, {int(dev['default_samplerate'])} Hz)")
    cable = find_output("CABLE Input")
    lines.append("")
    lines.append(f"VB-Cable: {'FOUND (device %d)' % cable if cable is not None else 'NOT INSTALLED'}")
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
            extra_settings=sd.WasapiSettings(auto_convert=True))
