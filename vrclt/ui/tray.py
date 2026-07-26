"""System tray icon + menu for the main window."""
from PySide6 import QtCore, QtGui, QtWidgets

from . import theme


def make_tray_icon() -> QtGui.QIcon:
    """Blue rounded rect + white V (matches the VR dashboard thumbnail)."""
    pix = QtGui.QPixmap(64, 64)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pix)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setBrush(QtGui.QColor(theme.hex_rgb(theme.QT_TRAY_BLUE)))
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.drawRoundedRect(6, 6, 52, 52, 14, 14)
    painter.setPen(QtGui.QColor("#ffffff"))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(24)
    painter.setFont(font)
    painter.drawText(pix.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "V")
    painter.end()
    return QtGui.QIcon(pix)


class TrayIcon(QtCore.QObject):
    """Owns the QSystemTrayIcon and its menu; actions arrive as callbacks."""

    def __init__(self, parent: QtWidgets.QWidget, tr, *,
                 on_show, on_show_settings, on_open_update,
                 on_toggle_translation, on_toggle_subtitles, on_quit,
                 on_message_clicked):
        super().__init__(parent)
        self._tr = tr
        # parented to the window so Qt teardown order is unchanged
        self._tray = QtWidgets.QSystemTrayIcon(make_tray_icon(), parent)
        self._tray.setToolTip("vrclt")
        menu = QtWidgets.QMenu(parent)
        act_show = menu.addAction(tr("tray_show"))
        act_settings = menu.addAction(tr("tray_settings"))
        act_update = menu.addAction(tr("tray_update"))
        act_update.setVisible(False)
        menu.addSeparator()
        act_trans = menu.addAction(tr("tray_trans"))
        act_sub = menu.addAction(tr("tray_subs"))
        menu.addSeparator()
        act_quit = menu.addAction(tr("tray_quit"))
        self._actions = {
            "tray_show": act_show,
            "tray_settings": act_settings,
            "tray_update": act_update,
            "tray_trans": act_trans,
            "tray_subs": act_sub,
            "tray_quit": act_quit,
        }
        act_show.triggered.connect(on_show)
        act_settings.triggered.connect(on_show_settings)
        act_update.triggered.connect(on_open_update)
        act_trans.triggered.connect(on_toggle_translation)
        act_sub.triggered.connect(on_toggle_subtitles)
        act_quit.triggered.connect(on_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda reason: on_show()
            if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger else None)
        self._tray.messageClicked.connect(on_message_clicked)
        self._tray.show()

    def retranslate(self) -> None:
        for key, action in self._actions.items():
            action.setText(self._tr(key))

    def set_update_visible(self, visible: bool) -> None:
        self._actions["tray_update"].setVisible(visible)

    def show_message(self, title: str, body: str, msecs: int) -> None:
        self._tray.showMessage(
            title, body, QtWidgets.QSystemTrayIcon.MessageIcon.Information, msecs)

    def hide(self) -> None:
        self._tray.hide()
