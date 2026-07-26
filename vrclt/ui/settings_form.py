"""Settings-tab form engine: builds the config form and reads it back.

Collaborators (controller, tr, target layout, device lists, hotkey-capture
hooks) arrive by constructor injection - this module never reaches back into
the main window.

Field layout and widget metadata (ranges, steps, units) live in
settings_schema.GROUPS; numeric fields render as spinboxes, so most invalid
input is impossible. What can still fail at readback (partial text in the
nullable roll field, a future free-text kind) is collected per field into
SettingsValidationError instead of aborting on the first bad value.
"""
import copy
import logging

from PySide6 import QtCore, QtGui, QtWidgets

from .. import config as config_mod
from .. import i18n
from . import settings_schema
from .settings_schema import FieldSpec
from .widgets import (
    AxesField,
    HotkeyEdit,
    NoWheelComboBox,
    NoWheelDoubleSpinBox,
    NoWheelSpinBox,
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


def _widen_range(spin, value: float) -> None:
    """Never let a spinbox clamp (and later save back) an out-of-range value
    the user put in the config file by hand."""
    if value < spin.minimum():
        log.warning("config value %s below widget range, widening", value)
        spin.setMinimum(value)
    elif value > spin.maximum():
        log.warning("config value %s above widget range, widening", value)
        spin.setMaximum(value)


class FieldValueError(ValueError):
    def __init__(self, path: str, label_key: str, detail: str):
        super().__init__(f"{path}: {detail}")
        self.path = path
        self.label_key = label_key
        self.detail = detail


class SettingsValidationError(ValueError):
    def __init__(self, errors: list[FieldValueError]):
        super().__init__("; ".join(str(e) for e in errors))
        self.errors = errors


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
        self._fields: dict[str, tuple] = {}          # path -> (widget, spec)
        self._rows: dict[str, tuple] = {}            # path -> (spec, form, label, widget)
        self._groups: list[tuple] = []               # (group_box, [paths])
        self._invalid_widgets: list = []
        self._inputs: list[str] = [""]
        self._outputs: list[str] = [""]
        self._chk_autolaunch: QtWidgets.QCheckBox | None = None
        self._filter_text = ""

    # ---------------- construction ----------------
    def populate(self) -> None:
        clear_layout(self._layout)
        self._fields.clear()
        self._rows.clear()
        self._groups = []
        self._invalid_widgets = []
        self._inputs, self._outputs = self._get_devices()
        cfg = self._controller.raw_cfg
        for title_key, specs in settings_schema.GROUPS:
            group, form = self._add_group(title_key, specs, cfg)
            if title_key == "grp_steamvr":
                self._add_steamvr_autolaunch(form)
        self._layout.addStretch(1)
        if self._filter_text:  # rebuilds (save/language change) keep the filter
            self.apply_filter(self._filter_text)

    def _add_group(self, title_key: str, specs, cfg: dict):
        group = QtWidgets.QGroupBox(self._tr(title_key))
        form = QtWidgets.QFormLayout(group)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        paths = []
        for spec in specs:
            widget = self._make_field(spec, config_mod.get_path(cfg, spec.path))
            self._fields[spec.path] = (widget, spec)
            form.addRow(self._tr(spec.label_key), widget)
            label = form.labelForField(widget)
            self._rows[spec.path] = (spec, form, label, widget)
            paths.append(spec.path)
            self._apply_tip(label, widget, spec)
            self._install_reset_menu(label, widget, spec)
        self._layout.addWidget(group)
        self._groups.append((group, paths))
        return group, form

    def _apply_tip(self, label, widget, spec: FieldSpec) -> None:
        """Tooltip = optional f.<path>.tip help + the field's default value
        (skipped for empty-string defaults - passwords, device names)."""
        parts = []
        tip_key = spec.label_key + ".tip"
        if i18n.has(tip_key):
            parts.append(self._tr(tip_key))
        default_text = self._format_default(spec)
        if default_text is not None:
            parts.append(self._tr("default_prefix").format(value=default_text))
        if not parts:
            return
        tip = "\n".join(parts)
        widget.setToolTip(tip)
        if label is not None:
            label.setToolTip(tip)

    def _format_default(self, spec: FieldSpec) -> str | None:
        value = settings_schema.default_for(spec.path)
        if value is None:
            return self._tr("val_auto") if spec.kind == "nullable_float" else None
        if isinstance(value, bool):
            return "ON" if value else "OFF"
        if isinstance(value, list):
            text = as_csv(value)
            return text or None
        text = str(value)
        return text if text.strip() else None

    def _install_reset_menu(self, label, widget, spec: FieldSpec) -> None:
        """Right-click on the row label -> reset this field to its default.
        The menu lives on the label so the field widgets keep their native
        context menus (copy/paste on line edits)."""
        if label is None:
            return
        label.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)

        def show_menu(pos, label=label, widget=widget, spec=spec):
            menu = QtWidgets.QMenu(label)
            action = menu.addAction(self._tr("reset_field"))
            action.triggered.connect(
                lambda: self._set_field_widget_value(
                    widget, spec, settings_schema.default_for(spec.path)))
            menu.exec(label.mapToGlobal(pos))

        label.customContextMenuRequested.connect(show_menu)

    def _add_steamvr_autolaunch(self, form: QtWidgets.QFormLayout) -> None:
        # Live toggle: SteamVR stores the auto-launch state, so this applies
        # immediately (no save/restart) and mirrors SteamVR's own settings.
        self._chk_autolaunch = QtWidgets.QCheckBox()
        self._chk_autolaunch.clicked.connect(self._controller.set_steamvr_auto_launch)
        form.addRow(self._tr("f.steamvr.auto_launch"), self._chk_autolaunch)
        self.sync_steamvr_autolaunch()

    def _make_field(self, spec: FieldSpec, value):
        kind = spec.kind
        if kind == "bool":
            w = QtWidgets.QCheckBox()
            w.setChecked(bool(value))
            return w
        if kind == "int":
            w = NoWheelSpinBox()
            w.setRange(int(spec.min), int(spec.max))
            if spec.step:
                w.setSingleStep(int(spec.step))
            if spec.suffix:
                w.setSuffix(spec.suffix)
            self._set_spin_value(w, spec, value, int)
            return w
        if kind == "float":
            w = NoWheelDoubleSpinBox()
            w.setDecimals(spec.decimals)
            w.setRange(spec.min, spec.max)
            if spec.step:
                w.setSingleStep(spec.step)
            if spec.suffix:
                w.setSuffix(spec.suffix)
            self._set_spin_value(w, spec, value, float)
            return w
        if kind == "nullable_float":
            w = QtWidgets.QLineEdit("" if value is None else str(value))
            validator = QtGui.QDoubleValidator(spec.min, spec.max, spec.decimals)
            validator.setLocale(QtCore.QLocale.c())
            w.setValidator(validator)
            w.setPlaceholderText(self._tr("val_auto"))
            return w
        if kind == "float_csv":
            w = AxesField(spec.axes or ("X", "Y", "Z"), spec.min, spec.max,
                          spec.step or 0.01, spec.decimals, spec.suffix)
            w.set_values(self._coerce_float_list(spec, value))
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
        if kind == "uilang":
            w = NoWheelComboBox()
            w.addItems([""] + list(i18n.LANGS))
            w.setCurrentText(str(value or ""))
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

    def _set_spin_value(self, spin, spec: FieldSpec, value, coerce) -> None:
        try:
            value = coerce(value)
        except (TypeError, ValueError):
            log.warning("bad config value for %s: %r, using default",
                        spec.path, value)
            value = coerce(settings_schema.default_for(spec.path))
        _widen_range(spin, value)
        spin.setValue(value)

    def _coerce_float_list(self, spec: FieldSpec, value) -> list[float]:
        try:
            return [float(v) for v in (value or [])]
        except (TypeError, ValueError):
            log.warning("bad config value for %s: %r, using default",
                        spec.path, value)
            return [float(v) for v in settings_schema.default_for(spec.path)]

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
        for path, (widget, spec) in self._fields.items():
            if focus is not None and (focus is widget or widget.isAncestorOf(focus)):
                continue
            self._set_field_widget_value(
                widget, spec, config_mod.get_path(self._controller.raw_cfg, path))

    def _set_field_widget_value(self, widget, spec: FieldSpec, value) -> None:
        kind = spec.kind
        blocked = widget.blockSignals(True)
        try:
            if kind == "bool":
                widget.setChecked(bool(value))
            elif kind == "int":
                self._set_spin_value(widget, spec, value, int)
            elif kind == "float":
                self._set_spin_value(widget, spec, value, float)
            elif kind == "float_csv":
                widget.set_values(self._coerce_float_list(spec, value))
            elif kind == "language":
                set_language_combo_value(widget, "" if value is None else str(value))
            elif kind == "multiline":
                # the generic setText fallback would AttributeError here
                widget.setPlainText("" if value is None else str(value))
            elif kind == "hotkey":
                widget.setKeySequence(QtGui.QKeySequence("" if value is None else str(value)))
            elif isinstance(widget, QtWidgets.QComboBox):
                widget.setCurrentText("" if value is None else str(value))
            elif kind == "csv":
                widget.setText(as_csv(value))
            else:
                widget.setText("" if value is None else str(value))
        finally:
            widget.blockSignals(blocked)

    def _field_value(self, widget, spec: FieldSpec):
        kind = spec.kind
        if kind == "bool":
            return widget.isChecked()
        if kind in ("int", "float"):
            return widget.value()
        if kind == "nullable_float":
            text = widget.text().strip()
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                raise FieldValueError(spec.path, spec.label_key,
                                      f"not a number: {text!r}")
        if kind == "csv":
            return from_csv(widget.text())
        if kind == "multiline":
            return widget.toPlainText()
        if kind == "float_csv":
            return widget.values()
        if kind == "hotkey":
            return widget.keySequence().toString(
                QtGui.QKeySequence.SequenceFormat.PortableText)
        if kind == "language":
            return code_from_language_combo(widget, [])
        if isinstance(widget, QtWidgets.QComboBox):
            return widget.currentText().strip()
        return widget.text()

    def config_from_fields(self) -> dict:
        """Read every field back into a config dict. Collects all per-field
        failures into one SettingsValidationError (fields stay marked until
        the next successful read)."""
        self.clear_invalid()
        cfg = copy.deepcopy(self._controller.raw_cfg)
        errors: list[FieldValueError] = []
        for path, (widget, spec) in self._fields.items():
            try:
                value = self._field_value(widget, spec)
            except FieldValueError as e:
                errors.append(e)
                continue
            except Exception as e:
                errors.append(FieldValueError(path, spec.label_key, str(e)))
                continue
            config_mod.set_path(cfg, path, value)
        if errors:
            self.mark_invalid([e.path for e in errors])
            raise SettingsValidationError(errors)
        return cfg

    # ---------------- invalid-field marking ----------------
    def mark_invalid(self, paths: list[str]):
        """Red-border the offending widgets; returns the first one so the
        caller can scroll it into view."""
        first = None
        for path in paths:
            row = self._rows.get(path)
            if row is None:
                continue
            widget = row[3]
            self._set_invalid_prop(widget, True)
            self._invalid_widgets.append(widget)
            if first is None:
                first = widget
        return first

    # ---------------- search filter / focus helpers ----------------
    def apply_filter(self, text: str) -> None:
        """Show only rows whose translated label or config path contains the
        needle; groups with no visible rows hide entirely."""
        self._filter_text = text
        needle = text.strip().lower()
        visible_paths = set()
        for path, (spec, form, _label, widget) in self._rows.items():
            visible = (not needle
                       or needle in path.lower()
                       or needle in self._tr(spec.label_key).lower())
            form.setRowVisible(widget, visible)
            if visible:
                visible_paths.add(path)
        for group, paths in self._groups:
            group.setVisible(not needle or any(p in visible_paths for p in paths))

    def focused_field_path(self) -> str | None:
        focus = QtWidgets.QApplication.focusWidget()
        if focus is None:
            return None
        for path, (widget, _spec) in self._fields.items():
            if focus is widget or widget.isAncestorOf(focus):
                return path
        return None

    def focus_field(self, path: str | None) -> None:
        row = self._rows.get(path) if path else None
        if row is not None:
            row[3].setFocus()

    def first_invalid_widget(self):
        return self._invalid_widgets[0] if self._invalid_widgets else None

    def clear_invalid(self) -> None:
        for widget in self._invalid_widgets:
            self._set_invalid_prop(widget, False)
        self._invalid_widgets = []

    @staticmethod
    def _set_invalid_prop(widget, invalid: bool) -> None:
        widget.setProperty("invalid", "true" if invalid else "false")
        widget.style().unpolish(widget)
        widget.style().polish(widget)
