"""Small reusable Qt widgets and language-picker helpers."""
from PySide6 import QtCore, QtGui, QtWidgets

from ..languages import (
    language_code_from_text,
    language_label,
    supported_language_options,
)
from . import theme


class NoWheelComboBox(QtWidgets.QComboBox):
    """Ignores wheel events unless the popup is open (combos inside scroll
    areas must not hijack scrolling)."""

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


_PLAYING_ICON: "QtGui.QIcon | None" = None


def _playing_icon() -> QtGui.QIcon:
    """Small filled dot marking a process that is playing audio right now."""
    global _PLAYING_ICON
    if _PLAYING_ICON is None:
        pixmap = QtGui.QPixmap(10, 10)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(*theme.ON_GREEN))
        painter.drawEllipse(1, 1, 8, 8)
        painter.end()
        _PLAYING_ICON = QtGui.QIcon(pixmap)
    return _PLAYING_ICON


class AudioProcessCombo(NoWheelComboBox):
    """Editable process picker that re-lists the apps currently holding an
    audio session every time the dropdown opens (they come and go), keeping
    whatever the user typed. Item text stays the bare exe name so reading the
    field back needs no parsing; playing apps sort first, above a separator.
    """

    def __init__(self, list_processes, playing_suffix: str = "", parent=None):
        super().__init__(parent)
        self._list_processes = list_processes
        self._playing_suffix = playing_suffix
        self.setEditable(True)
        self.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)

    def showPopup(self) -> None:
        current = self.currentText()
        self.blockSignals(True)
        try:
            self.clear()
            self.addItem("")
            separated = False
            for name, playing in self._list_processes():
                if not playing and not separated and self.count() > 1:
                    self.insertSeparator(self.count())
                    separated = True
                self.addItem(_playing_icon() if playing else QtGui.QIcon(), name)
                if playing and self._playing_suffix:
                    self.setItemData(self.count() - 1, self._playing_suffix,
                                     QtCore.Qt.ItemDataRole.ToolTipRole)
            if current and self.findText(current) < 0:
                self.addItem(current)   # a target that is not running right now
            self.setCurrentText(current)
        finally:
            self.blockSignals(False)
        super().showPopup()


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
