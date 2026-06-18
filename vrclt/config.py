"""Configuration: yaml file + env fallback + defaults."""
import os
import sys
import copy
from pathlib import Path

import yaml

from .resources import bundled_font

APP_MODES = ("vrchat", "discord")
CLOSE_ACTIONS = ("tray", "exit")
APPDATA_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "vrclt"

if os.environ.get("VRCLT_CONFIG"):
    CONFIG_PATH = Path(os.environ["VRCLT_CONFIG"])
elif getattr(sys, "frozen", False):
    CONFIG_PATH = APPDATA_DIR / "config.yaml"
else:
    CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

DEFAULTS = {
    "api_key": "",                      # empty -> use GEMINI_API_KEY env var
    "model": "gemini-3.5-live-translate-preview",
    "app": {
        "mode": "vrchat",              # vrchat | discord
        "profiles": {
            "vrchat": {
                "process": "VRChat.exe",
                "ui_mode": "auto",
                "voice_output": True,
                "passthrough_while_translating": False,
                "chatbox": True,
                "osc_control": True,
                "vr_overlay": True,
                "wrist_ui": True,
            },
            "discord": {
                "process": "Discord.exe",
                "ui_mode": "desktop",
                "voice_output": True,
                "passthrough_while_translating": False,
                "chatbox": False,
                "osc_control": False,
                "vr_overlay": False,
                "wrist_ui": False,
            },
        },
    },
    "dashboard": {
        "translation_on": True,         # last Dashboard translation toggle state
        "subtitles_on": True,           # last Dashboard subtitles toggle state
    },
    "outbound": {                       # pipeline A: my voice -> others
        "enabled": True,
        "target_language": "ja",        # BCP-47
        "echo_target_language": False,
        "mic_device": "",               # substring; empty = default input device
        "tts_device": "CABLE Input",    # translated voice -> VB-Cable -> VRChat mic
        "monitor_device": "",           # also play translated voice here ("" = off)
        "text_only": False,              # True = original mic + translated OSC text only
        "voice_output": True,            # False = no translated TTS output
        "passthrough_while_translating": False,  # True = raw mic always -> tts_device
        "chatbox": True,                # send translated text to VRChat chatbox
    },
    "inbound": {                        # pipeline B: others' voices -> me (subtitles)
        "enabled": True,
        "target_language": "ko",
        "languages": ["ko", "en", "ja"],  # wrist menu cycles subtitles through these
        "process": "VRChat.exe",
        "play_audio": False,            # translated speech to my headphones
        "audio_device": "",             # "" = default output
        "vad_enabled": True,            # Silero VAD: send only speech (gate out music)
        "vad_threshold": 0.5,           # 0-1; higher = stricter (more music rejected)
        "vad_hangover_sec": 0.6,        # keep capturing this long after speech stops
    },
    "osc": {
        "ip": "127.0.0.1",
        "port": 9000,
        "throttle_sec": 1.5,
        "notification_sfx": False,
        "show_source": True,            # chatbox: source on top, translation below
        "chunk_display_sec": 4.0,       # per-part display time for split messages
    },
    "overlay": {                        # inbound subtitle overlay (SteamVR)
        "enabled": True,
        "width_m": 0.9,
        "distance_m": 1.2,
        "below_m": 0.35,
        "tilt_deg": -15.0,
        "font": bundled_font("NotoSansCJKsc-Regular.otf"),
        "font_size": 44,
        "display_sec": 7.0,
        "lines": 3,                     # recent finalized lines kept on screen
        "show_source": False,           # also show the original text (small)
    },
    "audio": {
        "send_interval_ms": 100,        # how often mic audio is flushed to the API
        "finalize_silence_sec": 2.0,    # flush a segment after this much transcription silence
        "mic_idle_disconnect_sec": 15.0,
        "voice_rms_threshold": 90.0,    # mic energy gate; raise if noise opens sessions, lower if speech is missed
        "voice_hangover_sec": 2.5,      # keep the turn open this long through pauses (avoids re-speak lag + chopping)
        "echo_guard_multiplier": 4.0,   # gate boost while game audio plays (1.0 = off)
    },
    "control": {                        # in-VR control via avatar parameters (OSC)
        "enabled": True,
        "osc_listen_port": 9001,
        "param_enabled": "VRCLT_Enabled",
        "param_lang": "VRCLT_Lang",
        # VRCLT_Lang int -> index; "yue" (Cantonese) uses the agent-model
        # fallback (stock voice, no voice replication)
        "languages": ["ja", "en", "ko", "zh-Hans", "zh-Hant", "yue", "es", "ru", "fr", "de"],
        "feedback_chatbox": True,       # announce toggle/language changes in chatbox
    },
    "ui": {
        "mode": "auto",                 # auto | vr | desktop
                                        # auto: VR overlays if SteamVR is running
        "lang": "",                     # UI display language: ""=auto | en | ko | ja | zh
                                        # applies to Qt UI and VR wrist menu labels
        "close_action": "tray",         # tray | exit; window close button behavior
    },
    "wrist_ui": {                       # SteamVR wrist watch menu (XSOverlay style)
        "enabled": True,
        "hand": "left",                 # which wrist wears the watch
        "width_m": 0.16,
        "offset": [0.0, 0.02, 0.12],    # x,y,z in controller space (meters)
        "tilt_deg": 0.0,                # extra tilt toward the face
        "roll_deg": None,               # in-plane rotation; None = auto (+90 left / -90 right)
        "pointer_tilt_deg": 50.0,       # laser tilts down from raw controller forward
        "font": bundled_font("NotoSansCJKsc-Bold.otf"),
    },
    "log_level": "INFO",
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = _merge(cfg, yaml.safe_load(f) or {})
    return cfg


def apply_app_profile(cfg: dict, mode: str | None = None) -> dict:
    cfg = copy.deepcopy(cfg)
    app = cfg.setdefault("app", {})
    selected = (mode or app.get("mode") or "vrchat").strip().lower()
    legacy_text_only = selected == "vrc_text"
    if legacy_text_only:
        selected = "vrchat"
        cfg.setdefault("outbound", {})["text_only"] = True
    profiles = _merge(DEFAULTS["app"]["profiles"], app.get("profiles", {}))
    app["profiles"] = profiles
    profile = profiles.get(selected)
    if profile is None:
        valid = ", ".join(sorted(profiles or APP_MODES))
        raise ValueError(f"unknown app mode: {selected!r} (valid: {valid})")

    app["mode"] = selected
    if profile.get("process"):
        cfg.setdefault("inbound", {})["process"] = profile["process"]
    if profile.get("ui_mode"):
        cfg.setdefault("ui", {})["mode"] = profile["ui_mode"]
    if "voice_output" in profile:
        cfg.setdefault("outbound", {})["voice_output"] = bool(profile["voice_output"])
    if "passthrough_while_translating" in profile:
        cfg.setdefault("outbound", {})["passthrough_while_translating"] = bool(
            profile["passthrough_while_translating"])
    if "chatbox" in profile:
        cfg.setdefault("outbound", {})["chatbox"] = bool(profile["chatbox"])
    if "osc_control" in profile:
        cfg.setdefault("control", {})["enabled"] = bool(profile["osc_control"])
    if "vr_overlay" in profile:
        cfg.setdefault("overlay", {})["enabled"] = bool(profile["vr_overlay"])
    if "wrist_ui" in profile:
        cfg.setdefault("wrist_ui", {})["enabled"] = bool(profile["wrist_ui"])
    if selected != "vrchat":
        cfg.setdefault("outbound", {})["text_only"] = False
    _apply_outbound_output_mode(cfg)
    cfg.setdefault("ui", {})["close_action"] = normalize_close_action(
        cfg.get("ui", {}).get("close_action", "tray"))
    return cfg


def normalize_close_action(value: str) -> str:
    value = (value or "").strip().lower()
    return value if value in CLOSE_ACTIONS else "tray"


def _apply_outbound_output_mode(cfg: dict) -> None:
    ob = cfg.setdefault("outbound", {})
    if ob.get("text_only", False):
        ob["voice_output"] = False
        ob["passthrough_while_translating"] = True
        ob["chatbox"] = True
    else:
        ob["voice_output"] = True
        ob["passthrough_while_translating"] = False


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def api_key(cfg: dict) -> str:
    return (cfg.get("api_key") or os.environ.get("GEMINI_API_KEY", "")).strip()


def api_key_validation_error(key: str) -> str | None:
    key = (key or "").strip()
    if not key:
        return None
    lowered = key.lower()
    if "://" in lowered or "github.com" in lowered:
        return "API key must be a Gemini API key, not a URL."
    return None
