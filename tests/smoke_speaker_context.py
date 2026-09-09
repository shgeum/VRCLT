"""Soniox dashboard context retention: defaults, persistence and settings sync."""
import copy
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6 import QtWidgets
from smoke_qt import StubController
from vrclt import config, i18n
from vrclt.qt_ui import MainWindow
from vrclt.ui.update_banner import UpdateBanner


def main():
    app = QtWidgets.QApplication([])
    ctl = StubController()
    ctl.cfg["provider"] = "soniox"
    ctl.cfg["hotkeys"]["enabled"] = False
    assert ctl.cfg["soniox"]["keep_speaker_context"] is True
    ctl.get_provider = lambda: ctl.cfg["provider"]

    def restart(cfg):
        ctl.raw_cfg = copy.deepcopy(cfg)
        ctl.cfg = config.apply_app_profile(cfg)
        return True

    ctl.restart = restart
    with patch.object(UpdateBanner, "start_check", return_value=False):
        win = MainWindow(ctl, Path(__file__).parent / "nonexistent.log")
    win._timer.stop()
    win._desktop_overlay._timer.stop()
    win.show()
    app.processEvents()
    checkbox = win._keep_speaker_context
    assert not checkbox.isHidden() and checkbox.isChecked()
    assert win._settings_form._fields["soniox.keep_speaker_context"][0].isChecked()
    assert win._settings_form._fields["soniox.speaker_context_idle_sec"][0].value() == 60
    assert not win._speaker_badge.isHidden(), "diarization must remain enabled"

    for lang in ("ko", "en", "ja", "zh"):
        ctl.state.ui_lang = lang
        win._refresh()
        assert checkbox.text() == i18n.tr(lang, "f.soniox.keep_speaker_context")
        assert checkbox.toolTip() == i18n.tr(lang, "f.soniox.keep_speaker_context.tip")
        assert win._soniox_idle_hint.text() == i18n.tr(
            lang, "soniox_idle_timeout_status").format(seconds="60")
        assert win._soniox_idle_hint.toolTip() == i18n.tr(
            lang, "f.soniox.speaker_context_idle_sec.tip")
        win.resize(780, 620)
        app.processEvents()
        assert win._dashboard_scroll.horizontalScrollBar().maximum() == 0, lang

    for provider in ("gemini", "qwen", "openai", "soniox"):
        ctl.cfg["provider"] = provider
        win._refresh()
        assert checkbox.isHidden() == (provider != "soniox")
        assert win._soniox_idle_hint.isHidden() == (provider != "soniox")

    # Explicit saved choices are preserved when defaults change.
    timeout_draft = win._settings_form._fields["soniox.speaker_context_idle_sec"][0]
    timeout_draft.setValue(120)
    voice_draft = win._settings_form._fields["soniox.voice"][0]
    voice_draft.setText("keep-this-draft")
    # Simulate a VR toggle: no form rebuild/config-revision reset occurs.
    ctl.cfg["soniox"]["keep_speaker_context"] = False
    win._refresh()
    assert not win._settings_form._fields["soniox.keep_speaker_context"][0].isChecked()
    assert timeout_draft.value() == 120 and voice_draft.text() == "keep-this-draft"
    win._populate_settings()
    win._refresh()
    assert not checkbox.isChecked()
    assert win._soniox_idle_hint.text() == win._tr(
        "soniox_idle_timeout_status").format(seconds="15")
    assert win._soniox_idle_hint.toolTip() == win._tr("f.audio.mic_idle_disconnect_sec.tip")

    # The output test must finish before a context-triggered audio restart.
    win._test_thread = Mock()
    win._test_thread.is_alive.return_value = True
    with patch.object(config, "save") as save:
        win._refresh()
        assert not checkbox.isEnabled()
        win._apply_speaker_context(True)
        save.assert_not_called()
    win._test_thread = None
    win._refresh()
    assert checkbox.isEnabled()

    # Only the context flag is persisted; unrelated unsaved form edits survive.
    other_field = win._settings_form._fields["soniox.voice"][0]
    other_field.setText("unsaved-voice")
    original = copy.deepcopy(ctl.raw_cfg)
    with (patch.object(config, "save") as save,
          patch.object(win, "_spawn_restart", return_value=None) as spawn):
        checkbox.click()
        expected = copy.deepcopy(original)
        expected["soniox"]["keep_speaker_context"] = True
        save.assert_called_once_with(expected)
        assert win._speaker_context_applying and not checkbox.isEnabled()
        assert not win._btn_save.isEnabled()
        win._refresh()
        assert checkbox.isChecked(), "pending value reverted during refresh"
        assert not win._text_only.isEnabled()
        op, done = spawn.call_args.args[1:]
        done.emit(op())
        app.processEvents()
        assert not win._speaker_context_applying and checkbox.isEnabled()
        assert checkbox.isChecked()
        assert win._settings_form._fields["soniox.keep_speaker_context"][0].isChecked()
        assert other_field.text() == "unsaved-voice"
        win._apply_speaker_context(True)
        save.assert_called_once()

    # A write error restores the saved value and allows retry.
    with (patch.object(config, "save", side_effect=OSError("test write failure")),
          patch.object(win, "_spawn_restart") as spawn):
        checkbox.click()
        spawn.assert_not_called()
        assert checkbox.isChecked() and checkbox.isEnabled()
        assert "test write failure" in win._dashboard_note.text()

    # Changes saved from Settings are reflected on the dashboard.
    win._settings_form._fields["soniox.keep_speaker_context"][0].setChecked(False)
    win._settings_form._fields["soniox.speaker_context_idle_sec"][0].setValue(120)
    with (patch.object(config, "save") as save,
          patch.object(win, "_spawn_restart", return_value=None) as spawn):
        win._save_settings()
        assert save.call_args.args[0]["soniox"]["keep_speaker_context"] is False
        op, done = spawn.call_args.args[1:]
        done.emit(op())
        win._refresh()
        assert not checkbox.isChecked()
        assert not win._speaker_badge.isHidden()

    # A failed runtime start still reflects the newly saved config, and unlocks.
    with (patch.object(config, "save"),
          patch.object(win, "_spawn_restart", return_value=None) as spawn):
        checkbox.click()
        op, done = spawn.call_args.args[1:]
        op()
        done.emit(False)
        assert checkbox.isChecked() and checkbox.isEnabled()
        assert win._soniox_idle_hint.text() == win._tr(
            "soniox_idle_timeout_status").format(seconds="120")
        assert win._btn_save.isEnabled()
        assert win._dashboard_note.text() == win._tr("msg_saved_start_failed")

    # Older config without this setting uses the bounded keep-context default.
    del ctl.cfg["soniox"]["keep_speaker_context"]
    win._refresh()
    assert checkbox.isChecked()
    win._quitting = True
    win.close()
    print("smoke_speaker_context: OK")


if __name__ == "__main__":
    main()
