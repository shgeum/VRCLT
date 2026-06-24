"""PySide6 native UI for vrclt."""
from __future__ import annotations

import copy
import logging
import threading
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from . import __version__
from . import config as config_mod
from . import i18n
from .app_controller import resolve_ui_mode
from .desktop_overlay import DesktopSubtitleOverlay
from .languages import (
    language_code_from_text,
    language_label,
    supported_language_options,
)
from .hotkeys import HotkeyRegistration, WindowsGlobalHotkeys
from .resources import bundled_font, resolve_font_path
from .update_check import check_latest_release

log = logging.getLogger(__name__)

APP_FONT_SIZE_PT = 11
HOTKEY_TRANSLATION_ID = 0x6100
HOTKEY_SUBTITLES_ID = 0x6101
_APP_FONT_FAMILIES: dict[str, str] = {}

def _get_path(data: dict, path: str, default=None):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _set_path(data: dict, path: str, value) -> None:
    cur = data
    parts = path.split(".")
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _as_csv(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


def _from_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _as_float_list(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


def _from_float_list(value: str) -> list[float]:
    return [float(v.strip()) for v in value.split(",") if v.strip()]


def _device_names() -> tuple[list[str], list[str]]:
    try:
        import sounddevice as sd
        from .audio.devices import wasapi_index
        try:
            wi = wasapi_index()
        except Exception:
            wi = None
        ins, outs, seen_i, seen_o = [""], [""], {""}, {""}
        for d in sd.query_devices():
            if wi is not None and d["hostapi"] != wi:
                continue
            name = d["name"]
            if d["max_input_channels"] > 0 and name not in seen_i:
                seen_i.add(name)
                ins.append(name)
            if d["max_output_channels"] > 0 and name not in seen_o:
                seen_o.add(name)
                outs.append(name)
        return ins, outs
    except Exception:
        log.exception("device enumeration failed")
        return [""], [""]


def _install_app_font(app: QtWidgets.QApplication, lang: str = "") -> None:
    for key, filename in (
        ("ko", "NotoSansCJKkr-Regular.otf"),
        ("ko_bold", "NotoSansCJKkr-Bold.otf"),
        ("zh", "NotoSansCJKsc-Regular.otf"),
        ("zh_bold", "NotoSansCJKsc-Bold.otf"),
        ("ja", "PretendardJP-Regular.otf"),
        ("ja_bold", "PretendardJP-Bold.otf"),
    ):
        token = bundled_font(filename)
        fallback = filename
        path = resolve_font_path(token, fallback)
        font_id = QtGui.QFontDatabase.addApplicationFont(path)
        if font_id < 0:
            log.warning("failed to load app font: %s", path)
            continue
        families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        if families:
            _APP_FONT_FAMILIES[key] = families[0]
    _apply_app_font(app, lang)


def _apply_app_font(app: QtWidgets.QApplication | None, lang: str = "") -> None:
    if app is None:
        return
    lang = i18n.detect(lang)
    family = (
        _APP_FONT_FAMILIES.get(lang)
        or _APP_FONT_FAMILIES.get("ko")
        or _APP_FONT_FAMILIES.get("ja")
        or _APP_FONT_FAMILIES.get("zh")
        or app.font().family()
    )
    font = QtGui.QFont(family)
    font.setPointSize(APP_FONT_SIZE_PT)
    font.setStyleStrategy(
        QtGui.QFont.StyleStrategy.PreferQuality
        | QtGui.QFont.StyleStrategy.PreferAntialias
        | QtGui.QFont.StyleStrategy.ContextFontMerging
    )
    font.setHintingPreference(QtGui.QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)


class _UiSignals(QtCore.QObject):
    refresh = QtCore.Signal()
    save_done = QtCore.Signal(bool)
    mode_done = QtCore.Signal(bool)
    reset_done = QtCore.Signal(bool)
    translation_hotkey = QtCore.Signal()
    subtitles_hotkey = QtCore.Signal()
    update_available = QtCore.Signal(object)


class _NoWheelComboBox(QtWidgets.QComboBox):
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class _HotkeyEdit(QtWidgets.QKeySequenceEdit):
    focus_in = QtCore.Signal()
    focus_out = QtCore.Signal()

    def focusInEvent(self, event: QtGui.QFocusEvent) -> None:
        self.focus_in.emit()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.focus_out.emit()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, controller, log_file: Path):
        super().__init__()
        self._controller = controller
        self._log_file = Path(log_file)
        self._quitting = False
        self._fields = {}
        self._i18n_widgets = {}
        self._tab_dashboard_idx = -1
        self._tab_settings_idx = -1
        self._tab_logs_idx = -1
        self._tray_actions = {}
        self._last_ui_lang = ""
        self._last_config_revision = getattr(controller, "config_revision", 0)
        self._hotkey_signature = None
        self._hotkeys = WindowsGlobalHotkeys()
        self._save_thread = None
        self._mode_thread = None
        self._reset_thread = None
        self._update_thread = None
        self._update_info = None
        self._update_notified = False
        self._app_mode_applying = False
        self._app_mode_buttons = {}
        self._inputs, self._outputs = _device_names()
        self._signals = _UiSignals()
        self._signals.refresh.connect(self._refresh)
        self._signals.save_done.connect(self._save_done)
        self._signals.mode_done.connect(self._mode_done)
        self._signals.reset_done.connect(self._reset_done)
        self._signals.translation_hotkey.connect(self._toggle_translation)
        self._signals.subtitles_hotkey.connect(self._toggle_subtitles)
        self._signals.update_available.connect(self._update_available)

        self.setWindowTitle("vrclt")
        self.resize(980, 720)
        self._tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self._tabs)

        self._build_dashboard()
        self._build_settings()
        self._build_logs()
        self._build_tray()
        self._apply_style()
        self._desktop_overlay = DesktopSubtitleOverlay(controller)

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(250)
        self._controller.subscribe(self._signals.refresh.emit)
        self._sync_hotkeys()
        self._refresh()
        self._start_update_check()
        QtCore.QTimer.singleShot(1200, self._maybe_prompt_config_reset_after_update)

    # ---------------- construction ----------------
    def _lang(self) -> str:
        try:
            return self._controller.state.ui_lang
        except Exception:
            return i18n.detect(self._controller.cfg.get("ui", {}).get("lang", ""))

    def _tr(self, key: str) -> str:
        return i18n.tr(self._lang(), key)

    def _label(self, key: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(self._tr(key))
        self._i18n_widgets[key] = label
        return label

    def _status_label(self, status: str) -> str:
        key = "status_" + (status or "").strip().lower().replace(" ", "_")
        return i18n.tr(self._lang(), key)

    def _error_label(self, error: str) -> str:
        if error == "API key is empty.":
            return self._tr("err_api_key_empty")
        if error == "API key must be a Gemini API key, not a URL.":
            return self._tr("err_api_key_url")
        return error

    def _apply_i18n(self) -> None:
        for key, widget in self._i18n_widgets.items():
            widget.setText(self._tr(key))
        if self._tab_dashboard_idx >= 0:
            self._tabs.setTabText(self._tab_dashboard_idx, self._tr("tab_dashboard"))
        if self._tab_settings_idx >= 0:
            self._tabs.setTabText(self._tab_settings_idx, self._tr("tab_settings"))
        if self._tab_logs_idx >= 0:
            self._tabs.setTabText(self._tab_logs_idx, self._tr("tab_logs"))
        if hasattr(self, "_btn_restart"):
            self._btn_restart.setText(self._tr("btn_restart_runtime"))
        if hasattr(self, "_text_only"):
            self._text_only.setText(self._tr("btn_text_only_on"))
        if hasattr(self, "_out_lang_add"):
            self._set_language_picker_placeholder(self._out_lang_add, self._tr("ph_out_add"))
        if hasattr(self, "_out_lang_add_btn"):
            self._out_lang_add_btn.setText(self._tr("btn_add"))
        if hasattr(self, "_sub_lang_add"):
            self._set_language_picker_placeholder(self._sub_lang_add, self._tr("ph_sub_add"))
        if hasattr(self, "_sub_lang_add_btn"):
            self._sub_lang_add_btn.setText(self._tr("btn_add"))
        if hasattr(self, "_btn_overlay_reset"):
            self._btn_overlay_reset.setText(self._tr("btn_overlay_reset"))
        if hasattr(self, "_subtitle_view"):
            self._subtitle_view.setPlaceholderText(self._tr("subtitle_live_placeholder"))
        if hasattr(self, "_btn_devices"):
            self._btn_devices.setText(self._tr("btn_refresh_devices"))
        if hasattr(self, "_btn_reset_config"):
            self._btn_reset_config.setText(self._tr("btn_reset_config"))
        if hasattr(self, "_btn_save"):
            self._btn_save.setText(self._tr("btn_save_restart"))
        if hasattr(self, "_btn_log_refresh"):
            self._btn_log_refresh.setText(self._tr("btn_refresh_log"))
        if hasattr(self, "_about_text"):
            self._about_text.setText(self._tr("about_paths").format(config=config_mod.CONFIG_PATH))
        if hasattr(self, "_btn_update_open"):
            self._btn_update_open.setText(self._tr("btn_update_open"))
            self._sync_update_banner()
        if hasattr(self, "_close_action"):
            self._sync_close_action()
        for key, action in self._tray_actions.items():
            action.setText(self._tr(key))

    def _build_dashboard(self) -> None:
        page = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(page)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        top = QtWidgets.QHBoxLayout()
        self._status_dot = QtWidgets.QLabel()
        self._status_dot.setFixedSize(14, 14)
        self._status_text = QtWidgets.QLabel(self._tr("status_stopped"))
        self._status_text.setObjectName("statusText")
        self._error_text = QtWidgets.QLabel("")
        self._error_text.setObjectName("errorText")
        self._error_text.setWordWrap(True)
        top.addWidget(self._status_dot)
        top.addWidget(self._status_text)
        top.addStretch(1)
        self._btn_restart = QtWidgets.QPushButton(self._tr("btn_restart_runtime"))
        self._btn_restart.clicked.connect(self._restart_runtime)
        top.addWidget(self._btn_restart)
        root.addLayout(top)
        root.addWidget(self._error_text)

        self._update_bar = QtWidgets.QWidget()
        self._update_bar.setObjectName("updateBar")
        update_layout = QtWidgets.QHBoxLayout(self._update_bar)
        update_layout.setContentsMargins(12, 10, 12, 10)
        self._update_text = QtWidgets.QLabel("")
        self._update_text.setObjectName("updateText")
        self._update_text.setWordWrap(True)
        self._btn_update_open = QtWidgets.QPushButton(self._tr("btn_update_open"))
        self._btn_update_open.clicked.connect(self._open_update_release)
        update_layout.addWidget(self._update_text, 1)
        update_layout.addWidget(self._btn_update_open)
        self._update_bar.hide()
        root.addWidget(self._update_bar)

        controls = QtWidgets.QGridLayout()
        self._btn_trans = QtWidgets.QPushButton()
        self._btn_trans.clicked.connect(
            lambda: self._controller.set_translation_on(not self._controller.state.translation_on))
        self._btn_sub = QtWidgets.QPushButton()
        self._btn_sub.clicked.connect(
            lambda: self._controller.set_subtitles_on(not self._controller.state.subtitles_on))
        self._out_lang = _NoWheelComboBox()
        self._sub_lang = _NoWheelComboBox()
        self._ui_lang = _NoWheelComboBox()
        self._ui_lang.addItems([i18n.UI_LANG_LABELS[c] for c in i18n.LANGS])
        self._out_lang.currentTextChanged.connect(self._pick_out_lang)
        self._sub_lang.currentTextChanged.connect(self._pick_sub_lang)
        self._ui_lang.currentTextChanged.connect(self._pick_ui_lang)
        self._out_lang_add = self._build_language_picker(self._tr("ph_out_add"))
        self._out_lang_add.lineEdit().returnPressed.connect(self._add_output_language_from_input)
        self._out_lang_add_btn = QtWidgets.QPushButton(self._tr("btn_add"))
        self._out_lang_add_btn.clicked.connect(self._add_output_language_from_input)
        self._sub_lang_add = self._build_language_picker(self._tr("ph_sub_add"))
        self._sub_lang_add.lineEdit().returnPressed.connect(self._add_inbound_language_from_input)
        self._sub_lang_add_btn = QtWidgets.QPushButton(self._tr("btn_add"))
        self._sub_lang_add_btn.clicked.connect(self._add_inbound_language_from_input)
        out_lang_add_widget = self._build_language_add_control(
            self._out_lang_add, self._out_lang_add_btn)
        sub_lang_add_widget = self._build_language_add_control(
            self._sub_lang_add, self._sub_lang_add_btn)
        app_mode_widget = self._build_app_mode_toggle()
        self._text_only = QtWidgets.QCheckBox(self._tr("btn_text_only_on"))
        self._text_only.toggled.connect(self._apply_text_only)
        self._overlay_font_size = QtWidgets.QSpinBox()
        self._overlay_font_size.setRange(18, 72)
        self._overlay_font_size.setSuffix(" px")
        self._overlay_font_size.setValue(
            int(self._controller.cfg.get("overlay", {}).get("font_size", 44)))
        self._overlay_font_size.valueChanged.connect(self._set_overlay_font_size)
        self._close_action = _NoWheelComboBox()
        self._sync_close_action()
        self._close_action.currentIndexChanged.connect(self._pick_close_action)
        self._dashboard_note = QtWidgets.QLabel("")
        self._dashboard_note.setObjectName("noteText")
        self._btn_overlay_move = QtWidgets.QPushButton()
        self._btn_overlay_move.clicked.connect(self._toggle_overlay_move)
        self._btn_overlay_reset = QtWidgets.QPushButton(self._tr("btn_overlay_reset"))
        self._btn_overlay_reset.clicked.connect(self._reset_overlay_position)
        controls.addWidget(self._label("label_app_mode"), 0, 0)
        controls.addWidget(app_mode_widget, 0, 1, 1, 2)
        controls.addWidget(self._text_only, 0, 3)
        controls.addWidget(self._label("ctl_my_translate"), 1, 0)
        controls.addWidget(self._btn_trans, 1, 1)
        controls.addWidget(self._label("label_out_lang"), 1, 2)
        controls.addWidget(self._out_lang, 1, 3)
        controls.addWidget(self._label("ctl_their_sub"), 2, 0)
        controls.addWidget(self._btn_sub, 2, 1)
        controls.addWidget(self._label("label_sub_lang"), 2, 2)
        controls.addWidget(self._sub_lang, 2, 3)
        controls.addWidget(self._label("ui_lang"), 3, 0)
        controls.addWidget(self._ui_lang, 3, 1)
        controls.addWidget(self._label("label_pc_sub_size"), 3, 2)
        controls.addWidget(self._overlay_font_size, 3, 3)
        controls.addWidget(self._label("label_close_action"), 4, 0)
        controls.addWidget(self._close_action, 4, 1)
        controls.addWidget(self._btn_overlay_move, 4, 2)
        controls.addWidget(self._btn_overlay_reset, 4, 3)
        controls.addWidget(self._label("label_add_out_lang"), 5, 0)
        controls.addWidget(out_lang_add_widget, 5, 1)
        controls.addWidget(self._label("label_add_sub_lang"), 5, 2)
        controls.addWidget(sub_lang_add_widget, 5, 3)
        root.addLayout(controls)
        root.addWidget(self._dashboard_note)

        self._subtitle_view = QtWidgets.QPlainTextEdit()
        self._subtitle_view.setReadOnly(True)
        self._subtitle_view.setPlaceholderText(self._tr("subtitle_live_placeholder"))
        root.addWidget(self._subtitle_view, 1)
        self._tab_dashboard_idx = self._tabs.addTab(page, self._tr("tab_dashboard"))

    def _build_language_picker(self, placeholder: str = "") -> _NoWheelComboBox:
        combo = _NoWheelComboBox()
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
        self._set_language_picker_placeholder(combo, placeholder)
        return combo

    @staticmethod
    def _set_language_picker_placeholder(combo: QtWidgets.QComboBox, text: str) -> None:
        line_edit = combo.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText(text)

    def _build_language_add_control(self, edit: QtWidgets.QComboBox,
                                    button: QtWidgets.QPushButton) -> QtWidgets.QWidget:
        wrap = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        button.setFixedWidth(64)
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        return wrap

    def _build_app_mode_toggle(self) -> QtWidgets.QWidget:
        wrap = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._app_mode_group = QtWidgets.QButtonGroup(self)
        self._app_mode_group.setExclusive(True)
        labels = {
            "vrchat": "VRChat",
            "discord": "Discord",
        }
        for mode in config_mod.APP_MODES:
            btn = QtWidgets.QPushButton(labels.get(mode, mode))
            btn.setCheckable(True)
            btn.setProperty("modeButton", True)
            btn.setMinimumSize(112, 52)
            btn.clicked.connect(lambda _checked=False, m=mode: self._apply_app_mode(m))
            self._app_mode_group.addButton(btn)
            self._app_mode_buttons[mode] = btn
            layout.addWidget(btn)
        layout.addStretch(1)
        self._set_app_mode_checked(self._controller.cfg.get("app", {}).get("mode", "vrchat"))
        return wrap

    def _build_settings(self) -> None:
        page = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        body = QtWidgets.QWidget()
        self._settings_layout = QtWidgets.QVBoxLayout(body)
        self._settings_layout.setContentsMargins(18, 18, 18, 18)
        self._settings_layout.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        buttons = QtWidgets.QHBoxLayout()
        self._btn_devices = QtWidgets.QPushButton(self._tr("btn_refresh_devices"))
        self._btn_devices.clicked.connect(self._reload_devices)
        self._btn_reset_config = QtWidgets.QPushButton(self._tr("btn_reset_config"))
        self._btn_reset_config.clicked.connect(self._confirm_reset_config)
        self._btn_save = QtWidgets.QPushButton(self._tr("btn_save_restart"))
        self._btn_save.setObjectName("primaryButton")
        self._btn_save.clicked.connect(self._save_settings)
        self._settings_note = QtWidgets.QLabel("")
        self._settings_note.setObjectName("noteText")
        buttons.addWidget(self._settings_note, 1)
        buttons.addWidget(self._btn_devices)
        buttons.addWidget(self._btn_reset_config)
        buttons.addWidget(self._btn_save)
        outer.addLayout(buttons)

        self._populate_settings()
        self._tab_settings_idx = self._tabs.addTab(page, self._tr("tab_settings"))

    def _build_logs(self) -> None:
        page = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(page)
        root.setContentsMargins(18, 18, 18, 18)
        self._log_path = QtWidgets.QLabel(str(self._log_file))
        self._log_text = QtWidgets.QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._btn_log_refresh = QtWidgets.QPushButton(self._tr("btn_refresh_log"))
        self._btn_log_refresh.clicked.connect(self._load_log_tail)
        self._about_text = QtWidgets.QLabel(
            self._tr("about_paths").format(config=config_mod.CONFIG_PATH)
        )
        self._about_text.setWordWrap(True)
        root.addWidget(self._label("label_log_file"))
        root.addWidget(self._log_path)
        root.addWidget(self._btn_log_refresh)
        root.addWidget(self._log_text, 1)
        root.addWidget(self._about_text)
        self._tab_logs_idx = self._tabs.addTab(page, self._tr("tab_logs"))
        self._load_log_tail()

    def _build_tray(self) -> None:
        self._tray = QtWidgets.QSystemTrayIcon(self._make_icon(), self)
        self._tray.setToolTip("vrclt")
        menu = QtWidgets.QMenu(self)
        act_show = menu.addAction(self._tr("tray_show"))
        act_settings = menu.addAction(self._tr("tray_settings"))
        act_update = menu.addAction(self._tr("tray_update"))
        act_update.setVisible(False)
        menu.addSeparator()
        act_trans = menu.addAction(self._tr("tray_trans"))
        act_sub = menu.addAction(self._tr("tray_subs"))
        menu.addSeparator()
        act_quit = menu.addAction(self._tr("tray_quit"))
        self._tray_actions = {
            "tray_show": act_show,
            "tray_settings": act_settings,
            "tray_update": act_update,
            "tray_trans": act_trans,
            "tray_subs": act_sub,
            "tray_quit": act_quit,
        }
        act_show.triggered.connect(self._show_main)
        act_settings.triggered.connect(self._show_settings)
        act_update.triggered.connect(self._open_update_release)
        act_trans.triggered.connect(self._toggle_translation)
        act_sub.triggered.connect(self._toggle_subtitles)
        act_quit.triggered.connect(self._quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda reason: self._show_main()
            if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger else None)
        self._tray.messageClicked.connect(self._open_update_release)
        self._tray.show()

    def _make_icon(self) -> QtGui.QIcon:
        pix = QtGui.QPixmap(64, 64)
        pix.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pix)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(QtGui.QColor("#4a6eb4"))
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

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #12141a; color: #f0f0f0; }
            QTabWidget::pane { border: 1px solid #303542; }
            QTabBar::tab { padding: 10px 18px; background: #1c1f29; }
            QTabBar::tab:selected { background: #2a3040; }
            QGroupBox { border: 1px solid #303542; border-radius: 6px; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
                background: #1c1f29; color: #f0f0f0; border: 1px solid #303542;
                border-radius: 4px; padding: 6px 8px; min-height: 28px;
            }
            QPushButton {
                background: #2a3040; color: #f0f0f0; border: 0; border-radius: 4px;
                padding: 8px 14px; min-height: 30px;
            }
            QPushButton:hover { background: #384259; }
            QPushButton#primaryButton {
                background: #1f8f4d; color: #ffffff; font-weight: 800;
                padding: 9px 18px;
            }
            QPushButton#primaryButton:hover { background: #26a85d; }
            QPushButton#primaryButton:disabled {
                background: #32513d; color: #9aa0ad;
            }
            #statusText { font-weight: 700; }
            #errorText { color: #ffb4a8; }
            #noteText { color: #9aa0ad; }
            #updateBar {
                background: #1c1f29; border: 1px solid #d29922; border-radius: 6px;
            }
            #updateText { color: #ffd580; font-weight: 600; }
            QPushButton[modeButton="true"] {
                background: #1c1f29; border: 1px solid #303542; border-radius: 8px;
                padding: 10px 14px; font-weight: 600;
            }
            QPushButton[modeButton="true"]:checked {
                background: #f0f0f0; color: #12141a; border: 2px solid #8b949e;
                font-weight: 800;
            }
        """)

    # ---------------- settings form ----------------
    def _populate_settings(self) -> None:
        self._clear_layout(self._settings_layout)
        self._fields.clear()
        cfg = self._controller.raw_cfg
        self._add_group("grp_api", [
            ("api_key", "f.api_key", "password"),
            ("model", "f.model", "text"),
            ("app.mode", "f.app.mode", "appmode"),
            ("app.profiles.discord.process", "f.app.profiles.discord.process", "text"),
        ], cfg)
        self._add_group("grp_lang", [
            ("outbound.target_language", "f.outbound.target_language", "language"),
            ("control.languages", "f.control.languages", "csv"),
            ("inbound.target_language", "f.inbound.target_language", "language"),
            ("inbound.languages", "f.inbound.languages", "csv"),
        ], cfg)
        self._add_group("grp_ui", [
            ("ui.mode", "f.ui.mode", "uimode"),
            ("ui.lang", "f.ui.lang", "text"),
        ], cfg)
        self._add_group("grp_hotkeys", [
            ("hotkeys.enabled", "f.hotkeys.enabled", "bool"),
            ("hotkeys.translation_toggle", "f.hotkeys.translation_toggle", "hotkey"),
            ("hotkeys.subtitles_toggle", "f.hotkeys.subtitles_toggle", "hotkey"),
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
            ("audio.voice_rms_threshold", "f.audio.voice_rms_threshold", "float"),
            ("audio.voice_hangover_sec", "f.audio.voice_hangover_sec", "float"),
            ("audio.turn_end_silence_sec", "f.audio.turn_end_silence_sec", "float"),
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
        self._settings_layout.addStretch(1)

    def _add_group(self, title_key: str, fields: list[tuple[str, str, str]], cfg: dict) -> None:
        group = QtWidgets.QGroupBox(self._tr(title_key))
        form = QtWidgets.QFormLayout(group)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for path, label_key, kind in fields:
            widget = self._make_field(path, kind, _get_path(cfg, path))
            self._fields[path] = (widget, kind)
            form.addRow(self._tr(label_key), widget)
        self._settings_layout.addWidget(group)

    def _make_field(self, path: str, kind: str, value):
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
            return QtWidgets.QLineEdit(_as_csv(value))
        if kind == "hotkey":
            w = _HotkeyEdit()
            w.setKeySequence(QtGui.QKeySequence("" if value is None else str(value)))
            if hasattr(w, "setMaximumSequenceLength"):
                w.setMaximumSequenceLength(1)
            if hasattr(w, "setClearButtonEnabled"):
                w.setClearButtonEnabled(True)
            w.focus_in.connect(self._hotkeys.stop)
            w.focus_out.connect(lambda: self._sync_hotkeys(force=True))
            return w
        if kind == "language":
            w = self._build_language_picker()
            self._set_language_combo_value(w, "" if value is None else str(value))
            return w
        if kind == "float_csv":
            return QtWidgets.QLineEdit(_as_float_list(value))
        if kind == "appmode":
            w = _NoWheelComboBox()
            w.addItems(list(config_mod.APP_MODES))
            w.setCurrentText(str(value or "vrchat"))
            return w
        if kind == "uimode":
            w = _NoWheelComboBox()
            w.addItems(["auto", "vr", "desktop"])
            w.setCurrentText(str(value or "auto"))
            return w
        if kind == "hand":
            w = _NoWheelComboBox()
            w.addItems(["left", "right"])
            w.setCurrentText(str(value or "left"))
            return w
        if kind in ("input_device", "output_device"):
            w = _NoWheelComboBox()
            w.setEditable(True)
            names = self._inputs if kind == "input_device" else self._outputs
            w.addItems(names)
            w.setCurrentText("" if value is None else str(value))
            return w
        return QtWidgets.QLineEdit("" if value is None else str(value))

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
            return _from_csv(widget.text())
        if kind == "float_csv":
            return _from_float_list(widget.text())
        if kind == "hotkey":
            return widget.keySequence().toString(
                QtGui.QKeySequence.SequenceFormat.PortableText)
        if kind == "language":
            return self._code_from_language_combo(widget, [])
        if isinstance(widget, QtWidgets.QComboBox):
            return widget.currentText().strip()
        return widget.text()

    def _sync_settings_from_config(self) -> None:
        focus = QtWidgets.QApplication.focusWidget()
        for path, (widget, kind) in self._fields.items():
            if focus is not None and (focus is widget or widget.isAncestorOf(focus)):
                continue
            self._set_field_widget_value(widget, kind, _get_path(self._controller.raw_cfg, path))

    def _set_field_widget_value(self, widget, kind: str, value) -> None:
        blocked = widget.blockSignals(True)
        try:
            if kind == "bool":
                widget.setChecked(bool(value))
            elif kind == "language":
                self._set_language_combo_value(widget, "" if value is None else str(value))
            elif kind == "hotkey":
                widget.setKeySequence(QtGui.QKeySequence("" if value is None else str(value)))
            elif isinstance(widget, QtWidgets.QComboBox):
                widget.setCurrentText("" if value is None else str(value))
            elif kind == "csv":
                widget.setText(_as_csv(value))
            elif kind == "float_csv":
                widget.setText(_as_float_list(value))
            else:
                widget.setText("" if value is None else str(value))
        finally:
            widget.blockSignals(blocked)

    def _settings_from_fields(self) -> dict:
        cfg = copy.deepcopy(self._controller.raw_cfg)
        for path, (widget, kind) in self._fields.items():
            _set_path(cfg, path, self._field_value(widget, kind))
        return cfg

    # ---------------- actions ----------------
    def _start_update_check(self) -> None:
        if self._update_thread is not None:
            return

        def run():
            info = check_latest_release(__version__)
            if info is not None:
                self._signals.update_available.emit(info)

        self._update_thread = threading.Thread(
            target=run, daemon=True, name="vrclt-update-check")
        self._update_thread.start()

    def _update_available(self, info) -> None:
        self._update_info = info
        self._sync_update_banner()
        action = self._tray_actions.get("tray_update")
        if action is not None:
            action.setVisible(True)
        if not self._update_notified:
            self._update_notified = True
            self._tray.showMessage(
                self._tr("update_title"),
                self._update_message(info),
                QtWidgets.QSystemTrayIcon.MessageIcon.Information,
                10000,
            )

    def _sync_update_banner(self) -> None:
        if not hasattr(self, "_update_bar"):
            return
        info = self._update_info
        self._update_bar.setVisible(info is not None)
        if info is not None:
            self._update_text.setText(self._update_message(info))

    def _update_message(self, info) -> str:
        return self._tr("update_body").format(
            current=info.current_version,
            latest=info.latest_version,
        )

    def _open_update_release(self) -> None:
        info = self._update_info
        if info is None:
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(info.release_url))

    def _maybe_prompt_config_reset_after_update(self) -> None:
        previous = self._controller.last_config_version()
        if previous == __version__:
            return
        if not config_mod.CONFIG_PATH.exists():
            self._controller.mark_config_version_seen(__version__)
            return
        body = self._tr("reset_config_update_body").format(
            previous=previous or self._tr("version_unknown"),
            current=__version__,
        )
        reply = QtWidgets.QMessageBox.question(
            self,
            self._tr("reset_config_title"),
            body,
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._run_config_reset()
        else:
            self._controller.mark_config_version_seen(__version__)

    def _confirm_reset_config(self) -> None:
        reply = QtWidgets.QMessageBox.question(
            self,
            self._tr("reset_config_title"),
            self._tr("reset_config_body"),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._run_config_reset()

    def _run_config_reset(self) -> None:
        if self._reset_thread is not None and self._reset_thread.is_alive():
            return
        self._settings_note.setText(self._tr("msg_reset_restarting"))
        self._btn_reset_config.setEnabled(False)
        self._btn_save.setEnabled(False)

        def run():
            ok = self._controller.reset_config_preserving_language_lists(__version__)
            self._signals.reset_done.emit(ok)

        self._reset_thread = threading.Thread(target=run, daemon=True, name="vrclt-reset")
        self._reset_thread.start()

    def _reset_done(self, ok: bool) -> None:
        self._btn_reset_config.setEnabled(True)
        self._btn_save.setEnabled(True)
        self._settings_note.setText(
            self._tr("msg_reset_done") if ok else self._tr("msg_reset_failed"))
        self._sync_hotkeys(force=True)
        self._populate_settings()

    def _save_settings(self) -> None:
        try:
            cfg = self._settings_from_fields()
            key_error = config_mod.api_key_validation_error(cfg.get("api_key", ""))
            if key_error:
                raise ValueError(self._tr("err_api_key_url"))
            force_profile = (
                cfg.get("app", {}).get("mode")
                != self._controller.raw_cfg.get("app", {}).get("mode")
            )
            cfg = config_mod.apply_app_profile(cfg, force=force_profile)
            config_mod.save(cfg)
        except Exception as e:
            self._settings_note.setText(f"{self._tr('msg_save_failed')}: {e}")
            return
        self._settings_note.setText(self._tr("msg_save_restarting"))
        self._btn_save.setEnabled(False)

        def run():
            ok = self._controller.restart(cfg)
            self._signals.save_done.emit(ok)

        self._save_thread = threading.Thread(target=run, daemon=True, name="vrclt-restart")
        self._save_thread.start()

    def _save_done(self, ok: bool) -> None:
        self._btn_save.setEnabled(True)
        self._settings_note.setText(
            self._tr("msg_applied") if ok else self._tr("msg_saved_start_failed"))
        self._sync_hotkeys(force=True)
        self._populate_settings()

    def _restart_runtime(self) -> None:
        self._settings_note.setText(self._tr("msg_runtime_restarting"))
        threading.Thread(target=self._controller.restart, daemon=True,
                         name="vrclt-restart").start()

    def _reload_devices(self) -> None:
        self._inputs, self._outputs = _device_names()
        self._populate_settings()
        self._settings_note.setText(self._tr("msg_devices_refreshed"))

    def _apply_app_mode(self, mode: str) -> None:
        mode = (mode or "").strip()
        current = self._controller.cfg.get("app", {}).get("mode", "vrchat")
        if not mode or self._app_mode_applying:
            self._set_app_mode_checked(current)
            return
        try:
            cfg = copy.deepcopy(self._controller.raw_cfg)
            cfg.setdefault("app", {})["mode"] = mode
            cfg = config_mod.apply_app_profile(cfg, force=True)
            config_mod.save(cfg)
        except Exception as e:
            self._dashboard_note.setText(f"{self._tr('msg_mode_failed')}: {e}")
            self._set_app_mode_checked(current)
            return
        if mode == current and self._profile_runtime_snapshot(cfg) == \
                self._profile_runtime_snapshot(self._controller.cfg):
            self._set_app_mode_checked(current)
            return

        self._dashboard_note.setText(self._tr("msg_mode_applying"))
        self._app_mode_applying = True
        self._set_dashboard_apply_enabled(False)

        def run():
            ok = self._controller.restart(cfg)
            self._signals.mode_done.emit(ok)

        self._mode_thread = threading.Thread(target=run, daemon=True, name="vrclt-mode-restart")
        self._mode_thread.start()

    def _mode_done(self, ok: bool) -> None:
        self._app_mode_applying = False
        self._set_dashboard_apply_enabled(True)
        self._set_app_mode_checked(self._controller.cfg.get("app", {}).get("mode", "vrchat"))
        self._sync_text_only()
        self._dashboard_note.setText(
            self._tr("msg_mode_applied") if ok else self._tr("msg_saved_start_failed"))
        self._sync_hotkeys(force=True)
        self._populate_settings()

    def _set_dashboard_apply_enabled(self, enabled: bool) -> None:
        for btn in self._app_mode_buttons.values():
            btn.setEnabled(enabled)
        self._text_only.setEnabled(enabled)

    def _set_app_mode_checked(self, mode: str) -> None:
        for key, btn in self._app_mode_buttons.items():
            btn.setChecked(key == mode)

    @staticmethod
    def _profile_runtime_snapshot(cfg: dict) -> tuple:
        paths = (
            "inbound.process",
            "ui.mode",
            "outbound.voice_output",
            "outbound.passthrough_while_translating",
            "outbound.chatbox",
            "control.enabled",
            "overlay.enabled",
            "wrist_ui.enabled",
        )
        return tuple(_get_path(cfg, path) for path in paths)

    def _apply_text_only(self, enabled: bool) -> None:
        if self._app_mode_applying:
            self._sync_text_only()
            return
        try:
            cfg = copy.deepcopy(self._controller.raw_cfg)
            if enabled:
                cfg.setdefault("app", {})["mode"] = "vrchat"
            cfg.setdefault("outbound", {})["text_only"] = bool(enabled)
            cfg = config_mod.apply_app_profile(cfg, force=True)
            config_mod.save(cfg)
        except Exception as e:
            self._dashboard_note.setText(f"{self._tr('msg_text_only_failed')}: {e}")
            self._sync_text_only()
            return

        self._dashboard_note.setText(self._tr("msg_text_only_applying"))
        self._app_mode_applying = True
        self._set_dashboard_apply_enabled(False)

        def run():
            ok = self._controller.restart(cfg)
            self._signals.mode_done.emit(ok)

        self._mode_thread = threading.Thread(target=run, daemon=True, name="vrclt-text-only-restart")
        self._mode_thread.start()

    def _sync_text_only(self) -> None:
        blocked = self._text_only.blockSignals(True)
        try:
            self._text_only.setChecked(self._is_text_only(self._controller.cfg))
            self._text_only.setEnabled(
                not self._app_mode_applying
                and self._controller.cfg.get("app", {}).get("mode", "vrchat") == "vrchat")
        finally:
            self._text_only.blockSignals(blocked)

    @staticmethod
    def _is_text_only(cfg: dict) -> bool:
        ob = cfg.get("outbound", {})
        return bool(
            ob.get("text_only", False)
            or (not ob.get("voice_output", True)
                and ob.get("passthrough_while_translating", False)
                and ob.get("chatbox", False))
        )

    def _set_overlay_font_size(self, value: int) -> None:
        self._controller.set_overlay_font_size(value)
        self._desktop_overlay.refresh()

    def _toggle_overlay_move(self) -> None:
        st = self._controller.state
        st.edit_mode = not st.edit_mode
        if st.edit_mode:
            self._desktop_overlay.show_for_edit()

    def _reset_overlay_position(self) -> None:
        self._desktop_overlay.reset_position()
        self._controller.state.request_position_reset()

    def _toggle_translation(self) -> None:
        self._controller.set_translation_on(not self._controller.state.translation_on)

    def _toggle_subtitles(self) -> None:
        self._controller.set_subtitles_on(not self._controller.state.subtitles_on)

    def _sync_hotkeys(self, force: bool = False) -> None:
        cfg = self._controller.cfg.get("hotkeys", {})
        enabled = bool(cfg.get("enabled", True))
        translation = str(cfg.get("translation_toggle", "") or "")
        subtitles = str(cfg.get("subtitles_toggle", "") or "")
        pc_mode = resolve_ui_mode(self._controller.cfg) == "desktop"
        signature = (enabled, pc_mode, translation, subtitles)
        if not force and signature == self._hotkey_signature:
            return
        self._hotkey_signature = signature
        if not enabled or not pc_mode:
            self._hotkeys.configure([])
            return
        self._hotkeys.configure([
            HotkeyRegistration(
                HOTKEY_TRANSLATION_ID, "translation toggle", translation,
                self._signals.translation_hotkey.emit),
            HotkeyRegistration(
                HOTKEY_SUBTITLES_ID, "subtitles toggle", subtitles,
                self._signals.subtitles_hotkey.emit),
        ])

    def _add_output_language_from_input(self) -> None:
        self._add_language_from_input(
            self._out_lang_add,
            self._controller.cfg.get("control", {}).get("languages", []),
            self._controller.add_output_language,
        )

    def _add_inbound_language_from_input(self) -> None:
        self._add_language_from_input(
            self._sub_lang_add,
            self._controller.cfg.get("inbound", {}).get("languages", []),
            self._controller.add_inbound_language,
        )

    def _add_language_from_input(self, edit: QtWidgets.QComboBox, existing: list[str],
                                 add_fn) -> None:
        code = self._code_from_language_combo(edit, existing)
        if not code:
            return
        add_fn(code)
        edit.setCurrentIndex(-1)
        edit.setEditText("")
        self._dashboard_note.setText(self._tr("msg_applied"))

    def _pick_out_lang(self, label: str) -> None:
        code = self._code_for_label(label, self._controller.cfg.get("control", {}).get("languages", []))
        if code:
            self._controller.set_target_language(code)

    def _pick_sub_lang(self, label: str) -> None:
        code = self._code_for_label(label, self._controller.cfg.get("inbound", {}).get("languages", []))
        if code:
            self._controller.set_inbound_language(code)

    def _pick_ui_lang(self, label: str) -> None:
        for code, text in i18n.UI_LANG_LABELS.items():
            if text == label:
                self._controller.set_ui_lang(code)
                break

    def _pick_close_action(self) -> None:
        code = self._close_action.currentData()
        if code:
            self._controller.set_close_action(str(code))

    def _sync_close_action(self) -> None:
        blocked = self._close_action.blockSignals(True)
        try:
            current = self._controller.close_action()
            self._close_action.clear()
            for code in config_mod.CLOSE_ACTIONS:
                self._close_action.addItem(self._tr(f"close_action_{code}"), code)
            idx = self._close_action.findData(current)
            self._close_action.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            self._close_action.blockSignals(blocked)

    @staticmethod
    def _code_for_label(label: str, codes: list[str]) -> str:
        return language_code_from_text(label, codes)

    @staticmethod
    def _code_from_language_combo(combo: QtWidgets.QComboBox, fallback_codes: list[str]) -> str:
        text = combo.currentText().strip()
        data = combo.currentData()
        if data and (not text or text == language_label(str(data))):
            return str(data)
        return language_code_from_text(text, fallback_codes)

    @staticmethod
    def _set_language_combo_value(combo: QtWidgets.QComboBox, code: str) -> None:
        code = language_code_from_text(code)
        idx = combo.findData(code)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setCurrentIndex(-1)
            combo.setEditText(code)

    # ---------------- refresh ----------------
    def _refresh(self) -> None:
        st = self._controller.state
        if st.ui_lang != self._last_ui_lang:
            self._last_ui_lang = st.ui_lang
            _apply_app_font(QtWidgets.QApplication.instance(), st.ui_lang)
            self._apply_i18n()
            self._populate_settings()
        revision = getattr(self._controller, "config_revision", 0)
        if revision != self._last_config_revision:
            self._last_config_revision = revision
            self._sync_settings_from_config()
            self._sync_hotkeys()
        connected = self._controller.connected()
        status = self._controller.status
        color = "#2ea043" if connected else ("#d29922" if status == "Running" else "#8b949e")
        self._status_dot.setStyleSheet(f"background:{color}; border-radius:7px;")
        conn_key = "conn_on" if connected else "conn_off"
        self._status_text.setText(f"{self._status_label(status)} | {i18n.tr(st.ui_lang, conn_key)}")
        self._error_text.setText(self._error_label(self._controller.last_error))

        self._btn_trans.setText(i18n.tr(st.ui_lang, "btn_trans_on" if st.translation_on else "btn_trans_off"))
        self._btn_trans.setStyleSheet(
            "background:#2ea043;" if st.translation_on else "background:#78541e;")
        self._btn_sub.setText(i18n.tr(st.ui_lang, "btn_sub_on" if st.subtitles_on else "btn_sub_off"))
        self._btn_sub.setStyleSheet("background:#2870aa;" if st.subtitles_on else "")
        self._btn_overlay_move.setText(
            i18n.tr(st.ui_lang, "btn_overlay_done" if st.edit_mode else "btn_overlay_move"))
        self._btn_overlay_move.setStyleSheet("background:#2870aa;" if st.edit_mode else "")

        if not self._app_mode_applying:
            self._set_app_mode_checked(self._controller.cfg.get("app", {}).get("mode", "vrchat"))
            self._sync_text_only()

        blocked = self._overlay_font_size.blockSignals(True)
        try:
            self._overlay_font_size.setValue(
                int(self._controller.cfg.get("overlay", {}).get("font_size", 44)))
        finally:
            self._overlay_font_size.blockSignals(blocked)

        self._sync_combo(self._out_lang, [
            language_label(c) for c in self._controller.cfg.get("control", {}).get("languages", ["en"])
        ], language_label(st.target_language))
        self._sync_combo(self._sub_lang, [
            language_label(c) for c in self._controller.cfg.get("inbound", {}).get("languages", ["ko"])
        ], language_label(st.inbound_language))
        self._sync_combo(self._ui_lang, [i18n.UI_LANG_LABELS[c] for c in i18n.LANGS],
                         i18n.UI_LANG_LABELS.get(st.ui_lang, st.ui_lang))

        finals, partial = self._controller.subtitles_snapshot()
        rows = []
        for src, dst, _lang in finals:
            rows.append(dst or src)
        p_src, p_dst = partial
        if p_dst or p_src:
            rows.append(p_dst or p_src)
        text = "\n".join(rows)
        if self._subtitle_view.toPlainText() != text:
            self._subtitle_view.setPlainText(text)

    @staticmethod
    def _sync_combo(combo: QtWidgets.QComboBox, items: list[str], current: str) -> None:
        blocked = combo.blockSignals(True)
        try:
            existing = [combo.itemText(i) for i in range(combo.count())]
            if existing != items:
                combo.clear()
                combo.addItems(items)
            combo.setCurrentText(current)
        finally:
            combo.blockSignals(blocked)

    def _load_log_tail(self) -> None:
        try:
            text = self._log_file.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()[-300:]
            self._log_text.setPlainText("\n".join(lines))
        except FileNotFoundError:
            self._log_text.setPlainText(self._tr("msg_log_missing"))
        except Exception as e:
            self._log_text.setPlainText(f"{self._tr('msg_log_failed')}: {e}")

    # ---------------- window/tray lifecycle ----------------
    def _show_main(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _show_settings(self) -> None:
        self._tabs.setCurrentIndex(1)
        self._show_main()

    def closeEvent(self, event) -> None:
        if self._quitting:
            event.accept()
        elif self._controller.close_action() == "exit":
            event.accept()
            self._quit()
        else:
            event.ignore()
            self.hide()
            self._tray.showMessage("vrclt", self._tr("tray_still_running"),
                                   QtWidgets.QSystemTrayIcon.MessageIcon.Information, 1500)

    def _quit(self) -> None:
        self._quitting = True
        self._hotkeys.stop()
        self._desktop_overlay.close()
        self._tray.hide()
        self._controller.stop()
        QtWidgets.QApplication.quit()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child is not None:
                MainWindow._clear_layout(child)


def run_qt_app(controller, log_file: Path) -> int:
    app = QtWidgets.QApplication([])
    app.setApplicationName("vrclt")
    app.setQuitOnLastWindowClosed(False)
    _install_app_font(app, controller.state.ui_lang)
    win = MainWindow(controller, log_file)
    win.show()
    threading.Thread(target=controller.start, daemon=True, name="vrclt-start").start()
    app.aboutToQuit.connect(controller.stop)
    return app.exec()
