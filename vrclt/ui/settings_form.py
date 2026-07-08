"""Settings-tab form engine: builds the config form and reads it back.

Collaborators (controller, tr, target layout, device lists, hotkey-capture
hooks) arrive by constructor injection - this module never reaches back into
the main window.
"""
import copy
import logging

from PySide6 import QtGui, QtWidgets

from .. import config as config_mod
from .widgets import (
    HotkeyEdit,
    NoWheelComboBox,
    build_language_picker,
    code_from_language_combo,
    set_language_combo_value,
)

log = logging.getLogger(__name__)


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child is not None:
            clear_layout(child)


def as_csv(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


def from_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def from_float_list(value: str) -> list[float]:
    return [float(v.strip()) for v in value.split(",") if v.strip()]


class SettingsForm:
    """Owns the settings scroll body: field registry, construction, config
    sync, and readback into a config dict."""

    def __init__(self, controller, tr, layout: QtWidgets.QVBoxLayout, *,
                 get_devices, on_hotkey_capture_start, on_hotkey_capture_end):
        self._controller = controller
        self._tr = tr
        self._layout = layout
        self._get_devices = get_devices
        self._on_hotkey_capture_start = on_hotkey_capture_start
        self._on_hotkey_capture_end = on_hotkey_capture_end
        self._fields: dict[str, tuple] = {}
        self._inputs: list[str] = [""]
        self._outputs: list[str] = [""]
        self._chk_autolaunch: QtWidgets.QCheckBox | None = None

    # ---------------- construction ----------------
    def populate(self) -> None:
        clear_layout(self._layout)
        self._fields.clear()
        self._inputs, self._outputs = self._get_devices()
        cfg = self._controller.raw_cfg
        self._add_group("grp_api", [
            ("provider", "f.provider", "provider"),
            ("api_key", "f.api_key", "password"),
            ("model", "f.model", "text"),
            ("qwen.api_key", "f.qwen.api_key", "password"),
            ("qwen.model", "f.qwen.model", "text"),
            ("qwen.endpoint", "f.qwen.endpoint", "qwen_endpoint"),
            ("qwen.workspace_id", "f.qwen.workspace_id", "text"),
            ("qwen.voice_clone", "f.qwen.voice_clone", "qwen_voice_clone"),
            ("qwen.voice", "f.qwen.voice", "text"),
            ("app.mode", "f.app.mode", "appmode"),
            ("app.profiles.discord.process", "f.app.profiles.discord.process", "text"),
        ], cfg)
        self._add_group("grp_lang", [
            ("outbound.target_language", "f.outbound.target_language", "language"),
            ("outbound.source_language", "f.outbound.source_language", "language"),
            ("control.languages", "f.control.languages", "csv"),
            ("inbound.target_language", "f.inbound.target_language", "language"),
            ("inbound.source_language", "f.inbound.source_language", "language"),
            ("inbound.languages", "f.inbound.languages", "csv"),
            ("outbound.glossary", "f.outbound.glossary", "multiline"),
        ], cfg)
        self._add_group("grp_ui", [
            ("ui.mode", "f.ui.mode", "uimode"),
            ("ui.lang", "f.ui.lang", "text"),
        ], cfg)
        self._add_group("grp_hotkeys", [
            ("hotkeys.enabled", "f.hotkeys.enabled", "bool"),
            ("hotkeys.enabled_in_vr", "f.hotkeys.enabled_in_vr", "bool"),
            ("hotkeys.translation_toggle", "f.hotkeys.translation_toggle", "hotkey"),
            ("hotkeys.subtitles_toggle", "f.hotkeys.subtitles_toggle", "hotkey"),
            ("hotkeys.translation_hold", "f.hotkeys.translation_hold", "hotkey"),
        ], cfg)
        self._add_group("grp_dev", [
            ("outbound.mic_device", "f.outbound.mic_device", "input_device"),
            ("outbound.text_only", "f.outbound.text_only", "bool"),
            ("outbound.tts_device", "f.outbound.tts_device", "output_device"),
            ("outbound.monitor_device", "f.outbound.monitor_device", "output_device"),
            ("inbound.audio_device", "f.inbound.audio_device", "output_device"),
            ("inbound.process", "f.inbound.process", "text"),
        ], cfg)
        self._add_group("grp_audio", [
            ("outbound.tts_gain", "f.outbound.tts_gain", "float"),
            ("audio.voice_rms_threshold", "f.audio.voice_rms_threshold", "float"),
            ("audio.voice_hangover_sec", "f.audio.voice_hangover_sec", "float"),
            ("audio.turn_end_silence_sec", "f.audio.turn_end_silence_sec", "float"),
            ("audio.inbound_turn_end_silence_sec", "f.audio.inbound_turn_end_silence_sec", "float"),
            ("audio.subtitle_partial_interval_sec", "f.audio.subtitle_partial_interval_sec", "float"),
            ("audio.subtitle_finalize_silence_sec", "f.audio.subtitle_finalize_silence_sec", "float"),
            ("audio.echo_guard_multiplier", "f.audio.echo_guard_multiplier", "float"),
            ("audio.echo_guard_hold_sec", "f.audio.echo_guard_hold_sec", "float"),
            ("audio.echo_guard_barge_in_multiplier", "f.audio.echo_guard_barge_in_multiplier", "float"),
            ("audio.send_interval_ms", "f.audio.send_interval_ms", "int"),
            ("audio.finalize_silence_sec", "f.audio.finalize_silence_sec", "float"),
            ("audio.mic_idle_disconnect_sec", "f.audio.mic_idle_disconnect_sec", "float"),
            ("outbound.echo_target_language", "f.outbound.echo_target_language", "bool"),
            ("inbound.vad_enabled", "f.inbound.vad_enabled", "bool"),
            ("inbound.vad_threshold", "f.inbound.vad_threshold", "float"),
            ("inbound.vad_hangover_sec", "f.inbound.vad_hangover_sec", "float"),
            ("inbound.play_audio", "f.inbound.play_audio", "bool"),
        ], cfg)
        self._add_group("grp_osc_vr", [
            ("outbound.chatbox", "f.outbound.chatbox", "bool"),
            ("osc.ip", "f.osc.ip", "text"),
            ("osc.port", "f.osc.port", "int"),
            ("osc.throttle_sec", "f.osc.throttle_sec", "float"),
            ("osc.notification_sfx", "f.osc.notification_sfx", "bool"),
            ("osc.show_source", "f.osc.show_source", "bool"),
            ("osc.stream_sentences", "f.osc.stream_sentences", "bool"),
            ("osc.chunk_display_sec", "f.osc.chunk_display_sec", "float"),
            ("control.enabled", "f.control.enabled", "bool"),
            ("control.osc_listen_port", "f.control.osc_listen_port", "int"),
            ("control.feedback_chatbox", "f.control.feedback_chatbox", "bool"),
        ], cfg)
        self._add_group("grp_overlay_wrist", [
            ("overlay.enabled", "f.overlay.enabled", "bool"),
            ("overlay.width_m", "f.overlay.width_m", "float"),
            ("overlay.height_m", "f.overlay.height_m", "float"),
            ("overlay.distance_m", "f.overlay.distance_m", "float"),
            ("overlay.below_m", "f.overlay.below_m", "float"),
            ("overlay.tilt_deg", "f.overlay.tilt_deg", "float"),
            ("overlay.font_size", "f.overlay.font_size", "int"),
            ("overlay.display_sec", "f.overlay.display_sec", "float"),
            ("overlay.lines", "f.overlay.lines", "int"),
            ("overlay.show_source", "f.overlay.show_source", "bool"),
            ("wrist_ui.enabled", "f.wrist_ui.enabled", "bool"),
            ("wrist_ui.hand", "f.wrist_ui.hand", "hand"),
            ("wrist_ui.width_m", "f.wrist_ui.width_m", "float"),
            ("wrist_ui.offset", "f.wrist_ui.offset", "float_csv"),
            ("wrist_ui.tilt_deg", "f.wrist_ui.tilt_deg", "float"),
            ("wrist_ui.roll_deg", "f.wrist_ui.roll_deg", "nullable_float"),
            ("wrist_ui.pointer_tilt_deg", "f.wrist_ui.pointer_tilt_deg", "float"),
        ], cfg)
        self._add_steamvr_group(cfg)
        self._layout.addStretch(1)

    def _add_group(self, title_key: str, fields: list[tuple[str, str, str]],
                   cfg: dict) -> None:
        group = QtWidgets.QGroupBox(self._tr(title_key))
        form = QtWidgets.QFormLayout(group)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for path, label_key, kind in fields:
            widget = self._make_field(kind, config_mod.get_path(cfg, path))
            self._fields[path] = (widget, kind)
            form.addRow(self._tr(label_key), widget)
        self._layout.addWidget(group)

    def _add_steamvr_group(self, cfg: dict) -> None:
        group = QtWidgets.QGroupBox(self._tr("grp_steamvr"))
        form = QtWidgets.QFormLayout(group)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for path, label_key, kind in (
                ("steamvr.register", "f.steamvr.register", "bool"),
                ("steamvr.dashboard_panel", "f.steamvr.dashboard_panel", "bool")):
            widget = self._make_field(kind, config_mod.get_path(cfg, path))
            self._fields[path] = (widget, kind)
            form.addRow(self._tr(label_key), widget)
        # Live toggle: SteamVR stores the auto-launch state, so this applies
        # immediately (no save/restart) and mirrors SteamVR's own settings.
        self._chk_autolaunch = QtWidgets.QCheckBox()
        self._chk_autolaunch.clicked.connect(self._controller.set_steamvr_auto_launch)
        form.addRow(self._tr("f.steamvr.auto_launch"), self._chk_autolaunch)
        self._layout.addWidget(group)
        self.sync_steamvr_autolaunch()

    def _make_field(self, kind: str, value):
        if kind == "bool":
            w = QtWidgets.QCheckBox()
            w.setChecked(bool(value))
            return w
        if kind in ("int", "float", "nullable_float"):
            w = QtWidgets.QLineEdit("" if value is None else str(value))
            return w
        if kind == "password":
            w = QtWidgets.QLineEdit("" if value is None else str(value))
            w.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
            return w
        if kind == "csv":
            return QtWidgets.QLineEdit(as_csv(value))
        if kind == "multiline":
            w = QtWidgets.QPlainTextEdit()
            w.setPlainText("" if value is None else str(value))
            w.setFixedHeight(96)
            return w
        if kind == "hotkey":
            w = HotkeyEdit()
            w.setKeySequence(QtGui.QKeySequence("" if value is None else str(value)))
            if hasattr(w, "setMaximumSequenceLength"):
                w.setMaximumSequenceLength(1)
            if hasattr(w, "setClearButtonEnabled"):
                w.setClearButtonEnabled(True)
            w.focus_in.connect(self._on_hotkey_capture_start)
            w.focus_out.connect(self._on_hotkey_capture_end)
            return w
        if kind == "language":
            w = build_language_picker()
            set_language_combo_value(w, "" if value is None else str(value))
            return w
        if kind == "float_csv":
            return QtWidgets.QLineEdit(as_csv(value))
        if kind == "appmode":
            w = NoWheelComboBox()
            w.addItems(list(config_mod.APP_MODES))
            w.setCurrentText(str(value or "vrchat"))
            return w
        if kind == "uimode":
            w = NoWheelComboBox()
            w.addItems(["auto", "vr", "desktop"])
            w.setCurrentText(str(value or "auto"))
            return w
        if kind == "hand":
            w = NoWheelComboBox()
            w.addItems(["left", "right"])
            w.setCurrentText(str(value or "left"))
            return w
        if kind == "provider":
            w = NoWheelComboBox()
            w.addItems(list(config_mod.PROVIDERS))
            w.setCurrentText(str(value or "gemini"))
            return w
        if kind == "qwen_endpoint":
            w = NoWheelComboBox()
            w.addItems(list(config_mod.QWEN_ENDPOINTS))
            w.setCurrentText(str(value or "intl"))
            return w
        if kind == "qwen_voice_clone":
            w = NoWheelComboBox()
            w.addItems(list(config_mod.QWEN_VOICE_CLONE_MODES))
            w.setCurrentText(str(value or "once"))
            return w
        if kind in ("input_device", "output_device"):
            w = NoWheelComboBox()
            w.setEditable(True)
            names = self._inputs if kind == "input_device" else self._outputs
            w.addItems(names)
            w.setCurrentText("" if value is None else str(value))
            return w
        return QtWidgets.QLineEdit("" if value is None else str(value))

    # ---------------- sync / readback ----------------
    def sync_steamvr_autolaunch(self) -> None:
        chk = self._chk_autolaunch
        if chk is None:
            return
        value = self._controller.get_steamvr_auto_launch()
        available = value is not None
        if chk.isEnabled() != available:
            chk.setEnabled(available)
            chk.setToolTip("" if available else self._tr("tip_steamvr_unavailable"))
        if available and chk.isChecked() != bool(value):
            blocked = chk.blockSignals(True)
            chk.setChecked(bool(value))
            chk.blockSignals(blocked)

    def sync_from_config(self) -> None:
        focus = QtWidgets.QApplication.focusWidget()
        for path, (widget, kind) in self._fields.items():
            if focus is not None and (focus is widget or widget.isAncestorOf(focus)):
                continue
            self._set_field_widget_value(
                widget, kind, config_mod.get_path(self._controller.raw_cfg, path))

    def _set_field_widget_value(self, widget, kind: str, value) -> None:
        blocked = widget.blockSignals(True)
        try:
            if kind == "bool":
                widget.setChecked(bool(value))
            elif kind == "language":
                set_language_combo_value(widget, "" if value is None else str(value))
            elif kind == "multiline":
                # the generic setText fallback would AttributeError here
                widget.setPlainText("" if value is None else str(value))
            elif kind == "hotkey":
                widget.setKeySequence(QtGui.QKeySequence("" if value is None else str(value)))
            elif isinstance(widget, QtWidgets.QComboBox):
                widget.setCurrentText("" if value is None else str(value))
            elif kind in ("csv", "float_csv"):
                widget.setText(as_csv(value))
            else:
                widget.setText("" if value is None else str(value))
        finally:
            widget.blockSignals(blocked)

    def _field_value(self, widget, kind: str):
        if kind == "bool":
            return widget.isChecked()
        if kind == "int":
            return int(widget.text().strip())
        if kind == "float":
            return float(widget.text().strip())
        if kind == "nullable_float":
            text = widget.text().strip()
            return None if not text else float(text)
        if kind == "csv":
            return from_csv(widget.text())
        if kind == "multiline":
            return widget.toPlainText()
        if kind == "float_csv":
            return from_float_list(widget.text())
        if kind == "hotkey":
            return widget.keySequence().toString(
                QtGui.QKeySequence.SequenceFormat.PortableText)
        if kind == "language":
            return code_from_language_combo(widget, [])
        if isinstance(widget, QtWidgets.QComboBox):
            return widget.currentText().strip()
        return widget.text()

    def config_from_fields(self) -> dict:
        cfg = copy.deepcopy(self._controller.raw_cfg)
        for path, (widget, kind) in self._fields.items():
            config_mod.set_path(cfg, path, self._field_value(widget, kind))
        return cfg
