"""Offscreen LogPanel test: incremental tail, rotation, level filter, search."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6 import QtWidgets

from vrclt import i18n
from vrclt.ui.log_view import LogPanel


def main():
    app = QtWidgets.QApplication([])
    tr = lambda key: i18n.tr("en", key)
    tmp = Path(tempfile.mkdtemp()) / "vrclt.log"

    # missing file -> placeholder message
    p = LogPanel(tmp, tr)
    assert "log file" in p._text.toPlainText().lower()

    tmp.write_text("2026-01-01 [INFO] a: hello\n2026-01-01 [ERROR] b: boom\n",
                   encoding="utf-8")
    p.reload()
    assert "hello" in p._text.toPlainText() and "boom" in p._text.toPlainText()

    # incremental append with a traceback continuation inheriting ERROR
    with tmp.open("a", encoding="utf-8") as f:
        f.write("2026-01-01 [ERROR] c: fail\nTraceback (most recent)\n")
    p._poll()
    assert "Traceback" in p._text.toPlainText()

    # level filter: ERROR only
    p._level.setCurrentIndex(3)
    txt = p._text.toPlainText()
    assert "hello" not in txt and "boom" in txt and "Traceback" in txt, txt

    # search
    p._level.setCurrentIndex(0)
    p._search.setText("boom")
    p._render()
    assert p._text.toPlainText().strip() == "2026-01-01 [ERROR] b: boom"
    p._search.setText("")
    p._render()

    # partial line handling: bytes without trailing newline stay in carry
    with tmp.open("a", encoding="utf-8") as f:
        f.write("2026-01-01 [INFO] d: partial")
    p._poll()
    assert "partial" not in p._text.toPlainText()
    with tmp.open("a", encoding="utf-8") as f:
        f.write(" done\n")
    p._poll()
    assert "partial done" in p._text.toPlainText()

    # rotation: file truncated/replaced -> reload from scratch
    tmp.write_text("2026-01-02 [INFO] e: rotated\n", encoding="utf-8")
    p._poll()
    assert "rotated" in p._text.toPlainText()
    assert "hello" not in p._text.toPlainText()

    print("smoke_logpanel: OK")


if __name__ == "__main__":
    main()
