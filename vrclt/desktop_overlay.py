"""Desktop subtitle overlay for the Qt app."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from . import config as config_mod
from . import i18n

log = logging.getLogger(__name__)

TRANSFORM_PATH = config_mod.APPDATA_DIR / "desktop_subtitle_overlay.json"


def _window_flag(name: str):
    return getattr(QtCore.Qt.WindowType, name, QtCore.Qt.WindowType(0))


class DesktopSubtitleOverlay(QtWidgets.QWidget):
    def __init__(self, controller):
        super().__init__(None)
        self._controller = controller
        self._drag_offset = QtCore.QPoint()
        self._input_edit: bool | None = None

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("vrclt subtitles")

        self._label = QtWidgets.QLabel()
        self._label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self._label.setWordWrap(True)
        self._label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self._label.setMinimumSize(420, 84)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        self._restore_geometry()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(120)
        self.refresh()

    def refresh(self) -> None:
        state = self._controller.state
        cfg = self._controller.cfg
        overlay_cfg = cfg.get("overlay", {})
        enabled = bool(overlay_cfg.get("enabled", True))
        edit = bool(state.edit_mode)
        text = self._subtitle_text()

        if edit and not text:
            text = i18n.tr(state.ui_lang, "sub_placeholder")

        should_show = edit or (enabled and state.subtitles_on and bool(text))
        if not should_show:
            self.hide()
            return

        self._apply_input_mode(edit)
        self._apply_style(edit)
        if self._label.text() != text:
            self._label.setText(text)
        if not self.isVisible():
            self.show()
        if edit:
            self.raise_()

    def show_for_edit(self) -> None:
        self.refresh()
        self.show()
        self.raise_()

    def reset_position(self) -> None:
        self.setGeometry(self._default_geometry())
        self._save_geometry()
        self.show_for_edit()

    def _subtitle_text(self) -> str:
        cfg = self._controller.cfg.get("overlay", {})
        show_source = bool(cfg.get("show_source", False))
        finals, partial = self._controller.subtitles_snapshot()
        rows: list[str] = []
        for src, dst, _lang in finals:
            if show_source and src and dst:
                rows.append(f"{src}\n{dst}")
            else:
                rows.append(dst or src)
        p_src, p_dst = partial
        if p_src or p_dst:
            if show_source and p_src and p_dst:
                rows.append(f"{p_src}\n{p_dst}")
            else:
                rows.append(p_dst or p_src)
        return "\n".join(row for row in rows if row)

    def _apply_style(self, edit: bool) -> None:
        overlay_cfg = self._controller.cfg.get("overlay", {})
        try:
            font_size = int(overlay_cfg.get("font_size", 36))
        except Exception:
            font_size = 36
        font_size = max(18, min(72, font_size))
        border = "2px solid #58a6ff" if edit else "1px solid rgba(255,255,255,60)"
        background = "rgba(12,14,18,210)" if edit else "rgba(12,14,18,175)"
        self._label.setStyleSheet(
            f"QLabel {{"
            f"color: white;"
            f"background: {background};"
            f"border: {border};"
            f"border-radius: 8px;"
            f"padding: 14px 18px;"
            f"font-size: {font_size}px;"
            f"font-weight: 700;"
            f"}}"
        )

    def _apply_input_mode(self, edit: bool) -> None:
        if self._input_edit == edit:
            return
        flags = (
            _window_flag("FramelessWindowHint")
            | _window_flag("Tool")
            | _window_flag("WindowStaysOnTopHint")
            | _window_flag("WindowDoesNotAcceptFocus")
        )
        if not edit:
            flags |= _window_flag("WindowTransparentForInput")
        self.setWindowFlags(flags)
        self._input_edit = edit
        if self.isVisible():
            self.show()

    def _default_geometry(self) -> QtCore.QRect:
        screen = QtWidgets.QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1280, 720)
        width = min(820, max(420, area.width() - 96))
        height = 156
        x = area.x() + (area.width() - width) // 2
        y = area.y() + area.height() - height - 96
        return QtCore.QRect(x, y, width, height)

    def _restore_geometry(self) -> None:
        rect = self._default_geometry()
        try:
            data = json.loads(Path(TRANSFORM_PATH).read_text(encoding="utf-8"))
            rect = QtCore.QRect(int(data["x"]), int(data["y"]),
                                int(data["w"]), int(data["h"]))
        except Exception:
            pass
        self.setGeometry(self._clamp_to_screen(rect))

    def _save_geometry(self) -> None:
        try:
            TRANSFORM_PATH.parent.mkdir(parents=True, exist_ok=True)
            rect = self.geometry()
            TRANSFORM_PATH.write_text(json.dumps({
                "x": rect.x(),
                "y": rect.y(),
                "w": rect.width(),
                "h": rect.height(),
            }), encoding="utf-8")
        except Exception:
            log.debug("failed to save desktop subtitle overlay geometry", exc_info=True)

    def _clamp_to_screen(self, rect: QtCore.QRect) -> QtCore.QRect:
        screen = QtWidgets.QApplication.screenAt(rect.center()) or QtWidgets.QApplication.primaryScreen()
        if not screen:
            return rect
        area = screen.availableGeometry()
        width = min(max(rect.width(), 420), area.width())
        height = min(max(rect.height(), 84), area.height())
        x = min(max(rect.x(), area.left()), area.right() - width + 1)
        y = min(max(rect.y(), area.top()), area.bottom() - height + 1)
        return QtCore.QRect(x, y, width, height)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if not self._controller.state.edit_mode or event.button() != QtCore.Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if not self._controller.state.edit_mode or not (event.buttons() & QtCore.Qt.MouseButton.LeftButton):
            event.ignore()
            return
        self.move(event.globalPosition().toPoint() - self._drag_offset)
        event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._controller.state.edit_mode and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._save_geometry()
            event.accept()
            return
        event.ignore()
