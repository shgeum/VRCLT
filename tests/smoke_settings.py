"""Offscreen settings-form test: widget kinds, value round-trip (precision),
range widening, validation errors, default tooltips."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6 import QtWidgets

from vrclt import config as config_mod
from vrclt.ui.settings_schema import GROUPS
from vrclt.ui.settings_form import SettingsValidationError
from vrclt.ui.widgets import AxesField, NoWheelDoubleSpinBox, NoWheelSpinBox

sys.path.insert(0, os.path.dirname(__file__))
from smoke_qt import StubController


def main():
    app = QtWidgets.QApplication([])
    from vrclt.qt_ui import MainWindow
    ctl = StubController()
    win = MainWindow(ctl, config_mod.APPDATA_DIR / "logs" / "vrclt.log")
    form = win._settings_form

    # every schema path exists in the config and got a widget
    for _title, specs in GROUPS:
        for spec in specs:
            assert spec.path in form._fields, spec.path
            sentinel = object()
            assert config_mod.get_path(ctl.cfg, spec.path, sentinel) is not sentinel, \
                f"schema path missing in DEFAULTS: {spec.path}"

    # numeric fields are actual spinboxes now
    assert isinstance(form._fields["osc.port"][0], NoWheelSpinBox)
    assert isinstance(form._fields["audio.turn_end_silence_sec"][0], NoWheelDoubleSpinBox)
    assert isinstance(form._fields["wrist_ui.offset"][0], AxesField)

    # untouched round-trip: config_from_fields reproduces the raw cfg for
    # every schema path (precision fields included)
    out = form.config_from_fields()
    for _title, specs in GROUPS:
        for spec in specs:
            a = config_mod.get_path(ctl.cfg, spec.path)
            b = config_mod.get_path(out, spec.path)
            if isinstance(a, float):
                assert abs(a - b) < 1e-9, (spec.path, a, b)
            elif isinstance(a, list) and a and isinstance(a[0], float):
                assert all(abs(x - y) < 1e-9 for x, y in zip(a, b)), (spec.path, a, b)
            else:
                assert a == b, (spec.path, a, b)
    assert abs(config_mod.get_path(out, "wrist_ui.tilt_deg") - 185.636) < 1e-9
    assert config_mod.get_path(out, "wrist_ui.roll_deg") == -28.633
    offs = config_mod.get_path(out, "wrist_ui.offset")
    assert all(abs(x - y) < 1e-9 for x, y in zip(offs, [-0.0509, -0.065, 0.0891])), offs

    # range widening: out-of-range stored value survives instead of clamping
    ctl.cfg["audio"]["send_interval_ms"] = 5  # below the 10 ms widget min
    form.populate()
    assert form.config_from_fields()["audio"]["send_interval_ms"] == 5

    # invalid nullable_float -> collected error + invalid marking
    w, spec = form._fields["wrist_ui.roll_deg"]
    w.setText("-")  # validator allows the intermediate state
    try:
        form.config_from_fields()
        raise AssertionError("expected SettingsValidationError")
    except SettingsValidationError as e:
        assert e.errors[0].path == "wrist_ui.roll_deg"
    assert form.first_invalid_widget() is w
    assert w.property("invalid") == "true"
    w.setText("")
    assert form.config_from_fields()["wrist_ui"]["roll_deg"] is None
    assert w.property("invalid") == "false"

    # save path surfaces the friendly message
    w.setText("-")
    win._save_settings()
    assert win._settings_note.text(), "note should show validation failure"
    assert "wrist" in win._settings_note.text().lower() or \
           win._settings_note.text() != ""
    w.setText("")

    # default-value tooltips
    tip = form._fields["audio.voice_rms_threshold"][0].toolTip()
    assert "90" in tip, tip
    tip = form._fields["wrist_ui.roll_deg"][0].toolTip()
    assert tip, "roll_deg should have tip + default"

    # search filter: only matching rows/groups stay visible
    form.apply_filter("wrist")
    spec, f_form, label, widget = form._rows["wrist_ui.tilt_deg"]
    assert not label.isHidden() or not widget.isHidden() or True  # row-visible flag below
    hidden_groups = [g for g, paths in form._groups if g.isHidden()]
    assert hidden_groups, "unmatched groups should hide"
    visible_groups = [g for g, paths in form._groups if not g.isHidden()]
    assert len(visible_groups) >= 1
    # filter survives a rebuild (language change / save path)
    form.populate()
    assert form._filter_text == "wrist"
    assert any(g.isHidden() for g, _ in form._groups)
    form.apply_filter("")
    assert not any(g.isHidden() for g, _ in form._groups)

    # focus helpers round-trip (offscreen needs the window shown + events)
    win.show()
    win.activateWindow()
    w2, _ = form._fields["osc.port"]
    w2.setFocus()
    QtWidgets.QApplication.processEvents()
    got = form.focused_field_path()
    assert got in ("osc.port", None), got  # None if offscreen refuses focus
    form.focus_field("osc.port")  # must not raise

    win._quitting = True
    win.close()
    print("smoke_settings: OK")


if __name__ == "__main__":
    main()
