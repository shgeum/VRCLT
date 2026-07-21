"""PySide6 native UI for vrclt."""
from __future__ import annotations

import copy
import logging
import math
import threading
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from . import __version__
from . import config as config_mod
from . import i18n
from .app_controller import resolve_ui_mode
from .config import get_path as _get_path, set_path as _set_path
from .desktop_overlay import DesktopSubtitleOverlay
from .languages import language_code_from_text, language_label
from .hotkeys import HotkeyRegistration, WindowsGlobalHotkeys
from .resources import bundled_font, resolve_font_path
from .ui.settings_form import SettingsForm
from .ui.setup_banner import SetupBanner
from .ui.tray import TrayIcon
from .ui.update_banner import UpdateBanner
from .ui.widgets import (
    NoWheelComboBox,
    build_language_picker,
    code_from_language_combo,
    set_language_combo_value,
    set_language_picker_placeholder,
)

log = logging.getLogger(__name__)

APP_FONT_SIZE_PT = 11
HOTKEY_TRANSLATION_ID = 0x6100
HOTKEY_SUBTITLES_ID = 0x6101
HOTKEY_TRANSLATION_HOLD_ID = 0x6102
_APP_FONT_FAMILIES: dict[str, str] = {}


def _device_names() -> tuple[list[str], list[str]]:
    from .audio.devices import device_names
    return device_names()


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


class _MicLevelMeter(QtWidgets.QWidget):
    """Log-scaled mic RMS bar with the effective gate-threshold marker
    (marker jumps right while the echo guard boosts the gate)."""

    _LOG_MAX = math.log10(1 + 3000.0)  # RMS display ceiling

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setMinimumWidth(120)
        self._rms: float | None = None
        self._threshold: float | None = None

    def set_level(self, rms: float | None, threshold: float | None) -> None:
        if (rms, threshold) != (self._rms, self._threshold):
            self._rms = rms
            self._threshold = threshold
            self.update()

    @classmethod
    def _frac(cls, value: float) -> float:
        return max(0.0, min(1.0, math.log10(1 + max(0.0, value)) / cls._LOG_MAX))

    def paintEvent(self, event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 2, -1, -2)
        p.setPen(QtGui.QColor("#303542"))
        p.setBrush(QtGui.QColor("#1c1f29"))
        p.drawRoundedRect(r, 4, 4)
        if self._rms is not None and self._threshold is not None:
            frac = self._frac(self._rms)
            gate_open = self._rms >= self._threshold
            if frac > 0:
                bar = QtCore.QRectF(r.x() + 1, r.y() + 1,
                                    max(2.0, (r.width() - 2) * frac),
                                    r.height() - 2)
                p.setPen(QtCore.Qt.PenStyle.NoPen)
                p.setBrush(QtGui.QColor("#2ea043" if gate_open else "#8b949e"))
                p.drawRoundedRect(bar, 3, 3)
            tx = r.x() + 1 + (r.width() - 2) * self._frac(self._threshold)
            p.setPen(QtGui.QPen(QtGui.QColor("#d29922"), 2))
            p.drawLine(QtCore.QPointF(tx, r.y() + 1),
                       QtCore.QPointF(tx, r.bottom() - 1))
        p.end()


class _UiSignals(QtCore.QObject):
    refresh = QtCore.Signal()
    toast = QtCore.Signal(str)
    save_done = QtCore.Signal(bool)
    mode_done = QtCore.Signal(bool)
    device_done = QtCore.Signal(bool)
    reset_done = QtCore.Signal(bool)
    devices_reloaded = QtCore.Signal(bool)
    test_done = QtCore.Signal(bool, str)
    translation_hotkey = QtCore.Signal()
    subtitles_hotkey = QtCore.Signal()
    translation_hold = QtCore.Signal(bool)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, controller, log_file: Path):
        super().__init__()
        self._controller = controller
        self._log_file = Path(log_file)
        self._quitting = False
        self._i18n_widgets = {}
        self._i18n_groups = {}
        self._i18n_tooltips = {}
        self._tab_dashboard_idx = -1
        self._tab_settings_idx = -1
        self._tab_logs_idx = -1
        self._last_ui_lang = ""
        self._last_update_result = None
        self._last_config_revision = getattr(controller, "config_revision", 0)
        self._hotkey_signature = None
        self._hotkeys = WindowsGlobalHotkeys()
        self._save_thread = None
        self._mode_thread = None
        self._device_thread = None
        self._reset_thread = None
        self._test_thread = None
        self._app_mode_applying = False
        self._device_applying = False
        self._devices_reloading = False
        self._app_mode_buttons = {}
        self._inputs, self._outputs = _device_names()
        self._signals = _UiSignals()
        self._signals.refresh.connect(self._refresh)
        self._signals.toast.connect(self._show_toast)
        self._signals.save_done.connect(self._save_done)
        self._signals.mode_done.connect(self._mode_done)
        self._signals.device_done.connect(self._device_done)
        self._signals.reset_done.connect(self._reset_done)
        self._signals.devices_reloaded.connect(self._devices_reloaded)
        self._signals.test_done.connect(self._test_done)
        self._signals.translation_hotkey.connect(self._toggle_translation)
        self._signals.subtitles_hotkey.connect(self._toggle_subtitles)
        self._signals.translation_hold.connect(self._controller.set_hold_mute)

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
        # the mic meter needs a faster tick than the 250 ms refresh; runs
        # only while the dashboard tab is visible (gated in _refresh)
        self._meter_timer = QtCore.QTimer(self)
        self._meter_timer.setInterval(75)
        self._meter_timer.timeout.connect(self._tick_mic_meter)
        self._controller.subscribe(self._signals.refresh.emit)
        # worker threads only format a string here; tr() is a pure dict
        # lookup and the signal marshals delivery to the Qt thread
        self._controller.subscribe_errors(
            lambda key, detail: self._signals.toast.emit(
                f"{self._tr(key)}: {detail}"))
        self._sync_hotkeys()
        self._refresh()
        self._update_banner.result_ready.connect(self._on_update_result)
        self._update_banner.start_check(__version__)
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

    def _group(self, key: str) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox(self._tr(key))
        self._i18n_groups[key] = box
        return box

    def _tip(self, widget, key: str) -> None:
        """Register a retranslatable tooltip; skipped when the key is missing
        (tr() would show the raw key to the user)."""
        if not i18n.has(key):
            return
        widget.setToolTip(self._tr(key))
        self._i18n_tooltips.setdefault(key, []).append(widget)

    def _error_label(self, error: str) -> str:
        if error == "API key is empty.":
            return self._tr("err_api_key_empty")
        if error == "API key must be a Gemini API key, not a URL.":
            return self._tr("err_api_key_url")
        if error == "Qwen (DashScope) API key is empty.":
            return self._tr("err_qwen_api_key_empty")
        if error == "API key must be a DashScope API key, not a URL.":
            return self._tr("err_qwen_api_key_url")
        if error == "Qwen intl endpoint requires a Model Studio workspace ID.":
            return self._tr("err_qwen_workspace_required")
        return error

    def _apply_i18n(self) -> None:
        for key, widget in self._i18n_widgets.items():
            widget.setText(self._tr(key))
        for key, box in self._i18n_groups.items():
            box.setTitle(self._tr(key))
        for key, widgets in self._i18n_tooltips.items():
            for widget in widgets:
                widget.setToolTip(self._tr(key))
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
            set_language_picker_placeholder(self._out_lang_add, self._tr("ph_out_add"))
        if hasattr(self, "_out_lang_add_btn"):
            self._out_lang_add_btn.setText(self._tr("btn_add"))
        if hasattr(self, "_sub_lang_add"):
            set_language_picker_placeholder(self._sub_lang_add, self._tr("ph_sub_add"))
        if hasattr(self, "_sub_lang_add_btn"):
            self._sub_lang_add_btn.setText(self._tr("btn_add"))
        if hasattr(self, "_src_lang"):
            set_language_picker_placeholder(self._src_lang, self._tr("ph_src_auto"))
        if hasattr(self, "_in_src_lang"):
            set_language_picker_placeholder(self._in_src_lang, self._tr("ph_src_auto"))
        if hasattr(self, "_btn_overlay_reset"):
            self._btn_overlay_reset.setText(self._tr("btn_overlay_reset"))
        if hasattr(self, "_subtitle_view"):
            self._subtitle_view.setPlaceholderText(self._tr("subtitle_live_placeholder"))
        if hasattr(self, "_btn_devices"):
            self._btn_devices.setText(self._tr("btn_refresh_devices"))
        if hasattr(self, "_btn_test_out"):
            self._btn_test_out.setText(self._tr("btn_test_output"))
        if hasattr(self, "_btn_reset_config"):
            self._btn_reset_config.setText(self._tr("btn_reset_config"))
        if hasattr(self, "_btn_save"):
            self._btn_save.setText(self._tr("btn_save_restart"))
        if hasattr(self, "_btn_log_refresh"):
            self._btn_log_refresh.setText(self._tr("btn_refresh_log"))
        if hasattr(self, "_btn_check_update"):
            self._btn_check_update.setText(self._tr("btn_check_update"))
            self._render_update_status()
        if hasattr(self, "_about_text"):
            self._about_text.setText(self._tr("about_paths").format(config=config_mod.CONFIG_PATH))
        if hasattr(self, "_update_banner"):
            self._update_banner.retranslate()
        if hasattr(self, "_setup_banner"):
            self._setup_banner.retranslate()
        if hasattr(self, "_close_action"):
            self._sync_close_action()
        if hasattr(self, "_tray"):
            self._tray.retranslate()

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

        self._update_banner = UpdateBanner(self._tr, on_available=self._on_update_available)
        root.addWidget(self._update_banner)

        self._setup_banner = SetupBanner(
            self._tr,
            on_open_settings=lambda: self._tabs.setCurrentIndex(
                self._tab_settings_idx),
            on_open_url=QtGui.QDesktopServices.openUrl)
        root.addWidget(self._setup_banner)

        self._toast = QtWidgets.QLabel("")
        self._toast.setObjectName("errorText")
        self._toast.setWordWrap(True)
        self._toast.hide()
        root.addWidget(self._toast)
        self._toast_timer = QtCore.QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._toast.hide)

        self._btn_trans = QtWidgets.QPushButton()
        self._btn_trans.clicked.connect(
            lambda: self._controller.set_translation_on(not self._controller.state.translation_on))
        self._btn_sub = QtWidgets.QPushButton()
        self._btn_sub.clicked.connect(
            lambda: self._controller.set_subtitles_on(not self._controller.state.subtitles_on))
        self._out_lang = NoWheelComboBox()
        self._sub_lang = NoWheelComboBox()
        self._ui_lang = NoWheelComboBox()
        self._ui_lang.addItems([i18n.UI_LANG_LABELS[c] for c in i18n.LANGS])
        self._out_lang.currentTextChanged.connect(self._pick_out_lang)
        self._sub_lang.currentTextChanged.connect(self._pick_sub_lang)
        self._ui_lang.currentTextChanged.connect(self._pick_ui_lang)
        self._mic_device = self._build_dashboard_device_combo(
            "outbound.mic_device", self._inputs,
            self._controller.cfg.get("outbound", {}).get("mic_device", ""))
        self._voice_out_device = self._build_dashboard_device_combo(
            "outbound.tts_device", self._outputs,
            self._controller.cfg.get("outbound", {}).get("tts_device", ""))
        self._out_lang_add = build_language_picker(self._tr("ph_out_add"))
        self._out_lang_add.lineEdit().returnPressed.connect(self._add_output_language_from_input)
        self._out_lang_add_btn = QtWidgets.QPushButton(self._tr("btn_add"))
        self._out_lang_add_btn.clicked.connect(self._add_output_language_from_input)
        self._sub_lang_add = build_language_picker(self._tr("ph_sub_add"))
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
        self._overlay_font_size.setRange(config_mod.OVERLAY_FONT_MIN,
                                         config_mod.OVERLAY_FONT_MAX)
        self._overlay_font_size.setSuffix(" px")
        self._overlay_font_size.setValue(
            int(self._controller.cfg.get("overlay", {}).get("font_size", 27)))
        self._overlay_font_size.valueChanged.connect(self._set_overlay_font_size)
        self._close_action = NoWheelComboBox()
        self._sync_close_action()
        self._close_action.currentIndexChanged.connect(self._pick_close_action)
        self._dashboard_note = QtWidgets.QLabel("")
        self._dashboard_note.setObjectName("noteText")
        self._btn_overlay_move = QtWidgets.QPushButton()
        self._btn_overlay_move.clicked.connect(self._toggle_overlay_move)
        self._btn_overlay_reset = QtWidgets.QPushButton(self._tr("btn_overlay_reset"))
        self._btn_overlay_reset.clicked.connect(self._reset_overlay_position)
        self._btn_test_out = QtWidgets.QPushButton(self._tr("btn_test_output"))
        self._btn_test_out.setFixedWidth(72)
        self._btn_test_out.clicked.connect(self._test_output_device)
        out_device_wrap = QtWidgets.QWidget()
        out_device_layout = QtWidgets.QHBoxLayout(out_device_wrap)
        out_device_layout.setContentsMargins(0, 0, 0, 0)
        out_device_layout.setSpacing(6)
        out_device_layout.addWidget(self._voice_out_device, 1)
        out_device_layout.addWidget(self._btn_test_out)
        tts_gain_widget = self._build_tts_gain_control()
        self._mic_meter = _MicLevelMeter()
        # source languages (Qwen only - Gemini auto-detects, combos disabled)
        self._src_lang = build_language_picker(self._tr("ph_src_auto"))
        self._src_lang.activated.connect(lambda _i: self._pick_src_lang())
        self._src_lang.lineEdit().returnPressed.connect(self._pick_src_lang)
        self._in_src_lang = build_language_picker(self._tr("ph_src_auto"))
        self._in_src_lang.activated.connect(lambda _i: self._pick_in_src_lang())
        self._in_src_lang.lineEdit().returnPressed.connect(self._pick_in_src_lang)
        src_label = self._label("label_src_lang")
        in_src_label = self._label("label_in_src_lang")
        mic_label = self._label("label_mic_level")

        self._tip(app_mode_widget, "tip_app_mode")
        self._tip(self._text_only, "tip_text_only")
        self._tip(self._btn_trans, "tip_translate_toggle")
        self._tip(self._btn_sub, "tip_subtitles_toggle")
        self._tip(self._out_lang, "tip_out_lang")
        self._tip(self._sub_lang, "tip_sub_lang")
        self._tip(out_lang_add_widget, "tip_add_out_lang")
        self._tip(sub_lang_add_widget, "tip_add_sub_lang")
        self._tip(self._mic_device, "tip_mic_device")
        self._tip(self._voice_out_device, "tip_voice_out_device")
        self._tip(self._btn_test_out, "tip_test_output")
        self._tip(tts_gain_widget, "tip_tts_gain")
        self._tip(mic_label, "tip_mic_level")
        self._tip(self._mic_meter, "tip_mic_level")
        self._tip(src_label, "tip_src_lang")
        self._tip(self._src_lang, "tip_src_lang")
        self._tip(in_src_label, "tip_src_lang")
        self._tip(self._in_src_lang, "tip_src_lang")
        self._tip(self._overlay_font_size, "tip_pc_sub_size")
        self._tip(self._btn_overlay_move, "tip_overlay_move")
        self._tip(self._close_action, "tip_close_action")

        grp_mode = self._group("dash_grp_mode")
        mode_lay = QtWidgets.QHBoxLayout(grp_mode)
        mode_lay.addWidget(self._label("label_app_mode"))
        mode_lay.addWidget(app_mode_widget, 1)
        mode_lay.addWidget(self._text_only)

        grp_out = self._group("dash_grp_out")
        out_lay = QtWidgets.QGridLayout(grp_out)
        out_lay.addWidget(self._label("ctl_my_translate"), 0, 0)
        out_lay.addWidget(self._btn_trans, 0, 1)
        out_lay.addWidget(self._label("label_out_lang"), 1, 0)
        out_lay.addWidget(self._out_lang, 1, 1)
        out_lay.addWidget(self._label("label_add_out_lang"), 2, 0)
        out_lay.addWidget(out_lang_add_widget, 2, 1)
        out_lay.addWidget(src_label, 3, 0)
        out_lay.addWidget(self._src_lang, 3, 1)
        out_lay.setColumnStretch(1, 1)

        grp_in = self._group("dash_grp_in")
        in_lay = QtWidgets.QGridLayout(grp_in)
        in_lay.addWidget(self._label("ctl_their_sub"), 0, 0)
        in_lay.addWidget(self._btn_sub, 0, 1)
        in_lay.addWidget(self._label("label_sub_lang"), 1, 0)
        in_lay.addWidget(self._sub_lang, 1, 1)
        in_lay.addWidget(self._label("label_add_sub_lang"), 2, 0)
        in_lay.addWidget(sub_lang_add_widget, 2, 1)
        in_lay.addWidget(in_src_label, 3, 0)
        in_lay.addWidget(self._in_src_lang, 3, 1)
        in_lay.setColumnStretch(1, 1)

        pipes = QtWidgets.QHBoxLayout()
        pipes.addWidget(grp_out, 1)
        pipes.addWidget(grp_in, 1)

        grp_audio = self._group("dash_grp_audio")
        audio_lay = QtWidgets.QGridLayout(grp_audio)
        audio_lay.addWidget(self._label("label_mic_device"), 0, 0)
        audio_lay.addWidget(self._mic_device, 0, 1)
        audio_lay.addWidget(self._label("label_voice_out_device"), 0, 2)
        audio_lay.addWidget(out_device_wrap, 0, 3)
        audio_lay.addWidget(mic_label, 1, 0)
        audio_lay.addWidget(self._mic_meter, 1, 1)
        audio_lay.addWidget(self._label("label_tts_gain"), 1, 2)
        audio_lay.addWidget(tts_gain_widget, 1, 3)
        audio_lay.setColumnStretch(1, 1)
        audio_lay.setColumnStretch(3, 1)

        grp_display = self._group("dash_grp_display")
        disp_lay = QtWidgets.QHBoxLayout(grp_display)
        disp_lay.addWidget(self._label("label_pc_sub_size"))
        disp_lay.addWidget(self._overlay_font_size)
        disp_lay.addStretch(1)
        disp_lay.addWidget(self._btn_overlay_move)
        disp_lay.addWidget(self._btn_overlay_reset)

        grp_app = self._group("dash_grp_app")
        app_lay = QtWidgets.QHBoxLayout(grp_app)
        app_lay.addWidget(self._label("ui_lang"))
        app_lay.addWidget(self._ui_lang)
        app_lay.addSpacing(18)
        app_lay.addWidget(self._label("label_close_action"))
        app_lay.addWidget(self._close_action)
        app_lay.addStretch(1)

        root.addWidget(grp_mode)
        root.addLayout(pipes)
        root.addWidget(grp_audio)
        root.addWidget(grp_display)
        root.addWidget(grp_app)
        root.addWidget(self._dashboard_note)

        self._subtitle_view = QtWidgets.QPlainTextEdit()
        self._subtitle_view.setReadOnly(True)
        self._subtitle_view.setPlaceholderText(self._tr("subtitle_live_placeholder"))
        root.addWidget(self._subtitle_view, 1)
        self._tab_dashboard_idx = self._tabs.addTab(page, self._tr("tab_dashboard"))

    def _build_tts_gain_control(self) -> QtWidgets.QWidget:
        self._tts_gain_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self._tts_gain_slider.setRange(0, 200)
        self._tts_gain_slider.setPageStep(10)
        self._tts_gain_slider.setValue(round(self._controller.tts_gain() * 100))
        self._tts_gain_label = QtWidgets.QLabel(f"{self._tts_gain_slider.value()}%")
        self._tts_gain_label.setFixedWidth(48)
        # debounce: live label instantly, save+apply 200 ms after the last move
        self._tts_gain_timer = QtCore.QTimer(self)
        self._tts_gain_timer.setSingleShot(True)
        self._tts_gain_timer.setInterval(200)
        self._tts_gain_timer.timeout.connect(
            lambda: self._controller.set_tts_gain(self._tts_gain_slider.value() / 100.0))
        self._tts_gain_slider.valueChanged.connect(self._tts_gain_changed)
        wrap = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._tts_gain_slider, 1)
        layout.addWidget(self._tts_gain_label)
        return wrap

    def _tts_gain_changed(self, value: int) -> None:
        self._tts_gain_label.setText(f"{value}%")
        self._tts_gain_timer.start()

    def _tick_mic_meter(self) -> None:
        level = self._controller.mic_level()
        if level is None:
            self._mic_meter.set_level(None, None)
        else:
            self._mic_meter.set_level(*level)

    def _build_dashboard_device_combo(self, path: str, names: list[str], current: str) -> NoWheelComboBox:
        combo = NoWheelComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        combo.setMinimumContentsLength(18)
        self._sync_device_combo(combo, names, current or "")
        combo.activated.connect(lambda _idx, p=path, c=combo: self._apply_dashboard_device(p, c))
        line_edit = combo.lineEdit()
        if line_edit is not None:
            line_edit.returnPressed.connect(
                lambda p=path, c=combo: self._apply_dashboard_device(p, c))
            line_edit.editingFinished.connect(
                lambda p=path, c=combo: self._apply_dashboard_device(p, c))
        return combo

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

        self._settings_form = SettingsForm(
            self._controller, self._tr, self._settings_layout,
            get_devices=lambda: (self._inputs, self._outputs),
            on_hotkey_capture_start=self._hotkeys.stop,
            on_hotkey_capture_end=lambda: self._sync_hotkeys(force=True))
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
        update_row = QtWidgets.QHBoxLayout()
        self._btn_check_update = QtWidgets.QPushButton(self._tr("btn_check_update"))
        self._btn_check_update.clicked.connect(self._check_updates)
        self._update_status = QtWidgets.QLabel(
            self._tr("update_status_idle").format(current=__version__))
        self._update_status.setObjectName("noteText")
        self._update_status.setWordWrap(True)
        update_row.addWidget(self._btn_check_update)
        update_row.addWidget(self._update_status, 1)
        root.addWidget(self._label("label_log_file"))
        root.addWidget(self._log_path)
        root.addWidget(self._btn_log_refresh)
        root.addWidget(self._log_text, 1)
        root.addLayout(update_row)
        root.addWidget(self._about_text)
        self._tab_logs_idx = self._tabs.addTab(page, self._tr("tab_logs"))
        self._load_log_tail()

    def _build_tray(self) -> None:
        self._tray = TrayIcon(
            self, self._tr,
            on_show=self._show_main,
            on_show_settings=self._show_settings,
            on_open_update=lambda: self._update_banner.open_release(),
            on_toggle_translation=self._toggle_translation,
            on_toggle_subtitles=self._toggle_subtitles,
            on_quit=self._quit,
            on_message_clicked=lambda: self._update_banner.open_release())

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
            #setupBar {
                background: #1c1f29; border: 1px solid #2870aa; border-radius: 6px;
            }
            #setupTitle { color: #7db8e8; font-weight: 700; }
            #setupText { color: #c9d4e3; }
            QToolTip {
                background: #1c1f29; color: #f0f0f0;
                border: 1px solid #303542; padding: 4px 6px;
            }
            QPushButton[modeButton="true"] {
                background: #1c1f29; border: 1px solid #303542; border-radius: 8px;
                padding: 10px 14px; font-weight: 600;
            }
            QPushButton[modeButton="true"]:checked {
                background: #f0f0f0; color: #12141a; border: 2px solid #8b949e;
                font-weight: 800;
            }
        """)

    # ---------------- settings form (thin delegates; see ui/settings_form) ----
    def _populate_settings(self) -> None:
        self._settings_form.populate()

    def _sync_settings_from_config(self) -> None:
        self._settings_form.sync_from_config()

    def _sync_steamvr_autolaunch(self) -> None:
        self._settings_form.sync_steamvr_autolaunch()

    def _settings_from_fields(self) -> dict:
        return self._settings_form.config_from_fields()

    # ---------------- actions ----------------
    def _on_update_available(self, info, message: str) -> None:
        """Fires once (from the banner) when a newer release is found."""
        self._tray.set_update_visible(True)
        self._tray.show_message(self._tr("update_title"), message, 10000)

    def _show_toast(self, text: str, msecs: int = 8000) -> None:
        """Transient dashboard notice for background failures (Qt thread)."""
        self._toast.setText(text)
        self._toast.show()
        self._toast_timer.start(msecs)

    def _check_updates(self) -> None:
        if self._update_banner.start_check(__version__, force=True):
            self._btn_check_update.setEnabled(False)
            self._update_status.setToolTip("")
            self._update_status.setText(self._tr("update_checking"))

    def _on_update_result(self, result) -> None:
        self._last_update_result = result
        self._btn_check_update.setEnabled(True)
        self._render_update_status()

    def _render_update_status(self) -> None:
        result = self._last_update_result
        if result is None:
            self._update_status.setText(
                self._tr("update_status_idle").format(current=__version__))
            return
        self._update_status.setToolTip("")
        if result.status == "update":
            self._update_status.setText(
                self._tr("update_available_short").format(
                    latest=result.info.latest_version, current=__version__))
        elif result.status == "up_to_date":
            self._update_status.setText(
                self._tr("update_up_to_date").format(current=__version__))
        else:
            err_key = f"update_err_{result.error_kind}"
            reason = self._tr(err_key) if i18n.has(err_key) else result.detail
            self._update_status.setText(
                self._tr("update_check_failed").format(reason=reason))
            self._update_status.setToolTip(result.detail)

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

    def _spawn_restart(self, thread_name: str, op, done_signal) -> threading.Thread:
        """Run op() (a controller call returning ok) on a daemon worker and
        emit done_signal(ok) back onto the Qt thread."""
        def run():
            done_signal.emit(op())

        t = threading.Thread(target=run, daemon=True, name=thread_name)
        t.start()
        return t

    def _apply_config_async(self, build_cfg, *, fail_key: str, busy_key: str,
                            note: QtWidgets.QLabel, done_signal,
                            thread_name: str, on_busy,
                            on_build_error=None) -> threading.Thread | None:
        """Shared save-and-restart shape for the settings/dashboard handlers.
        build_cfg() runs on the Qt thread and must validate + config_mod.save(),
        returning the cfg to restart with (None = silent no-op). On exception
        the note shows '{fail_key}: {e}' and on_build_error() rolls the
        widgets back; on success the busy note is set, on_busy() disables the
        controls, and the restart runs on a worker via _spawn_restart."""
        try:
            cfg = build_cfg()
        except Exception as e:
            note.setText(f"{self._tr(fail_key)}: {e}")
            if on_build_error is not None:
                on_build_error()
            return None
        if cfg is None:
            return None
        note.setText(self._tr(busy_key))
        on_busy()
        return self._spawn_restart(
            thread_name, lambda: self._controller.restart(cfg), done_signal)

    def _run_config_reset(self) -> None:
        if self._reset_thread is not None and self._reset_thread.is_alive():
            return
        self._settings_note.setText(self._tr("msg_reset_restarting"))
        self._btn_reset_config.setEnabled(False)
        self._btn_save.setEnabled(False)
        self._reset_thread = self._spawn_restart(
            "vrclt-reset",
            lambda: self._controller.reset_config_preserving_language_lists(__version__),
            self._signals.reset_done)

    def _reset_done(self, ok: bool) -> None:
        self._btn_reset_config.setEnabled(True)
        self._btn_save.setEnabled(True)
        self._settings_note.setText(
            self._tr("msg_reset_done") if ok else self._tr("msg_reset_failed"))
        self._sync_hotkeys(force=True)
        self._populate_settings()

    def _save_settings(self) -> None:
        def build():
            cfg = self._settings_from_fields()
            key_error = config_mod.api_key_validation_error(cfg.get("api_key", ""))
            if key_error:
                raise ValueError(self._tr("err_api_key_url"))
            qwen_key_error = config_mod.api_key_validation_error(
                cfg.get("qwen", {}).get("api_key", ""), provider_label="DashScope")
            if qwen_key_error:
                raise ValueError(self._tr("err_qwen_api_key_url"))
            qw = cfg.get("qwen", {})
            if config_mod.provider(cfg) == "qwen" \
                    and str(qw.get("endpoint", "intl") or "intl").strip() != "beijing" \
                    and not str(qw.get("workspace_id", "") or "").strip() \
                    and not str(qw.get("base_url", "") or "").strip():
                raise ValueError(self._tr("err_qwen_workspace_required"))
            force_profile = (
                cfg.get("app", {}).get("mode")
                != self._controller.raw_cfg.get("app", {}).get("mode")
            )
            cfg = config_mod.apply_app_profile(cfg, force=force_profile)
            config_mod.save(cfg)
            return cfg

        thread = self._apply_config_async(
            build, fail_key="msg_save_failed", busy_key="msg_save_restarting",
            note=self._settings_note, done_signal=self._signals.save_done,
            thread_name="vrclt-restart",
            on_busy=lambda: self._btn_save.setEnabled(False))
        if thread is not None:
            self._save_thread = thread

    def _save_done(self, ok: bool) -> None:
        self._btn_save.setEnabled(True)
        self._settings_note.setText(
            self._tr("msg_applied") if ok else self._tr("msg_saved_start_failed"))
        self._sync_hotkeys(force=True)
        self._populate_settings()

    def _restart_runtime(self) -> None:
        self._settings_note.setText(self._tr("msg_runtime_restarting"))
        self._controller.restart_async()

    def _reload_devices(self) -> None:
        """Refresh device lists via a runtime restart with a PortAudio
        reinit (the only way hot-plugged devices become visible)."""
        if self._devices_reloading:
            return
        self._devices_reloading = True
        self._btn_devices.setEnabled(False)
        self._btn_test_out.setEnabled(False)
        self._settings_note.setText(self._tr("msg_devices_refreshing"))
        self._spawn_restart("vrclt-device-reload",
                            self._controller.reinit_audio_devices,
                            self._signals.devices_reloaded)

    def _devices_reloaded(self, ok: bool) -> None:
        self._devices_reloading = False
        self._inputs, self._outputs = _device_names()
        self._btn_devices.setEnabled(True)
        self._btn_test_out.setEnabled(True)
        self._sync_dashboard_devices(force=True)
        self._populate_settings()
        self._settings_note.setText(
            self._tr("msg_devices_refreshed") if ok
            else self._tr("msg_saved_start_failed"))

    def _test_output_device(self) -> None:
        """Play a short test tone on the (unsaved) output-combo selection."""
        if (self._test_thread is not None and self._test_thread.is_alive()) \
                or self._device_applying or self._devices_reloading:
            return
        value = self._voice_out_device.currentText().strip()
        self._btn_test_out.setEnabled(False)
        self._btn_devices.setEnabled(False)
        self._dashboard_note.setText(self._tr("msg_test_playing"))

        def run():
            try:
                from .audio.devices import sine_test
                sine_test(value, seconds=1.0)
                self._signals.test_done.emit(True, "")
            except Exception as e:
                self._signals.test_done.emit(False, str(e))

        self._test_thread = threading.Thread(
            target=run, daemon=True, name="vrclt-sound-test")
        self._test_thread.start()

    def _test_done(self, ok: bool, error: str) -> None:
        self._btn_test_out.setEnabled(not self._devices_reloading)
        self._btn_devices.setEnabled(not self._devices_reloading)
        self._dashboard_note.setText(
            "" if ok else f"{self._tr('msg_test_failed')}: {error}")

    def _apply_dashboard_device(self, path: str, combo: QtWidgets.QComboBox) -> None:
        if self._device_applying:
            self._sync_dashboard_devices()
            return
        value = combo.currentText().strip()
        current = str(_get_path(self._controller.raw_cfg, path, "") or "")
        if value == current:
            return

        def build():
            cfg = copy.deepcopy(self._controller.raw_cfg)
            _set_path(cfg, path, value)
            cfg = config_mod.apply_app_profile(cfg)
            config_mod.save(cfg)
            return cfg

        def busy():
            self._device_applying = True
            self._set_dashboard_apply_enabled(False)

        thread = self._apply_config_async(
            build, fail_key="msg_device_failed", busy_key="msg_device_applying",
            note=self._dashboard_note, done_signal=self._signals.device_done,
            thread_name="vrclt-device-restart", on_busy=busy,
            on_build_error=self._sync_dashboard_devices)
        if thread is not None:
            self._device_thread = thread

    def _device_done(self, ok: bool) -> None:
        self._device_applying = False
        self._set_dashboard_apply_enabled(True)
        self._dashboard_note.setText(
            self._tr("msg_applied") if ok else self._tr("msg_saved_start_failed"))
        self._sync_dashboard_devices(force=True)
        self._populate_settings()

    def _apply_app_mode(self, mode: str) -> None:
        mode = (mode or "").strip()
        current = self._controller.cfg.get("app", {}).get("mode", "vrchat")
        if not mode or self._app_mode_applying:
            self._set_app_mode_checked(current)
            return

        def build():
            cfg = copy.deepcopy(self._controller.raw_cfg)
            cfg.setdefault("app", {})["mode"] = mode
            cfg = config_mod.apply_app_profile(cfg, force=True)
            if mode == current and self._profile_runtime_snapshot(cfg) == \
                    self._profile_runtime_snapshot(self._controller.cfg):
                # clicking the already-selected mode: nothing to write or restart
                self._set_app_mode_checked(current)
                return None
            config_mod.save(cfg)
            return cfg

        def busy():
            self._app_mode_applying = True
            self._set_dashboard_apply_enabled(False)

        thread = self._apply_config_async(
            build, fail_key="msg_mode_failed", busy_key="msg_mode_applying",
            note=self._dashboard_note, done_signal=self._signals.mode_done,
            thread_name="vrclt-mode-restart", on_busy=busy,
            on_build_error=lambda: self._set_app_mode_checked(current))
        if thread is not None:
            self._mode_thread = thread

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
        if hasattr(self, "_mic_device"):
            self._mic_device.setEnabled(enabled)
        if hasattr(self, "_voice_out_device"):
            self._voice_out_device.setEnabled(enabled)
        if hasattr(self, "_btn_test_out"):
            self._btn_test_out.setEnabled(enabled)

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

        def build():
            cfg = copy.deepcopy(self._controller.raw_cfg)
            if enabled:
                cfg.setdefault("app", {})["mode"] = "vrchat"
            cfg.setdefault("outbound", {})["text_only"] = bool(enabled)
            cfg = config_mod.apply_app_profile(cfg, force=True)
            config_mod.save(cfg)
            return cfg

        def busy():
            self._app_mode_applying = True
            self._set_dashboard_apply_enabled(False)

        thread = self._apply_config_async(
            build, fail_key="msg_text_only_failed", busy_key="msg_text_only_applying",
            note=self._dashboard_note, done_signal=self._signals.mode_done,
            thread_name="vrclt-text-only-restart", on_busy=busy,
            on_build_error=self._sync_text_only)
        if thread is not None:
            self._mode_thread = thread

    def _sync_text_only(self) -> None:
        blocked = self._text_only.blockSignals(True)
        try:
            self._text_only.setChecked(config_mod.is_text_only(self._controller.cfg))
            self._text_only.setEnabled(
                not self._app_mode_applying
                and self._controller.cfg.get("app", {}).get("mode", "vrchat") == "vrchat")
        finally:
            self._text_only.blockSignals(blocked)

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
        enabled_in_vr = bool(cfg.get("enabled_in_vr", True))
        translation = str(cfg.get("translation_toggle", "") or "")
        subtitles = str(cfg.get("subtitles_toggle", "") or "")
        hold = str(cfg.get("translation_hold", "") or "")
        pc_mode = resolve_ui_mode(self._controller.cfg) == "desktop"
        active = enabled and (pc_mode or enabled_in_vr)
        signature = (active, translation, subtitles, hold)
        if not force and signature == self._hotkey_signature:
            return
        self._hotkey_signature = signature
        if not active:
            self._hotkeys.configure([])
            return
        self._hotkeys.configure([
            HotkeyRegistration(
                HOTKEY_TRANSLATION_ID, "translation toggle", translation,
                self._signals.translation_hotkey.emit),
            HotkeyRegistration(
                HOTKEY_SUBTITLES_ID, "subtitles toggle", subtitles,
                self._signals.subtitles_hotkey.emit),
            HotkeyRegistration(
                HOTKEY_TRANSLATION_HOLD_ID, "translation hold", hold,
                lambda: self._signals.translation_hold.emit(True),
                on_release=lambda: self._signals.translation_hold.emit(False)),
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
        code = code_from_language_combo(edit, existing)
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

    def _pick_src_lang(self) -> None:
        self._controller.set_source_language(
            code_from_language_combo(self._src_lang, []))

    def _pick_in_src_lang(self) -> None:
        self._controller.set_inbound_source_language(
            code_from_language_combo(self._in_src_lang, []))

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
        # unconditional: cheap signature early-out, and it un-stales the
        # ui.mode=auto gate when SteamVR starts/stops between config saves
        self._sync_hotkeys()
        connected, status_key, detail = self._controller.get_status_info()
        if connected:
            color = "#2ea043"
        elif status_key in ("status_api_key_invalid", "status_api_key_required",
                            "status_failed"):
            color = "#e06450"
        elif status_key in ("status_running", "status_degraded",
                            "status_reconnecting", "status_quota_exceeded"):
            color = "#d29922"
        else:
            color = "#8b949e"
        self._set_style_if_changed(self._status_dot, f"background:{color}; border-radius:7px;")
        conn_key = "conn_on" if connected else "conn_off"
        self._status_text.setText(
            f"{i18n.tr(st.ui_lang, status_key)} | {i18n.tr(st.ui_lang, conn_key)}")
        self._error_text.setText(self._error_label(detail))

        cfg = self._controller.cfg
        prov = config_mod.provider(cfg)
        self._setup_banner.sync(
            prov, bool(config_mod.api_key_for(cfg, prov)),
            str(cfg.get("qwen", {}).get("endpoint", "intl") or "intl").strip())

        self._btn_trans.setText(i18n.tr(st.ui_lang, "btn_trans_on" if st.translation_on else "btn_trans_off"))
        self._set_style_if_changed(
            self._btn_trans,
            "background:#2ea043;" if st.translation_on else "background:#78541e;")
        self._btn_sub.setText(i18n.tr(st.ui_lang, "btn_sub_on" if st.subtitles_on else "btn_sub_off"))
        self._set_style_if_changed(
            self._btn_sub, "background:#2870aa;" if st.subtitles_on else "")
        self._btn_overlay_move.setText(
            i18n.tr(st.ui_lang, "btn_overlay_done" if st.edit_mode else "btn_overlay_move"))
        self._set_style_if_changed(
            self._btn_overlay_move, "background:#2870aa;" if st.edit_mode else "")

        if not self._app_mode_applying:
            self._set_app_mode_checked(self._controller.cfg.get("app", {}).get("mode", "vrchat"))
            self._sync_text_only()

        blocked = self._overlay_font_size.blockSignals(True)
        try:
            self._overlay_font_size.setValue(
                int(self._controller.cfg.get("overlay", {}).get("font_size", 27)))
        finally:
            self._overlay_font_size.blockSignals(blocked)

        if not self._tts_gain_slider.isSliderDown() and \
                not self._tts_gain_timer.isActive():
            blocked = self._tts_gain_slider.blockSignals(True)
            try:
                self._tts_gain_slider.setValue(
                    round(self._controller.tts_gain() * 100))
                self._tts_gain_label.setText(f"{self._tts_gain_slider.value()}%")
            finally:
                self._tts_gain_slider.blockSignals(blocked)
        want_meter = self.isVisible() and \
            self._tabs.currentIndex() == self._tab_dashboard_idx
        if want_meter != self._meter_timer.isActive():
            (self._meter_timer.start if want_meter else self._meter_timer.stop)()

        self._sync_combo(self._out_lang, [
            language_label(c) for c in self._controller.cfg.get("control", {}).get("languages", ["en"])
        ], language_label(st.target_language))
        self._sync_combo(self._sub_lang, [
            language_label(c) for c in self._controller.cfg.get("inbound", {}).get("languages", ["ko"])
        ], language_label(st.inbound_language))
        is_qwen = self._controller.get_provider() == "qwen"
        for combo, code in ((self._src_lang, st.source_language),
                            (self._in_src_lang, st.inbound_source_language)):
            if combo.isEnabled() != is_qwen:
                combo.setEnabled(is_qwen)
            if not combo.hasFocus() and \
                    code_from_language_combo(combo, []) != code:
                blocked = combo.blockSignals(True)
                try:
                    set_language_combo_value(combo, code)
                finally:
                    combo.blockSignals(blocked)
        self._sync_combo(self._ui_lang, [i18n.UI_LANG_LABELS[c] for c in i18n.LANGS],
                         i18n.UI_LANG_LABELS.get(st.ui_lang, st.ui_lang))
        self._sync_dashboard_devices()
        self._sync_steamvr_autolaunch()

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

    def _set_style_if_changed(self, widget: QtWidgets.QWidget, css: str) -> None:
        # setStyleSheet forces a re-polish/repaint even when unchanged; the
        # 250 ms refresh timer calls this constantly, so diff first
        cache = getattr(self, "_style_cache", None)
        if cache is None:
            cache = self._style_cache = {}
        key = id(widget)
        if cache.get(key) != css:
            cache[key] = css
            widget.setStyleSheet(css)

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

    def _sync_dashboard_devices(self, force: bool = False) -> None:
        if not hasattr(self, "_mic_device") or not hasattr(self, "_voice_out_device"):
            return
        if self._device_applying and not force:
            return
        focus = QtWidgets.QApplication.focusWidget()
        mic_active = focus is not None and (
            focus is self._mic_device or self._mic_device.isAncestorOf(focus))
        out_active = focus is not None and (
            focus is self._voice_out_device or self._voice_out_device.isAncestorOf(focus))
        if force or not mic_active:
            self._sync_device_combo(
                self._mic_device,
                self._inputs,
                self._controller.cfg.get("outbound", {}).get("mic_device", ""))
        if force or not out_active:
            self._sync_device_combo(
                self._voice_out_device,
                self._outputs,
                self._controller.cfg.get("outbound", {}).get("tts_device", ""))

    @staticmethod
    def _sync_device_combo(combo: QtWidgets.QComboBox, items: list[str], current: str) -> None:
        current = "" if current is None else str(current)
        values = list(items or [""])
        if "" not in values:
            values.insert(0, "")
        if current and current not in values:
            values.append(current)
        blocked = combo.blockSignals(True)
        try:
            existing = [combo.itemText(i) for i in range(combo.count())]
            if existing != values:
                combo.clear()
                combo.addItems(values)
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
            self._tray.show_message("vrclt", self._tr("tray_still_running"), 1500)

    def _quit(self) -> None:
        self._quitting = True
        self._hotkeys.stop()
        self._desktop_overlay.close()
        self._tray.hide()
        # shutdown (not stop): a restart queued behind the lifecycle lock
        # must not resurrect the runtime during interpreter teardown
        self._controller.shutdown()
        QtWidgets.QApplication.quit()


def run_qt_app(controller, log_file: Path) -> int:
    app = QtWidgets.QApplication([])
    app.setApplicationName("vrclt")
    app.setQuitOnLastWindowClosed(False)
    _install_app_font(app, controller.state.ui_lang)
    win = MainWindow(controller, log_file)
    win.show()
    threading.Thread(target=controller.start, daemon=True, name="vrclt-start").start()
    app.aboutToQuit.connect(controller.shutdown)
    return app.exec()
