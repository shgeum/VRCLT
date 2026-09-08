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
from vrclt.ui.log_view import INITIAL_TAIL_BYTES, MAX_LINE_BYTES, MAX_LINES, LogPanel


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

    # File identity catches rotation even when the replacement is larger.
    replacement = tmp.with_suffix(".replacement")
    replacement.write_text("[INFO] replacement file with a longer line than before\n",
                           encoding="utf-8")
    replacement.replace(tmp)
    p._poll()
    assert p._text.toPlainText() == "[INFO] replacement file with a longer line than before"

    # A burst updates the Qt document once, preserving all lines in order.
    changes = []
    p._text.textChanged.connect(lambda: changes.append(True))
    with tmp.open("a", encoding="utf-8") as f:
        f.writelines(f"[INFO] batch {i}\n" for i in range(300))
    p._poll()
    assert len(changes) == 1, f"one burst caused {len(changes)} Qt document updates"
    assert p._text.toPlainText().endswith("[INFO] batch 299")

    # Returning after a long hidden interval reads only the bounded tail.
    sizes = []
    ingest = p._ingest

    def tracked_ingest(data):
        sizes.append(len(data))
        return ingest(data)

    p._ingest = tracked_ingest
    with tmp.open("a", encoding="utf-8") as f:
        f.writelines(f"[INFO] backlog {i} {'x' * 100}\n" for i in range(6000))
    p._poll()
    p._ingest = ingest
    assert sizes and max(sizes) <= INITIAL_TAIL_BYTES, sizes
    assert p._offset == tmp.stat().st_size
    assert len(p._lines) <= MAX_LINES
    assert "backlog 5999" in p._text.toPlainText()
    assert "batch 299" not in p._text.toPlainText()

    # Filtering uses the same history window as the unfiltered ring buffer.
    tmp.write_text("[ERROR] old error\n", encoding="utf-8")
    p.reload()
    p._level.setCurrentIndex(3)
    with tmp.open("a", encoding="utf-8") as f:
        f.writelines("[INFO] newer\n" for _ in range(MAX_LINES))
    p._poll()
    assert not p._text.toPlainText(), "evicted error remained visible under the filter"
    p._level.setCurrentIndex(0)

    # Unterminated lines cannot grow the carry buffer forever. Preserve their
    # prefix/level and mark truncation when the newline finally arrives.
    p._carry = b""
    p._ingest(b"[ERROR] large " + b"x" * MAX_LINE_BYTES)
    for _ in range(4):
        assert not p._ingest(b"y" * MAX_LINE_BYTES)
        assert len(p._carry) <= MAX_LINE_BYTES
    added = p._ingest(b"\ncontinuation\n")
    assert added[0][0] == added[1][0] == 40
    assert added[0][1].startswith("[ERROR] large ") and added[0][1].endswith(" …")
    assert added[1][1] == "continuation"
    assert not p._carry and not p._carry_truncated

    # A UTF-8 character split across polls is still decoded only when complete.
    encoded = "[INFO] 안녕하세요\n".encode("utf-8")
    p._ingest(encoded[:-2])
    assert p._ingest(encoded[-2:]) == [(20, "[INFO] 안녕하세요")]

    # A newly created log replaces the missing-file placeholder automatically.
    missing = tmp.with_name("new.log")
    fresh = LogPanel(missing, tr)
    missing.write_text("[INFO] appeared\n", encoding="utf-8")
    fresh._poll()
    assert fresh._text.toPlainText() == "[INFO] appeared"

    print("smoke_logpanel: OK")


if __name__ == "__main__":
    main()
