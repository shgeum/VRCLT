"""VR page actions, asynchronous settings and controller wiring without a headset."""
import copy
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vrclt import config, i18n
from vrclt.app_controller import AppController, make_dashboard_panel, make_wrist_panel
from vrclt.state import AppState
from vrclt.vr import dashboard_panel, wrist_ui


def check_navigation():
    state = AppState()
    current = dict(provider="soniox", keep=True, mic="", out="")
    context_calls, devices, restarts, text_only = [], [], [], []
    panel = dashboard_panel.DashboardPanel(
        state, ["en", "ko", "yue"], inbound_languages=["ko", "en", "yue"],
        get_provider=lambda: current["provider"],
        get_speaker_context=lambda: (current["keep"], 60.0 if current["keep"] else 15.0),
        set_speaker_context=lambda enabled, done: context_calls.append((enabled, done)),
        get_devices=lambda: (["", "mic A", "mic B"], ["", "out A"]),
        get_mic_device=lambda: current["mic"], get_tts_device=lambda: current["out"],
        set_audio_devices=lambda mic, out, done: devices.append((mic, out, done)),
        on_restart=lambda: restarts.append(True), on_text_only_toggle=text_only.append)
    try:
        # Main is limited to live controls; settings cannot be invoked while hidden.
        panel._on_click("restart")
        panel._on_click("text_only")
        assert not restarts and not text_only
        for expected in ("en", "ko", ""):
            panel._on_click("src_next")
            assert state.source_language == expected  # Soniox skips unsupported yue, includes Auto
        current["provider"] = "gemini"
        panel._on_click("src_next")
        panel._on_click("speaker_context")
        assert state.source_language == "" and not context_calls
        current["provider"] = "qwen"
        panel._on_click("src_next")
        assert state.source_language == "ko"  # Qwen's blank value displays its default English
        current["provider"] = "soniox"
        panel._on_click("lang")
        assert panel._page == "lang_out"
        panel._on_click("pick_out:ko")
        assert state.target_language == "ko" and panel._page == "main"
        panel._on_click("sub_lang")
        panel._on_click("picker_close")
        assert panel._page == "main"

        panel._on_click("speaker_context")
        assert context_calls[0][0] is False and panel._context_applying
        panel._on_click("speaker_context")
        panel._on_click("nav_audio")
        panel._on_click("mic_next")
        panel._on_click("text_only")
        assert len(context_calls) == 1 and panel._pending_mic is None and not text_only
        context_calls.pop()[1](False)
        assert not panel._context_applying and current["keep"]
        panel._on_click("nav_main")
        panel._on_click("speaker_context")
        value, done = context_calls.pop()
        current["keep"] = value
        done(True)
        assert not panel._context_applying

        # Rapid device choices are batched once; unrelated restarts wait for them.
        panel._on_click("nav_audio")
        panel._on_click("mic_next")
        panel._on_click("mic_next")
        assert panel._pending_mic == "mic B" and not devices
        panel._on_click("text_only")
        panel._on_click("nav_layout")
        panel._on_click("restart")
        assert not restarts and not text_only
        panel._maybe_apply_devices(time.time() + 2)
        assert panel._devices_applying and len(devices) == 1
        mic, out, done = devices.pop()
        assert mic == "mic B" and out is None
        current["mic"] = mic
        done(True)
        panel._maybe_apply_devices(time.time() + 3)
        assert not devices and panel._pending_mic is None
        panel._on_click("restart")
        assert restarts == [True]

        # Missing localization keys must never leak into rendered VR controls.
        def strict_tr(lang, key):
            assert i18n.has(key), key
            return i18n.tr(lang, key)
        with patch.object(dashboard_panel, "tr", strict_tr), patch.object(wrist_ui, "tr", strict_tr):
            wrist = wrist_ui.WristPanel(state, ["en", "ko"], get_provider=lambda: current["provider"])
            try:
                for provider in ("gemini", "qwen", "openai", "soniox"):
                    current["provider"] = provider
                    for lang in i18n.LANGS:
                        state.ui_lang = lang
                        for page in ("main", "audio", "layout", "lang_out", "lang_in"):
                            panel._page = page
                            panel._render((False, "status_failed", ""))
                        for page in ("main", "settings", "lang_out", "lang_in"):
                            wrist._page = page
                            wrist._render((True, "status_running", ""), False)
            finally:
                wrist.detach()
    finally:
        panel.detach()


def check_controller_bridge():
    ctl = object.__new__(AppController)
    ctl._lock = threading.RLock()
    ctl._lifecycle_lock = threading.RLock()
    ctl._closed = ctl._restarting = False
    ctl.raw_cfg = copy.deepcopy(config.DEFAULTS)
    ctl.raw_cfg["provider"] = "soniox"
    ctl.raw_cfg["soniox"]["speaker_context_idle_sec"] = 120.0
    ctl.raw_cfg["soniox"]["voice"] = "keep-this-voice"
    ctl.cfg = config.apply_app_profile(ctl.raw_cfg)
    notifications, done = [], []
    ctl._notify = lambda: notifications.append(True)
    ctl._spawn = lambda name, fn: fn()

    def restart(cfg):
        ctl.raw_cfg = copy.deepcopy(cfg)
        ctl.cfg = config.apply_app_profile(cfg)
        return True

    ctl._restart_locked = restart
    with patch.object(config, "save") as save:
        ctl.set_speaker_context(False, done.append)
        save.assert_called_once()
        saved = save.call_args.args[0]
        assert saved["soniox"]["keep_speaker_context"] is False
        assert saved["soniox"]["speaker_context_idle_sec"] == 120
        assert saved["soniox"]["voice"] == "keep-this-voice"
    assert done == [True] and notifications and ctl.get_speaker_context() == (False, 15.0)

    # Factories pass the actual controller callbacks through to both VR surfaces.
    state = AppState()
    wrist = make_wrist_panel(ctl.cfg, state, lambda: (False, "status_stopped", ""),
                            get_provider=ctl.get_provider,
                            get_speaker_context=ctl.get_speaker_context,
                            set_speaker_context=ctl.set_speaker_context)
    dash = make_dashboard_panel(
        ctl.cfg, state, lambda: (False, "status_stopped", ""), lambda x: None,
        lambda x: None, lambda: 27, lambda: None, lambda x: None, lambda: None,
        lambda: ([""], [""]), lambda: "", lambda: "", lambda m,t,d: d(True),
        lambda x: None, lambda: 1.0, ctl.get_provider,
        ctl.get_speaker_context, ctl.set_speaker_context)
    try:
        assert wrist._get_provider() == dash._get_provider() == "soniox"
        assert wrist._get_speaker_context() == dash._get_speaker_context() == (False, 15.0)
        with patch.object(config, "save"):
            wrist._on_click("nav_settings")
            wrist._on_click("speaker_context")
        assert ctl.get_speaker_context() == (True, 120.0)
        assert dash._get_speaker_context() == (True, 120.0)
    finally:
        wrist.detach()
        dash.detach()


if __name__ == "__main__":
    check_navigation()
    check_controller_bridge()
    print("smoke_vr_navigation: OK")
