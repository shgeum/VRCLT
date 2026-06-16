"""PySide6 native UI for vrclt."""
from __future__ import annotations

import copy
import logging
import threading
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from . import config as config_mod
from . import i18n
from .desktop_overlay import DesktopSubtitleOverlay

log = logging.getLogger(__name__)

LANG_LABELS = {
    "ja": "日本語", "en": "English", "ko": "한국어",
    "zh-Hans": "中文(简)", "zh-Hant": "中文(繁)", "yue": "廣東話",
    "es": "Español", "ru": "Русский", "fr": "Français", "de": "Deutsch",
}


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


class _UiSignals(QtCore.QObject):
    refresh = QtCore.Signal()
    save_done = QtCore.Signal(bool)
    mode_done = QtCore.Signal(bool)


class _NoWheelComboBox(QtWidgets.QComboBox):
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, controller, log_file: Path):
        super().__init__()
        self._controller = controller
        self._log_file = Path(log_file)
        self._quitting = False
        self._fields = {}
        self._save_thread = None
        self._mode_thread = None
        self._app_mode_applying = False
        self._app_mode_buttons = {}
        self._inputs, self._outputs = _device_names()
        self._signals = _UiSignals()
        self._signals.refresh.connect(self._refresh)
        self._signals.save_done.connect(self._save_done)
        self._signals.mode_done.connect(self._mode_done)

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
        self._refresh()

    # ---------------- construction ----------------
    def _build_dashboard(self) -> None:
        page = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(page)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        top = QtWidgets.QHBoxLayout()
        self._status_dot = QtWidgets.QLabel()
        self._status_dot.setFixedSize(14, 14)
        self._status_text = QtWidgets.QLabel("Stopped")
        self._status_text.setObjectName("statusText")
        self._error_text = QtWidgets.QLabel("")
        self._error_text.setObjectName("errorText")
        self._error_text.setWordWrap(True)
        top.addWidget(self._status_dot)
        top.addWidget(self._status_text)
        top.addStretch(1)
        self._btn_restart = QtWidgets.QPushButton("Restart runtime")
        self._btn_restart.clicked.connect(self._restart_runtime)
        top.addWidget(self._btn_restart)
        root.addLayout(top)
        root.addWidget(self._error_text)

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
        app_mode_widget = self._build_app_mode_toggle()
        self._text_only = QtWidgets.QCheckBox("텍스트 온리")
        self._text_only.toggled.connect(self._apply_text_only)
        self._overlay_font_size = QtWidgets.QSpinBox()
        self._overlay_font_size.setRange(18, 72)
        self._overlay_font_size.setSuffix(" px")
        self._overlay_font_size.setValue(
            int(self._controller.cfg.get("overlay", {}).get("font_size", 44)))
        self._overlay_font_size.valueChanged.connect(self._set_overlay_font_size)
        self._dashboard_note = QtWidgets.QLabel("")
        self._dashboard_note.setObjectName("noteText")
        self._btn_overlay_move = QtWidgets.QPushButton()
        self._btn_overlay_move.clicked.connect(self._toggle_overlay_move)
        self._btn_overlay_reset = QtWidgets.QPushButton("자막 위치 리셋")
        self._btn_overlay_reset.clicked.connect(self._reset_overlay_position)
        controls.addWidget(QtWidgets.QLabel("앱 모드"), 0, 0)
        controls.addWidget(app_mode_widget, 0, 1, 1, 2)
        controls.addWidget(self._text_only, 0, 3)
        controls.addWidget(QtWidgets.QLabel("내 말 번역"), 1, 0)
        controls.addWidget(self._btn_trans, 1, 1)
        controls.addWidget(QtWidgets.QLabel("출력 언어"), 1, 2)
        controls.addWidget(self._out_lang, 1, 3)
        controls.addWidget(QtWidgets.QLabel("상대 말 자막"), 2, 0)
        controls.addWidget(self._btn_sub, 2, 1)
        controls.addWidget(QtWidgets.QLabel("자막 언어"), 2, 2)
        controls.addWidget(self._sub_lang, 2, 3)
        controls.addWidget(QtWidgets.QLabel("UI 언어"), 3, 0)
        controls.addWidget(self._ui_lang, 3, 1)
        controls.addWidget(QtWidgets.QLabel("PC 자막 크기"), 3, 2)
        controls.addWidget(self._overlay_font_size, 3, 3)
        controls.addWidget(self._btn_overlay_move, 4, 2)
        controls.addWidget(self._btn_overlay_reset, 4, 3)
        root.addLayout(controls)
        root.addWidget(self._dashboard_note)

        self._subtitle_view = QtWidgets.QPlainTextEdit()
        self._subtitle_view.setReadOnly(True)
        self._subtitle_view.setPlaceholderText("실시간 자막이 여기에 표시됩니다.")
        root.addWidget(self._subtitle_view, 1)
        self._tabs.addTab(page, "Dashboard")

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
        self._btn_devices = QtWidgets.QPushButton("장치 목록 새로고침")
        self._btn_devices.clicked.connect(self._reload_devices)
        self._btn_save = QtWidgets.QPushButton("설정 저장 및 재시작")
        self._btn_save.clicked.connect(self._save_settings)
        self._settings_note = QtWidgets.QLabel("")
        self._settings_note.setObjectName("noteText")
        buttons.addWidget(self._settings_note, 1)
        buttons.addWidget(self._btn_devices)
        buttons.addWidget(self._btn_save)
        outer.addLayout(buttons)

        self._populate_settings()
        self._tabs.addTab(page, "Settings")

    def _build_logs(self) -> None:
        page = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(page)
        root.setContentsMargins(18, 18, 18, 18)
        self._log_path = QtWidgets.QLabel(str(self._log_file))
        self._log_text = QtWidgets.QPlainTextEdit()
        self._log_text.setReadOnly(True)
        btn = QtWidgets.QPushButton("로그 새로고침")
        btn.clicked.connect(self._load_log_tail)
        about = QtWidgets.QLabel(
            f"Config: {config_mod.CONFIG_PATH}\n"
            "Standalone mode stores settings in AppData when running as an exe."
        )
        about.setWordWrap(True)
        root.addWidget(QtWidgets.QLabel("Log file"))
        root.addWidget(self._log_path)
        root.addWidget(btn)
        root.addWidget(self._log_text, 1)
        root.addWidget(about)
        self._tabs.addTab(page, "Logs/About")
        self._load_log_tail()

    def _build_tray(self) -> None:
        self._tray = QtWidgets.QSystemTrayIcon(self._make_icon(), self)
        self._tray.setToolTip("vrclt")
        menu = QtWidgets.QMenu(self)
        act_show = menu.addAction("창 열기")
        act_settings = menu.addAction("설정 열기")
        menu.addSeparator()
        act_trans = menu.addAction("번역 ON/OFF")
        act_sub = menu.addAction("자막 ON/OFF")
        menu.addSeparator()
        act_quit = menu.addAction("종료")
        act_show.triggered.connect(self._show_main)
        act_settings.triggered.connect(self._show_settings)
        act_trans.triggered.connect(
            lambda: self._controller.set_translation_on(not self._controller.state.translation_on))
        act_sub.triggered.connect(
            lambda: self._controller.set_subtitles_on(not self._controller.state.subtitles_on))
        act_quit.triggered.connect(self._quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda reason: self._show_main()
            if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger else None)
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
            QTabBar::tab { padding: 8px 14px; background: #1c1f29; }
            QTabBar::tab:selected { background: #2a3040; }
            QGroupBox { border: 1px solid #303542; border-radius: 6px; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
                background: #1c1f29; color: #f0f0f0; border: 1px solid #303542;
                border-radius: 4px; padding: 4px;
            }
            QPushButton { background: #2a3040; color: #f0f0f0; border: 0; border-radius: 4px; padding: 7px 12px; }
            QPushButton:hover { background: #384259; }
            #statusText { font-weight: 700; }
            #errorText { color: #ffb4a8; }
            #noteText { color: #9aa0ad; }
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
        self._add_group("기본 / API", [
            ("api_key", "API 키", "password"),
            ("model", "모델", "text"),
            ("app.mode", "기본 실행 대상", "appmode"),
            ("app.profiles.discord.process", "Discord 캡처 프로세스", "text"),
        ], cfg)
        self._add_group("언어", [
            ("outbound.target_language", "기본 출력 언어", "text"),
            ("control.languages", "출력 언어 목록", "csv"),
            ("inbound.target_language", "기본 자막 언어", "text"),
            ("inbound.languages", "자막 언어 목록", "csv"),
        ], cfg)
        self._add_group("UI", [
            ("ui.mode", "UI 모드", "uimode"),
            ("ui.lang", "UI 언어(auto/en/ko/ja/zh)", "text"),
        ], cfg)
        self._add_group("장치", [
            ("outbound.mic_device", "마이크 입력", "input_device"),
            ("outbound.text_only", "텍스트 온리(원음 패스스루 + 챗박스)", "bool"),
            ("outbound.tts_device", "번역 음성 출력", "output_device"),
            ("outbound.monitor_device", "번역 음성 모니터", "output_device"),
            ("inbound.audio_device", "인바운드 음성 출력", "output_device"),
            ("inbound.process", "캡처 프로세스", "text"),
        ], cfg)
        self._add_group("오디오 / 게이팅", [
            ("audio.voice_rms_threshold", "음성 감지 임계값", "float"),
            ("audio.voice_hangover_sec", "발화 유지(초)", "float"),
            ("audio.echo_guard_multiplier", "에코 가드 배수", "float"),
            ("audio.send_interval_ms", "전송 주기(ms)", "int"),
            ("audio.finalize_silence_sec", "문장 확정 침묵(초)", "float"),
            ("audio.mic_idle_disconnect_sec", "마이크 유휴 연결 해제(초)", "float"),
            ("outbound.echo_target_language", "대상언어 입력도 따라말함", "bool"),
            ("inbound.vad_enabled", "VAD 사용", "bool"),
            ("inbound.vad_threshold", "VAD 임계값", "float"),
            ("inbound.vad_hangover_sec", "VAD 유지(초)", "float"),
            ("inbound.play_audio", "인바운드 음성 재생", "bool"),
        ], cfg)
        self._add_group("OSC / VR", [
            ("outbound.chatbox", "VRChat 챗박스 전송", "bool"),
            ("osc.ip", "OSC IP", "text"),
            ("osc.port", "OSC 포트", "int"),
            ("osc.throttle_sec", "OSC 전송 간격(초)", "float"),
            ("osc.notification_sfx", "챗박스 알림음", "bool"),
            ("osc.show_source", "챗박스 원문 표시", "bool"),
            ("osc.chunk_display_sec", "긴 메시지 조각 표시(초)", "float"),
            ("control.enabled", "아바타 OSC 제어", "bool"),
            ("control.osc_listen_port", "OSC 수신 포트", "int"),
            ("control.feedback_chatbox", "제어 변경 챗박스 피드백", "bool"),
        ], cfg)
        self._add_group("VR 오버레이 / 손목 UI", [
            ("overlay.enabled", "자막 오버레이", "bool"),
            ("overlay.width_m", "자막 너비(m)", "float"),
            ("overlay.distance_m", "거리(m)", "float"),
            ("overlay.below_m", "아래 오프셋(m)", "float"),
            ("overlay.tilt_deg", "기울기", "float"),
            ("overlay.font_size", "글자 크기", "int"),
            ("overlay.display_sec", "표시 시간(초)", "float"),
            ("overlay.lines", "표시 줄수", "int"),
            ("overlay.show_source", "자막 원문 표시", "bool"),
            ("wrist_ui.enabled", "손목 UI", "bool"),
            ("wrist_ui.hand", "착용 손(left/right)", "hand"),
            ("wrist_ui.width_m", "손목 UI 너비(m)", "float"),
            ("wrist_ui.offset", "손목 UI 오프셋 x,y,z", "float_csv"),
            ("wrist_ui.tilt_deg", "손목 UI 기울기", "float"),
            ("wrist_ui.roll_deg", "손목 UI 롤(blank=auto)", "nullable_float"),
            ("wrist_ui.pointer_tilt_deg", "포인터 기울기", "float"),
        ], cfg)
        self._settings_layout.addStretch(1)

    def _add_group(self, title: str, fields: list[tuple[str, str, str]], cfg: dict) -> None:
        group = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(group)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for path, label, kind in fields:
            widget = self._make_field(path, kind, _get_path(cfg, path))
            self._fields[path] = (widget, kind)
            form.addRow(label, widget)
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
        if isinstance(widget, QtWidgets.QComboBox):
            return widget.currentText().strip()
        return widget.text()

    def _settings_from_fields(self) -> dict:
        cfg = copy.deepcopy(self._controller.raw_cfg)
        for path, (widget, kind) in self._fields.items():
            _set_path(cfg, path, self._field_value(widget, kind))
        return cfg

    # ---------------- actions ----------------
    def _save_settings(self) -> None:
        try:
            cfg = self._settings_from_fields()
            key_error = config_mod.api_key_validation_error(cfg.get("api_key", ""))
            if key_error:
                raise ValueError("API 키에는 URL이 아니라 Gemini API 키를 입력해야 합니다.")
            cfg = config_mod.apply_app_profile(cfg)
            config_mod.save(cfg)
        except Exception as e:
            self._settings_note.setText(f"저장 실패: {e}")
            return
        self._settings_note.setText("저장됨. 런타임 재시작 중...")
        self._btn_save.setEnabled(False)

        def run():
            ok = self._controller.restart(cfg)
            self._signals.save_done.emit(ok)

        self._save_thread = threading.Thread(target=run, daemon=True, name="vrclt-restart")
        self._save_thread.start()

    def _save_done(self, ok: bool) -> None:
        self._btn_save.setEnabled(True)
        self._settings_note.setText("적용됨" if ok else "저장됨. 런타임 시작 실패")
        self._populate_settings()

    def _restart_runtime(self) -> None:
        self._settings_note.setText("런타임 재시작 중...")
        threading.Thread(target=self._controller.restart, daemon=True,
                         name="vrclt-restart").start()

    def _reload_devices(self) -> None:
        self._inputs, self._outputs = _device_names()
        self._populate_settings()
        self._settings_note.setText("장치 목록을 새로고침했습니다.")

    def _apply_app_mode(self, mode: str) -> None:
        mode = (mode or "").strip()
        current = self._controller.cfg.get("app", {}).get("mode", "vrchat")
        if not mode or mode == current or self._app_mode_applying:
            self._set_app_mode_checked(current)
            return
        try:
            cfg = copy.deepcopy(self._controller.raw_cfg)
            cfg.setdefault("app", {})["mode"] = mode
            cfg = config_mod.apply_app_profile(cfg)
            config_mod.save(cfg)
        except Exception as e:
            self._dashboard_note.setText(f"모드 적용 실패: {e}")
            self._set_app_mode_checked(current)
            return

        self._dashboard_note.setText("앱 모드 적용 중...")
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
        self._dashboard_note.setText("앱 모드 적용됨" if ok else "저장됨. 런타임 시작 실패")
        self._populate_settings()

    def _set_dashboard_apply_enabled(self, enabled: bool) -> None:
        for btn in self._app_mode_buttons.values():
            btn.setEnabled(enabled)
        self._text_only.setEnabled(enabled)

    def _set_app_mode_checked(self, mode: str) -> None:
        for key, btn in self._app_mode_buttons.items():
            btn.setChecked(key == mode)

    def _apply_text_only(self, enabled: bool) -> None:
        if self._app_mode_applying:
            self._sync_text_only()
            return
        try:
            cfg = copy.deepcopy(self._controller.raw_cfg)
            if enabled:
                cfg.setdefault("app", {})["mode"] = "vrchat"
            cfg.setdefault("outbound", {})["text_only"] = bool(enabled)
            cfg = config_mod.apply_app_profile(cfg)
            config_mod.save(cfg)
        except Exception as e:
            self._dashboard_note.setText(f"텍스트 온리 적용 실패: {e}")
            self._sync_text_only()
            return

        self._dashboard_note.setText("텍스트 온리 적용 중...")
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

    @staticmethod
    def _code_for_label(label: str, codes: list[str]) -> str:
        for code in codes:
            if LANG_LABELS.get(code, code) == label:
                return code
        return label

    # ---------------- refresh ----------------
    def _refresh(self) -> None:
        st = self._controller.state
        connected = self._controller.connected()
        status = self._controller.status
        color = "#2ea043" if connected else ("#d29922" if status == "Running" else "#8b949e")
        self._status_dot.setStyleSheet(f"background:{color}; border-radius:7px;")
        self._status_text.setText(f"{status} | {'Connected' if connected else 'Idle'}")
        self._error_text.setText(self._controller.last_error)

        self._btn_trans.setText(i18n.tr(st.ui_lang, "btn_trans_on" if st.translation_on else "btn_trans_off"))
        self._btn_trans.setStyleSheet(
            "background:#2ea043;" if st.translation_on else "background:#78541e;")
        self._btn_sub.setText(i18n.tr(st.ui_lang, "btn_sub_on" if st.subtitles_on else "btn_sub_off"))
        self._btn_sub.setStyleSheet("background:#2870aa;" if st.subtitles_on else "")
        self._btn_overlay_move.setText("자막 이동 완료" if st.edit_mode else "자막 위치 이동")
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
            LANG_LABELS.get(c, c) for c in self._controller.cfg.get("control", {}).get("languages", ["en"])
        ], LANG_LABELS.get(st.target_language, st.target_language))
        self._sync_combo(self._sub_lang, [
            LANG_LABELS.get(c, c) for c in self._controller.cfg.get("inbound", {}).get("languages", ["ko"])
        ], LANG_LABELS.get(st.inbound_language, st.inbound_language))
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
            self._log_text.setPlainText("Log file has not been created yet.")
        except Exception as e:
            self._log_text.setPlainText(f"Failed to read log: {e}")

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
        else:
            event.ignore()
            self.hide()
            self._tray.showMessage("vrclt", "트레이에서 계속 실행 중입니다.",
                                   QtWidgets.QSystemTrayIcon.MessageIcon.Information, 1500)

    def _quit(self) -> None:
        self._quitting = True
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
    win = MainWindow(controller, log_file)
    win.show()
    threading.Thread(target=controller.start, daemon=True, name="vrclt-start").start()
    app.aboutToQuit.connect(controller.stop)
    return app.exec()
