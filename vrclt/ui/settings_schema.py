"""Settings-tab schema: every form field as a FieldSpec with widget metadata.

The i18n label key is always f.<path> (and the optional tooltip f.<path>.tip),
so only the config path is stored. Numeric specs carry range/step/decimals/
suffix for the spinbox widgets; the form widens a range when a stored config
value falls outside it rather than silently clamping the user's file.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import config as config_mod


@dataclass(frozen=True)
class FieldSpec:
    path: str
    kind: str
    min: float | None = None
    max: float | None = None
    step: float | None = None
    decimals: int = 2
    suffix: str = ""
    axes: tuple = ()

    @property
    def label_key(self) -> str:
        return f"f.{self.path}"


def _sec(path: str, lo: float, hi: float, step: float = 0.05) -> FieldSpec:
    return FieldSpec(path, "float", min=lo, max=hi, step=step, suffix=" s")


F = FieldSpec

# (group i18n key, fields) - order defines the settings tab layout
GROUPS: tuple = (
    ("grp_api", (
        F("provider", "provider"),
        F("api_key", "password"),
        F("model", "text"),
        F("qwen.api_key", "password"),
        F("qwen.model", "text"),
        F("qwen.endpoint", "qwen_endpoint"),
        F("qwen.workspace_id", "text"),
        F("qwen.voice_clone", "qwen_voice_clone"),
        F("qwen.voice", "text"),
        F("openai.api_key", "password"),
        F("openai.model", "text"),
        F("openai.transcribe_model", "openai_transcribe"),
        F("openai.inbound_transcribe_model", "openai_transcribe"),
        F("openai.noise_reduction", "openai_noise"),
        F("soniox.api_key", "password"),
        F("soniox.model", "text"),
        F("soniox.tts_model", "text"),
        F("soniox.voice", "text"),
        F("soniox.keep_speaker_context", "bool"),
        _sec("soniox.speaker_context_idle_sec", 5.0, 600.0, 5.0),
    )),
    ("grp_app", (
        F("app.mode", "appmode"),
        F("app.profiles.discord.process", "audio_process"),
        F("app.profiles.custom.process", "audio_process"),
    )),
    ("grp_lang", (
        F("outbound.target_language", "language"),
        F("outbound.source_language", "language"),
        F("control.languages", "csv"),
        F("inbound.target_language", "language"),
        F("inbound.source_language", "language"),
        F("inbound.languages", "csv"),
        F("outbound.glossary", "multiline"),
    )),
    ("grp_ui", (
        F("ui.mode", "uimode"),
        F("ui.lang", "uilang"),
    )),
    ("grp_hotkeys", (
        F("hotkeys.enabled", "bool"),
        F("hotkeys.enabled_in_vr", "bool"),
        F("hotkeys.translation_toggle", "hotkey"),
        F("hotkeys.subtitles_toggle", "hotkey"),
        F("hotkeys.translation_hold", "hotkey"),
    )),
    ("grp_dev", (
        F("outbound.mic_device", "input_device"),
        F("outbound.text_only", "bool"),
        F("outbound.tts_device", "output_device"),
        F("outbound.monitor_device", "output_device"),
        F("inbound.audio_device", "output_device"),
        F("inbound.process", "audio_process"),
        F("inbound.allow_system_audio", "bool"),
    )),
    ("grp_audio", (
        F("outbound.tts_gain", "float", min=0.0, max=2.0, step=0.05),
        F("audio.voice_rms_threshold", "float", min=0.0, max=3000.0,
          step=5.0, decimals=1),
        _sec("audio.voice_hangover_sec", 0.0, 30.0),
        _sec("audio.turn_end_silence_sec", 0.1, 10.0),
        _sec("audio.inbound_turn_end_silence_sec", 0.1, 10.0),
        _sec("audio.subtitle_partial_interval_sec", 0.05, 5.0),
        _sec("audio.subtitle_finalize_silence_sec", 0.1, 10.0),
        F("audio.echo_guard_multiplier", "float", min=1.0, max=20.0,
          step=0.5, decimals=1),
        _sec("audio.echo_guard_hold_sec", 0.0, 10.0),
        F("audio.echo_guard_barge_in_multiplier", "float", min=1.0, max=20.0,
          step=0.5, decimals=1),
        F("audio.send_interval_ms", "int", min=10, max=1000, step=10,
          suffix=" ms"),
        _sec("audio.finalize_silence_sec", 0.1, 30.0),
        _sec("audio.mic_idle_disconnect_sec", 0.0, 600.0, step=1.0),
        F("outbound.echo_target_language", "bool"),
        F("inbound.vad_enabled", "bool"),
        F("inbound.vad_threshold", "float", min=0.0, max=1.0, step=0.05),
        _sec("inbound.vad_hangover_sec", 0.0, 10.0),
        F("inbound.play_audio", "bool"),
    )),
    ("grp_osc_vr", (
        F("outbound.chatbox", "bool"),
        F("osc.ip", "text"),
        F("osc.port", "int", min=1, max=65535),
        _sec("osc.throttle_sec", 0.0, 10.0),
        F("osc.notification_sfx", "bool"),
        F("osc.show_source", "bool"),
        F("osc.stream_sentences", "bool"),
        _sec("osc.chunk_display_sec", 0.5, 30.0),
        F("control.enabled", "bool"),
        F("control.osc_listen_port", "int", min=1, max=65535),
        F("control.feedback_chatbox", "bool"),
    )),
    ("grp_overlay_wrist", (
        F("overlay.enabled", "bool"),
        F("overlay.width_m", "float", min=config_mod.OVERLAY_MIN_WIDTH_M,
          max=config_mod.OVERLAY_MAX_WIDTH_M, step=0.05, suffix=" m"),
        F("overlay.height_m", "float", min=config_mod.OVERLAY_MIN_HEIGHT_M,
          max=config_mod.OVERLAY_MAX_HEIGHT_M, step=0.025, decimals=3,
          suffix=" m"),
        F("overlay.distance_m", "float", min=0.3, max=5.0, step=0.05,
          suffix=" m"),
        F("overlay.below_m", "float", min=-1.0, max=2.0, step=0.025,
          decimals=3, suffix=" m"),
        F("overlay.tilt_deg", "float", min=-89.0, max=89.0, step=1.0,
          decimals=1, suffix=" °"),
        F("overlay.font_size", "int", min=config_mod.OVERLAY_FONT_MIN,
          max=config_mod.OVERLAY_FONT_MAX, suffix=" px"),
        _sec("overlay.display_sec", 1.0, 60.0, step=0.5),
        F("overlay.lines", "int", min=1, max=10),
        F("overlay.show_source", "bool"),
        F("wrist_ui.enabled", "bool"),
        F("wrist_ui.hand", "hand"),
        F("wrist_ui.width_m", "float", min=0.05, max=0.5, step=0.01,
          decimals=3, suffix=" m"),
        F("wrist_ui.offset", "float_csv", min=-0.5, max=0.5, step=0.005,
          decimals=4, suffix=" m", axes=("X", "Y", "Z")),
        F("wrist_ui.tilt_deg", "float", min=0.0, max=360.0, step=1.0,
          decimals=3, suffix=" °"),
        F("wrist_ui.roll_deg", "nullable_float", min=-360.0, max=360.0,
          decimals=3),
        F("wrist_ui.pointer_tilt_deg", "float", min=0.0, max=90.0, step=1.0,
          decimals=1, suffix=" °"),
    )),
    ("grp_steamvr", (
        F("steamvr.register", "bool"),
        F("steamvr.dashboard_panel", "bool"),
    )),
)

# Categories describe the task a setting serves. Searching spans categories;
# every field remains instantiated so navigation never discards unsaved edits.
CATEGORIES: tuple = (
    ("settings_cat_translation", ("grp_api", "grp_lang")),
    ("settings_cat_devices", ("grp_dev",)),
    ("settings_cat_audio", ("grp_audio",)),
    ("settings_cat_interface", ("grp_app", "grp_ui", "grp_hotkeys")),
    ("settings_cat_vr", ("grp_osc_vr", "grp_overlay_wrist", "grp_steamvr")),
)


def field_provider(path: str) -> str | None:
    """Engine-specific controls; shared options have no provider restriction."""
    if path in ("api_key", "model"):
        return "gemini"
    for provider in ("qwen", "openai", "soniox"):
        if path.startswith(provider + "."):
            return provider
    return None


def default_for(path: str):
    return config_mod.get_path(config_mod.DEFAULTS, path)
