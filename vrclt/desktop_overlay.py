"""Desktop subtitle overlay for the Qt app."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from . import config as config_mod
from . import i18n
from .app_controller import resolve_ui_mode

log = logging.getLogger(__name__)

TRANSFORM_PATH = config_mod.APPDATA_DIR / "desktop_subtitle_overlay.json"
RESIZE_MARGIN = 16
MIN_WIDTH = 420
MIN_HEIGHT = 84


def _window_flag(name: str):
    return getattr(QtCore.Qt.WindowType, name, QtCore.Qt.WindowType(0))


class DesktopSubtitleOverlay(QtWidgets.QWidget):
    def __init__(self, controller):
        super().__init__(None)
        self._controller = controller
        self._drag_offset = QtCore.QPoint()
        self._drag_mode = ""
        self._resize_edges = (False, False, False, False)  # left, top, right, bottom
        self._press_global = QtCore.QPoint()
        self._press_geometry = QtCore.QRect()
        self._input_edit: bool | None = None

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setWindowTitle(i18n.tr(self._controller.state.ui_lang, "desktop_subtitle_title"))

        self._label = QtWidgets.QLabel()
        self._label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self._label.setWordWrap(True)
        self._label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self._label.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        self._label.setMouseTracking(True)
        self._label.installEventFilter(self)

        self._resize_grip = QtWidgets.QFrame(self)
        self._resize_grip.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._resize_grip.setFixedSize(22, 22)
        self._resize_grip.setStyleSheet(
            "QFrame {"
            "background: transparent;"
            "border-right: 3px solid rgba(88,166,255,170);"
            "border-bottom: 3px solid rgba(88,166,255,170);"
            "}"
        )
        self._resize_grip.hide()

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
        self.setWindowTitle(i18n.tr(state.ui_lang, "desktop_subtitle_title"))
        desktop_mode = resolve_ui_mode(cfg) == "desktop"
        inbound_enabled = bool(cfg.get("inbound", {}).get("enabled", True))
        edit = bool(state.edit_mode)
        text = self._subtitle_text()

        if edit and not text:
            text = i18n.tr(state.ui_lang, "sub_placeholder")

        should_show = desktop_mode and (
            edit or (inbound_enabled and state.subtitles_on and bool(text))
        )
        if not should_show:
            self.hide()
            return

        self._apply_input_mode(edit)
        self._apply_style(edit)
        if self._label.text() != text:
            self._label.setText(text)
        self._resize_grip.setVisible(edit)
        if edit:
            self._position_resize_grip()
        if not self.isVisible():
            self.show()
        if edit:
            self.raise_()

    def show_for_edit(self) -> None:
        self.refresh()
        if resolve_ui_mode(self._controller.cfg) != "desktop":
            return
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
        font = QtGui.QFont(self.font())
        font.setPixelSize(font_size)
        font.setWeight(QtGui.QFont.Weight.Bold)
        font.setStyleStrategy(
            QtGui.QFont.StyleStrategy.PreferQuality
            | QtGui.QFont.StyleStrategy.PreferAntialias
            | QtGui.QFont.StyleStrategy.ContextFontMerging
        )
        font.setHintingPreference(QtGui.QFont.HintingPreference.PreferNoHinting)
        self._label.setFont(font)
        border = "2px solid #58a6ff" if edit else "1px solid rgba(255,255,255,60)"
        background = "rgba(12,14,18,210)" if edit else "rgba(12,14,18,175)"
        self._label.setStyleSheet(
            f"QLabel {{"
            f"color: white;"
            f"background: {background};"
            f"border: {border};"
            f"border-radius: 8px;"
            f"padding: 14px 18px;"
            f"}}"
        )

    def _position_resize_grip(self) -> None:
        size = self._resize_grip.size()
        self._resize_grip.move(max(0, self.width() - size.width() - 8),
                               max(0, self.height() - size.height() - 8))
        self._resize_grip.raise_()

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
        width = min(820, max(MIN_WIDTH, area.width() - 96))
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
        width = min(max(rect.width(), MIN_WIDTH), area.width())
        height = min(max(rect.height(), MIN_HEIGHT), area.height())
        x = min(max(rect.x(), area.left()), area.right() - width + 1)
        y = min(max(rect.y(), area.top()), area.bottom() - height + 1)
        return QtCore.QRect(x, y, width, height)

    def _resize_edges_at(self, pos: QtCore.QPoint) -> tuple[bool, bool, bool, bool]:
        rect = self.rect()
        return (
            pos.x() <= RESIZE_MARGIN,
            pos.y() <= RESIZE_MARGIN,
            pos.x() >= rect.width() - RESIZE_MARGIN,
            pos.y() >= rect.height() - RESIZE_MARGIN,
        )

    @staticmethod
    def _cursor_for_edges(edges: tuple[bool, bool, bool, bool]):
        left, top, right, bottom = edges
        if (left and top) or (right and bottom):
            return QtCore.Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return QtCore.Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return QtCore.Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return QtCore.Qt.CursorShape.SizeVerCursor
        return QtCore.Qt.CursorShape.SizeAllCursor

    def _update_cursor(self, pos: QtCore.QPoint) -> None:
        if not self._controller.state.edit_mode:
            self.unsetCursor()
            return
        self.setCursor(self._cursor_for_edges(self._resize_edges_at(pos)))

    def _resize_from_global(self, global_pos: QtCore.QPoint) -> None:
        dx = global_pos.x() - self._press_global.x()
        dy = global_pos.y() - self._press_global.y()
        left, top, right, bottom = self._resize_edges
        geom = QtCore.QRect(self._press_geometry)
        if left:
            geom.setLeft(min(self._press_geometry.left() + dx,
                             self._press_geometry.right() - MIN_WIDTH + 1))
        if top:
            geom.setTop(min(self._press_geometry.top() + dy,
                            self._press_geometry.bottom() - MIN_HEIGHT + 1))
        if right:
            geom.setWidth(max(MIN_WIDTH, self._press_geometry.width() + dx))
        if bottom:
            geom.setHeight(max(MIN_HEIGHT, self._press_geometry.height() + dy))
        self.setGeometry(self._clamp_to_screen(geom))

    def _handle_mouse_press(self, event: QtGui.QMouseEvent, pos: QtCore.QPoint) -> bool:
        if not self._controller.state.edit_mode or event.button() != QtCore.Qt.MouseButton.LeftButton:
            return False
        self._press_global = event.globalPosition().toPoint()
        self._press_geometry = self.geometry()
        self._resize_edges = self._resize_edges_at(pos)
        if any(self._resize_edges):
            self._drag_mode = "resize"
            self.setCursor(self._cursor_for_edges(self._resize_edges))
        else:
            self._drag_mode = "move"
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
        return True

    def _handle_mouse_move(self, event: QtGui.QMouseEvent, pos: QtCore.QPoint) -> bool:
        if not self._controller.state.edit_mode:
            self.unsetCursor()
            return False
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            if self._drag_mode == "resize":
                self._resize_from_global(event.globalPosition().toPoint())
                return True
            if self._drag_mode == "move":
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
        self._update_cursor(pos)
        return True

    def _handle_mouse_release(self, event: QtGui.QMouseEvent, pos: QtCore.QPoint) -> bool:
        if self._controller.state.edit_mode and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_mode = ""
            self._save_geometry()
            self._update_cursor(pos)
            return True
        return False

    def eventFilter(self, obj, event) -> bool:
        if obj is self._label and isinstance(event, QtGui.QMouseEvent):
            pos = self._label.mapTo(self, event.position().toPoint())
            if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                return self._handle_mouse_press(event, pos)
            if event.type() == QtCore.QEvent.Type.MouseMove:
                return self._handle_mouse_move(event, pos)
            if event.type() == QtCore.QEvent.Type.MouseButtonRelease:
                return self._handle_mouse_release(event, pos)
        return super().eventFilter(obj, event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_resize_grip()

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        if not self._drag_mode:
            self.unsetCursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._handle_mouse_press(event, event.position().toPoint()):
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._handle_mouse_move(event, event.position().toPoint()):
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._handle_mouse_release(event, event.position().toPoint()):
            event.accept()
            return
        event.ignore()
