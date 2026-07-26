"""Logs-tab panel: following tail, level filter, search, open-folder.

Reads the log file incrementally by byte offset (rotation-aware: the
RotatingFileHandler truncates at 5 MB, detected as size < offset) so the
500 ms follow tick never re-reads the whole file.
"""
from __future__ import annotations

import re
from collections import deque
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .widgets import NoWheelComboBox

INITIAL_TAIL_BYTES = 256 * 1024
MAX_LINES = 2000
FOLLOW_INTERVAL_MS = 500
SEARCH_DEBOUNCE_MS = 250

_LEVEL_RE = re.compile(r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]")
_LEVEL_RANK = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40,
               "CRITICAL": 50}
# combo index -> minimum rank shown ("All" passes unparsed lines too)
_FILTER_MIN_RANK = (0, 20, 30, 40)
_FILTER_LABEL_KEYS = ("logs_level_all", None, None, None)
_FILTER_LITERALS = (None, "INFO+", "WARN+", "ERROR")


class LogPanel(QtWidgets.QWidget):
    """Owns the log path row, follow/filter/search controls and the text
    view. The parent gates the follow timer via set_active() (same pattern
    as the dashboard mic-meter timer)."""

    def __init__(self, log_file: Path, tr, parent=None):
        super().__init__(parent)
        self._log_file = Path(log_file)
        self._tr = tr
        self._offset = 0
        self._carry = b""
        self._lines: deque[tuple[int, str]] = deque(maxlen=MAX_LINES)
        self._last_rank = 20  # continuation lines inherit the previous level

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)

        path_row = QtWidgets.QHBoxLayout()
        self._lbl_file = QtWidgets.QLabel(tr("label_log_file"))
        self._path = QtWidgets.QLabel(str(self._log_file))
        self._path.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self._btn_folder = QtWidgets.QPushButton(tr("btn_open_log_folder"))
        self._btn_folder.clicked.connect(self._open_folder)
        path_row.addWidget(self._lbl_file)
        path_row.addWidget(self._path, 1)
        path_row.addWidget(self._btn_folder)
        root.addLayout(path_row)

        controls = QtWidgets.QHBoxLayout()
        self._follow = QtWidgets.QCheckBox(tr("logs_follow"))
        self._follow.setChecked(True)
        self._follow.toggled.connect(self._follow_toggled)
        self._level = NoWheelComboBox()
        for key, literal in zip(_FILTER_LABEL_KEYS, _FILTER_LITERALS):
            self._level.addItem(tr(key) if key else literal)
        self._level.currentIndexChanged.connect(lambda _i: self._render())
        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText(tr("logs_search_ph"))
        self._search.setClearButtonEnabled(True)
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._render)
        self._search.textChanged.connect(
            lambda _t: self._search_timer.start())
        self._btn_refresh = QtWidgets.QPushButton(tr("btn_refresh_log"))
        self._btn_refresh.clicked.connect(self.reload)
        controls.addWidget(self._follow)
        controls.addWidget(self._level)
        controls.addWidget(self._search, 1)
        controls.addWidget(self._btn_refresh)
        root.addLayout(controls)

        self._text = QtWidgets.QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(MAX_LINES)
        root.addWidget(self._text, 1)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(FOLLOW_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._active = False

        self.reload()

    # ---------------- public api ----------------
    def retranslate(self) -> None:
        tr = self._tr
        self._lbl_file.setText(tr("label_log_file"))
        self._btn_folder.setText(tr("btn_open_log_folder"))
        self._follow.setText(tr("logs_follow"))
        self._search.setPlaceholderText(tr("logs_search_ph"))
        self._btn_refresh.setText(tr("btn_refresh_log"))
        blocked = self._level.blockSignals(True)
        try:
            self._level.setItemText(0, tr("logs_level_all"))
        finally:
            self._level.blockSignals(blocked)

    def set_active(self, active: bool) -> None:
        """Called from the parent's refresh loop; the follow timer runs only
        while the logs tab is visible and follow is checked."""
        self._active = active
        want = active and self._follow.isChecked()
        if want != self._timer.isActive():
            if want:
                self._poll()
                self._timer.start()
            else:
                self._timer.stop()

    def reload(self) -> None:
        """Full re-read of the tail (manual refresh, rotation, first load)."""
        self._lines.clear()
        self._carry = b""
        self._last_rank = 20
        try:
            with self._log_file.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                start = max(0, size - INITIAL_TAIL_BYTES)
                f.seek(start)
                data = f.read()
                self._offset = size
        except FileNotFoundError:
            self._offset = 0
            self._text.setPlainText(self._tr("msg_log_missing"))
            return
        except Exception as e:
            self._offset = 0
            self._text.setPlainText(f"{self._tr('msg_log_failed')}: {e}")
            return
        if start > 0:
            data = data.split(b"\n", 1)[1] if b"\n" in data else b""
        self._ingest(data)
        self._render()

    # ---------------- tail engine ----------------
    def _follow_toggled(self, _checked: bool) -> None:
        self.set_active(self._active)

    def _poll(self) -> None:
        try:
            size = self._log_file.stat().st_size
        except OSError:
            return
        if size < self._offset:  # rotated/truncated under us
            self.reload()
            return
        if size == self._offset:
            return
        try:
            with self._log_file.open("rb") as f:
                f.seek(self._offset)
                data = f.read(size - self._offset)
                self._offset = f.tell()
        except OSError:
            return
        for rank, line in self._ingest(data):
            if self._passes(rank, line):
                self._text.appendPlainText(line)

    def _ingest(self, data: bytes) -> list[tuple[int, str]]:
        """Split new bytes into complete lines (keeping the trailing partial
        line as carry), append them to the ring buffer, and return them."""
        data = self._carry + data
        if not data:
            return []
        parts = data.split(b"\n")
        self._carry = parts.pop()
        added = []
        for raw in parts:
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            m = _LEVEL_RE.search(line)
            if m:
                self._last_rank = _LEVEL_RANK[m.group(1)]
            added.append((self._last_rank, line))
        self._lines.extend(added)
        return added

    def _passes(self, rank: int, line: str) -> bool:
        if rank < _FILTER_MIN_RANK[self._level.currentIndex()]:
            return False
        needle = self._search.text().strip().lower()
        return not needle or needle in line.lower()

    def _render(self) -> None:
        self._text.setPlainText(
            "\n".join(line for rank, line in self._lines
                      if self._passes(rank, line)))
        bar = self._text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _open_folder(self) -> None:
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(self._log_file.parent)))
