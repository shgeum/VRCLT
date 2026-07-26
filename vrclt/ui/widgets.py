"""Small reusable Qt widgets and language-picker helpers."""
from PySide6 import QtCore, QtGui, QtWidgets

from ..languages import (
    language_code_from_text,
    language_label,
    supported_language_options,
)


class NoWheelComboBox(QtWidgets.QComboBox):
    """Ignores wheel events unless the popup is open (combos inside scroll
    areas must not hijack scrolling)."""

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoWheelSpinBox(QtWidgets.QSpinBox):
    """Ignores wheel events unless focused (spinboxes inside scroll areas
    must not hijack scrolling)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setLocale(QtCore.QLocale.c())
        self.setGroupSeparatorShown(False)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoWheelDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    """See NoWheelSpinBox. C locale so text round-trips as '1.5'."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setLocale(QtCore.QLocale.c())
        self.setGroupSeparatorShown(False)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class AxesField(QtWidgets.QWidget):
    """N labeled double-spinboxes in a row (e.g. X/Y/Z for wrist_ui.offset).
    Registered as the form-row widget, so the settings form's focused-widget
    skip (isAncestorOf) covers the child spinboxes unchanged."""

    def __init__(self, axes: tuple, minimum: float, maximum: float,
                 step: float, decimals: int, suffix: str = "", parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._spins: list[NoWheelDoubleSpinBox] = []
        for name in axes:
            layout.addWidget(QtWidgets.QLabel(name))
            spin = NoWheelDoubleSpinBox()
            spin.setRange(minimum, maximum)
            spin.setSingleStep(step)
            spin.setDecimals(decimals)
            if suffix:
                spin.setSuffix(suffix)
            layout.addWidget(spin, 1)
            self._spins.append(spin)

    def values(self) -> list[float]:
        return [spin.value() for spin in self._spins]

    def set_values(self, values) -> None:
        values = list(values or [])
        for spin, value in zip(self._spins, values):
            blocked = spin.blockSignals(True)
            try:
                self._widen_range_if_needed(spin, float(value))
                spin.setValue(float(value))
            finally:
                spin.blockSignals(blocked)

    @staticmethod
    def _widen_range_if_needed(spin, value: float) -> None:
        if value < spin.minimum():
            spin.setMinimum(value)
        elif value > spin.maximum():
            spin.setMaximum(value)


class HotkeyEdit(QtWidgets.QKeySequenceEdit):
    """Key-sequence editor that reports focus so global hotkeys can be
    suspended while the user is capturing a new one."""

    focus_in = QtCore.Signal()
    focus_out = QtCore.Signal()

    def focusInEvent(self, event: QtGui.QFocusEvent) -> None:
        self.focus_in.emit()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.focus_out.emit()


def build_language_picker(placeholder: str = "") -> NoWheelComboBox:
    """Editable combo over the full supported-language catalog with
    contains-matching completion."""
    combo = NoWheelComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
    combo.setMinimumContentsLength(22)
    combo.view().setMinimumWidth(300)
    for code, label in supported_language_options():
        combo.addItem(label, code)
    completer = combo.completer()
    if completer is not None:
        completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QtWidgets.QCompleter.CompletionMode.PopupCompletion)
    combo.setCurrentIndex(-1)
    combo.setEditText("")
    set_language_picker_placeholder(combo, placeholder)
    return combo


def set_language_picker_placeholder(combo: QtWidgets.QComboBox, text: str) -> None:
    line_edit = combo.lineEdit()
    if line_edit is not None:
        line_edit.setPlaceholderText(text)


def set_language_combo_value(combo: QtWidgets.QComboBox, code: str) -> None:
    code = language_code_from_text(code)
    idx = combo.findData(code)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    else:
        combo.setCurrentIndex(-1)
        combo.setEditText(code)


def code_from_language_combo(combo: QtWidgets.QComboBox,
                             fallback_codes: list[str]) -> str:
    text = combo.currentText().strip()
    data = combo.currentData()
    if data and (not text or text == language_label(str(data))):
        return str(data)
    return language_code_from_text(text, fallback_codes)
