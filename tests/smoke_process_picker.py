"""Offscreen test: audio-session process picker + the custom app profile."""
import copy
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6 import QtWidgets

from vrclt import config as config_mod
from vrclt import i18n
from vrclt.audio import sessions as audio_sessions
from vrclt.ui.widgets import AudioProcessCombo

sys.path.insert(0, os.path.dirname(__file__))
from smoke_qt import StubController

PROCESS_PATHS = ("inbound.process", "app.profiles.discord.process",
                 "app.profiles.custom.process")


def check_enumeration():
    """The real Core Audio enumeration: shape only - what is playing on the
    test machine (possibly nothing) must not decide pass/fail."""
    found = audio_sessions.audio_processes()
    assert isinstance(found, list)
    for entry in found:
        name, playing = entry
        assert isinstance(name, str) and name, entry
        assert isinstance(playing, bool), entry
    # playing processes sort first
    flags = [playing for _n, playing in found]
    assert flags == sorted(flags, reverse=True), found
    print(f"  audio sessions: {len(found)} process(es), "
          f"{sum(flags)} playing")


def check_custom_profile():
    assert "custom" in config_mod.APP_MODES
    cfg = copy.deepcopy(config_mod.DEFAULTS)

    # an empty custom target keeps whatever is being captured
    cfg["inbound"]["process"] = "VRChat.exe"
    out = config_mod.apply_app_profile(cfg, "custom", force=True)
    assert out["app"]["mode"] == "custom"
    assert out["inbound"]["process"] == "VRChat.exe", out["inbound"]["process"]
    assert out["outbound"]["chatbox"] is False
    assert out["overlay"]["enabled"] is True

    # a chosen target wins, and switching away and back restores it
    cfg["app"]["profiles"]["custom"]["process"] = "obs64.exe"
    out = config_mod.apply_app_profile(cfg, "custom", force=True)
    assert out["inbound"]["process"] == "obs64.exe", out["inbound"]["process"]
    out = config_mod.apply_app_profile(out, "vrchat", force=True)
    assert out["inbound"]["process"] == "VRChat.exe"
    out = config_mod.apply_app_profile(out, "custom", force=True)
    assert out["inbound"]["process"] == "obs64.exe"

    # a config reset keeps the custom target (it is user identity, not tuning)
    reset = config_mod.reset_preserving_language_lists(out)
    assert reset["app"]["profiles"]["custom"]["process"] == "obs64.exe"

    # the custom profile must not make the "profile looks stale" heuristic
    # fire on a freshly applied config
    for mode in config_mod.APP_MODES:
        applied = config_mod.apply_app_profile(
            copy.deepcopy(config_mod.DEFAULTS), mode, force=True)
        assert not config_mod.profile_runtime_looks_stale(applied), mode


def check_picker(win, form):
    for path in PROCESS_PATHS:
        widget, spec = form._fields[path]
        assert isinstance(widget, AudioProcessCombo), (path, type(widget))

    widget, spec = form._fields["inbound.process"]
    assert widget.currentText() == "VRChat.exe"

    # the dropdown re-lists processes but never loses the current value, even
    # when the target is not running (the usual case for a game)
    widget.showPopup()
    widget.hidePopup()
    assert widget.currentText() == "VRChat.exe", widget.currentText()
    assert widget.findText("VRChat.exe") >= 0
    assert form.config_from_fields()["inbound"]["process"] == "VRChat.exe"

    # a stub list drives the ordering/marking without depending on live audio
    widget._list_processes = lambda: [("Playing.exe", True), ("Quiet.exe", False)]
    widget.showPopup()
    widget.hidePopup()
    texts = [widget.itemText(i) for i in range(widget.count())]
    assert "Playing.exe" in texts and "Quiet.exe" in texts, texts
    assert texts.index("Playing.exe") < texts.index("Quiet.exe"), texts
    assert not widget.itemIcon(texts.index("Playing.exe")).isNull()
    assert widget.itemIcon(texts.index("Quiet.exe")).isNull()
    assert widget.currentText() == "VRChat.exe"   # still not clobbered

    # picking one reads back as a bare exe name (no decoration to strip)
    widget.setCurrentText("Playing.exe")
    assert form.config_from_fields()["inbound"]["process"] == "Playing.exe"


def check_mode_buttons(win, ctl):
    buttons = win._app_mode_buttons
    for mode in config_mod.APP_MODES:
        assert mode in buttons, mode
        assert buttons[mode].text(), mode
    lang = ctl.state.ui_lang
    assert buttons["custom"].text() == i18n.tr(lang, "app_mode_custom")
    ctl.state.ui_lang = "ko" if lang != "ko" else "en"
    win._apply_i18n()
    assert buttons["custom"].text() == i18n.tr(ctl.state.ui_lang, "app_mode_custom")
    assert buttons["vrchat"].text() == "VRChat"   # product name stays put
    ctl.state.ui_lang = lang
    win._apply_i18n()


def check_mode_note(win, ctl):
    """Custom mode with no target picked must say what it is still capturing."""
    ctl.cfg["app"]["mode"] = "vrchat"
    assert win._mode_applied_note() == win._tr("msg_mode_applied")
    ctl.cfg["app"]["mode"] = "custom"
    ctl.cfg["app"]["profiles"]["custom"]["process"] = ""
    ctl.cfg["inbound"]["process"] = "VRChat.exe"
    note = win._mode_applied_note()
    assert "VRChat.exe" in note and "{process}" not in note, note
    ctl.cfg["app"]["profiles"]["custom"]["process"] = "obs64.exe"
    assert win._mode_applied_note() == win._tr("msg_mode_applied")
    ctl.cfg["app"]["mode"] = "vrchat"
    ctl.cfg["app"]["profiles"]["custom"]["process"] = ""


def main():
    check_enumeration()
    check_custom_profile()
    app = QtWidgets.QApplication([])
    from vrclt.qt_ui import MainWindow
    ctl = StubController()
    win = MainWindow(ctl, config_mod.APPDATA_DIR / "logs" / "vrclt.log")
    check_picker(win, win._settings_form)
    check_mode_buttons(win, ctl)
    check_mode_note(win, ctl)
    win._quitting = True
    win.close()
    print("smoke_process_picker: OK")


main()
