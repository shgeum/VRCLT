"""Offscreen smoke test: build MainWindow with a stub controller, run the
refresh loop, cycle UI languages, exercise the subtitle view."""
import copy
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6 import QtWidgets

from vrclt import config as config_mod
from vrclt.state import AppState


class StubController:
    def __init__(self):
        self.cfg = copy.deepcopy(config_mod.DEFAULTS)
        self.raw_cfg = self.cfg  # plain dict attribute, like AppController
        self.state = AppState()
        self.config_revision = 0
        self._subs = []

    def subscribe(self, fn):
        self._subs.append(fn)

    def subscribe_errors(self, fn):
        pass

    def get_status_info(self):
        return (False, "status_stopped", "")

    def get_provider(self):
        return "gemini"

    def subtitles_snapshot(self):
        return getattr(self, "_snap", ([], ("", "")))

    def tts_gain(self):
        return 1.0

    def mic_level(self):
        return None

    def close_action(self):
        return "exit"

    def last_config_version(self):
        from vrclt import __version__
        return __version__

    def mark_config_version_seen(self):
        pass

    def get_steamvr_auto_launch(self):
        return None

    def set_steamvr_auto_launch(self, enabled):
        pass

    def set_ui_lang(self, lang, persist=True):
        self.state.ui_lang = lang

    def set_hold_mute(self, held):
        pass

    def shutdown(self):
        pass


def main():
    app = QtWidgets.QApplication([])
    from vrclt.qt_ui import MainWindow
    ctl = StubController()
    win = MainWindow(ctl, config_mod.APPDATA_DIR / "logs" / "vrclt.log")

    win._refresh()
    # subtitle view: finals + partial render, then clear back to placeholder
    ctl._snap = ([("hello", "안녕", "ko"), ("bye", "", "ko")], ("part src", "부분"))
    win._refresh()
    txt = win._subtitle_view.toPlainText()
    assert "안녕" in txt and "bye" in txt and "부분" in txt, txt
    html = win._subtitle_view.toHtml()
    assert "italic" in html, "partial line not styled"
    ctl._snap = ([], ("", ""))
    win._refresh()
    assert win._subtitle_view.toPlainText() == ""

    # cycle all UI languages (font + retranslate + settings rebuild)
    from vrclt import i18n
    for lang in ("ko", "ja", "zh", "en"):
        ctl.state.ui_lang = lang
        win._refresh()
        assert win._btn_save.text() == i18n.tr(lang, "btn_save_restart"), lang
        assert win._btn_restart.text() == i18n.tr(lang, "btn_restart_runtime"), lang
        assert win._tabs.tabText(win._tab_logs_idx) == i18n.tr(lang, "tab_logs"), lang

    # toggle states through the property path
    ctl.state.translation_on = False
    ctl.state.subtitles_on = True
    win._refresh()
    assert win._btn_trans.property("on") == "false"
    assert win._btn_sub.property("on") == "true"

    win._quitting = True
    win.close()
    print("smoke_qt: OK")


if __name__ == "__main__":
    main()
