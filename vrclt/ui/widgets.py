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
