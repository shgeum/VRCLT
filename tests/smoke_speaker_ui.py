"""Speaker provenance survives every Qt surface; transcript markup stays text."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6 import QtWidgets
from smoke_qt import StubController
from vrclt import i18n
from vrclt import config as config_mod
from vrclt.qt_ui import MainWindow
from vrclt.subtitles import SubtitleLine
from vrclt.ui import theme
from vrclt.ui.subtitle_text import subtitle_html
from vrclt.ui.update_banner import UpdateBanner


def main():
    app = QtWidgets.QApplication([])
    ctl = StubController()
    ctl.state.ui_lang = "ko"
    ctl.cfg["provider"] = "soniox"
    ctl.cfg["soniox"]["api_key"] = "test-placeholder"
    finals = [SubtitleLine("Alice <img src=x>", "안녕하세요 <b>문자</b>", "ko", "1"),
              SubtitleLine("Bob", "반가워요", "ko", "2")]
    partial = SubtitleLine("Alice again", "다시", "ko", "1")
    ctl.subtitles_snapshot_with_speakers = lambda: (finals, partial)
    with patch.object(UpdateBanner, "start_check", return_value=False):
        win = MainWindow(ctl, Path(__file__).parent / "nonexistent.log")
    win._timer.stop()
    win._desktop_overlay._timer.stop()
    win.show()
    app.processEvents()
    win._refresh()
    text = win._subtitle_view.toPlainText()
    assert "화자 1" in text and "화자 2" in text, text
    assert "<b>문자</b>" in text, "transcript interpreted as HTML"
    assert not win._speaker_badge.isHidden()
    html = win._desktop_overlay._subtitle_text()
    assert "화자 1" in html and "화자 2" in html
    assert "&lt;b&gt;" in html and "<img" not in html
    for speaker in ("1", "2"):
        assert theme.hex_rgb(theme.speaker_color(speaker)) in html
    assert theme.speaker_color("1") != theme.speaker_color("2")
    assert theme.speaker_color("custom-id") == theme.speaker_color("custom-id")
    plain = subtitle_html([SubtitleLine("hello", "안녕", "ko")], SubtitleLine(),
                          lambda key: i18n.tr("ko", key))
    assert "화자" not in plain

    # No horizontal clipping at the compact window size, including source hints.
    for width, height in ((780, 620), (1040, 820)):
        win.resize(width, height)
        app.processEvents()
        assert win._dashboard_scroll.horizontalScrollBar().maximum() == 0

    # Repeated notifications coalesce, rather than enqueueing full refreshes.
    win._refresh_pending.stop()
    for _ in range(100):
        win._queue_refresh()
    assert win._refresh_pending.isActive()
    assert win._refresh_pending.remainingTime() <= 40

    # Inactive provider credentials stay saved, but cannot block the selected
    # engine while their rows are hidden. An invalid active key is revealed.
    win._settings_form._fields["qwen.api_key"][0].setText("https://unused.example")
    with (patch.object(config_mod, "save") as save,
          patch.object(win, "_spawn_restart", return_value=None)):
        win._save_settings()
        save.assert_called_once()
        assert save.call_args.args[0]["qwen"]["api_key"] == "https://unused.example"
    win._settings_form._fields["soniox.api_key"][0].setText("https://not-a-key.example")
    with patch.object(config_mod, "save") as save:
        win._save_settings()
        save.assert_not_called()
    assert not win._settings_form._fields["soniox.api_key"][0].isHidden()

    win.hide()
    assert win._timer.interval() == 1000
    assert not win._meter_timer.isActive()
    ctl.cfg["provider"] = "gemini"
    win._refresh()
    assert win._speaker_badge.isHidden()
    win._quitting = True
    win.close()
    print("smoke_speaker_ui: OK")


if __name__ == "__main__":
    main()
