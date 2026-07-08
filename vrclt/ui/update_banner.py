"""Update-available banner: GitHub release check + the dashboard bar widget."""
import logging
import threading

from PySide6 import QtCore, QtGui, QtWidgets

from ..update_check import check_latest_release

log = logging.getLogger(__name__)


class UpdateBanner(QtWidgets.QWidget):
    """Hidden bar that appears when a newer release exists. Runs the check on
    a worker thread and marshals back via its own signal. on_available(info,
    message) fires once, on the Qt thread (used to notify the tray)."""

    _available = QtCore.Signal(object)

    def __init__(self, tr, *, on_available):
        super().__init__()
        self._tr = tr
        self._on_available = on_available
        self._info = None
        self._notified = False
        self._thread: threading.Thread | None = None

        self.setObjectName("updateBar")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self._text = QtWidgets.QLabel("")
        self._text.setObjectName("updateText")
        self._text.setWordWrap(True)
        self._btn_open = QtWidgets.QPushButton(tr("btn_update_open"))
        self._btn_open.clicked.connect(self.open_release)
        layout.addWidget(self._text, 1)
        layout.addWidget(self._btn_open)
        self.hide()
        self._available.connect(self._show_info)

    @property
    def info(self):
        return self._info

    def start_check(self, current_version: str) -> None:
        if self._thread is not None:
            return

        def run():
            info = check_latest_release(current_version)
            if info is not None:
                self._available.emit(info)

        self._thread = threading.Thread(
            target=run, daemon=True, name="vrclt-update-check")
        self._thread.start()

    def _show_info(self, info) -> None:
        self._info = info
        self._sync()
        if not self._notified:
            self._notified = True
            try:
                self._on_available(info, self._message(info))
            except Exception:
                log.debug("update-available callback failed", exc_info=True)

    def _sync(self) -> None:
        self.setVisible(self._info is not None)
        if self._info is not None:
            self._text.setText(self._message(self._info))

    def _message(self, info) -> str:
        return self._tr("update_body").format(
            current=info.current_version,
            latest=info.latest_version,
        )

    def retranslate(self) -> None:
        self._btn_open.setText(self._tr("btn_update_open"))
        self._sync()

    def open_release(self) -> None:
        if self._info is None:
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(self._info.release_url))
