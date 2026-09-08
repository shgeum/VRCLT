"""Offscreen settings regression: category/search navigation retains unsaved data,
engine changes reveal only relevant fields, invalid values remain reachable."""
import copy
import os
import pathlib
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6 import QtWidgets

from vrclt import config, i18n
from vrclt.ui.settings_form import SettingsForm, SettingsValidationError
from vrclt.ui.settings_schema import CATEGORIES, GROUPS
from vrclt.ui.setup_banner import SetupBanner


class Controller:
    raw_cfg = copy.deepcopy(config.DEFAULTS)

    def get_steamvr_auto_launch(self):
        return False

    def set_steamvr_auto_launch(self, _enabled):
        pass


def main():
    app = QtWidgets.QApplication([])
    root = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(root)
    ctl = Controller()
    form = SettingsForm(ctl, lambda key: i18n.tr("en", key), layout,
                        get_devices=lambda: ([""], [""]),
                        on_hotkey_capture_start=lambda: None,
                        on_hotkey_capture_end=lambda: None)
    form.populate()

    def visible(path):
        _spec, row_form, _label, widget = form._rows[path]
        return row_form.isRowVisible(widget)

    assert form._category_tabs.count() == len(CATEGORIES)
    assert visible("api_key")
    assert not visible("qwen.api_key")
    assert not visible("openai.api_key")
    assert not visible("soniox.api_key")
    assert not visible("soniox.keep_speaker_context")
    assert form._provider_note.isHidden()
    assert not visible("osc.port")

    # Navigation and engine changes preserve unsaved credentials for each engine.
    form._fields["api_key"][0].setText("saved-in-form-only")
    provider = form._fields["provider"][0]
    provider.setCurrentText("soniox")
    assert visible("soniox.api_key")
    assert visible("soniox.tts_model")
    assert visible("soniox.keep_speaker_context")
    assert not form._provider_note.isHidden()
    assert not visible("api_key")
    assert not visible("qwen.api_key")
    form._fields["soniox.api_key"][0].setText("soniox-unsaved")
    form._category_tabs.setCurrentIndex(1)
    assert visible("outbound.mic_device")
    assert not visible("soniox.api_key")
    assert form._provider_note.isHidden()
    result = form.config_from_fields()
    assert result["api_key"] == "saved-in-form-only"
    assert result["soniox"]["api_key"] == "soniox-unsaved"
    assert result["provider"] == "soniox"

    # Search spans categories and includes the SteamVR-owned live setting.
    form.apply_filter("wrist_ui.tilt_deg")
    assert visible("wrist_ui.tilt_deg")
    assert not visible("outbound.mic_device")
    assert not form._category_tabs.isEnabled()
    form.focus_field("wrist_ui.tilt_deg")
    assert form._filter_text == "wrist_ui.tilt_deg", "focus restore must retain a matching search"
    form.apply_filter("auto_launch")
    live_form, live_widget = form._autolaunch_row
    assert live_form.isRowVisible(live_widget)
    assert not form._empty_label.isVisible()
    form.apply_filter("no such setting 12345")
    assert not form._empty_label.isHidden()
    assert all(group.isHidden() for group, _paths in form._groups)
    form.apply_filter("")
    assert form._category_tabs.isEnabled()
    assert form._category_index == 1
    assert visible("outbound.mic_device")

    # Validation must reveal a hidden invalid field and ask the search box to clear.
    cleared = []
    form.filter_reset_requested.connect(lambda: cleared.append(True))
    form.apply_filter("soniox")
    form._fields["wrist_ui.roll_deg"][0].setText("-")
    try:
        form.config_from_fields()
        raise AssertionError("expected invalid roll value")
    except SettingsValidationError:
        pass
    assert cleared
    assert form._filter_text == ""
    assert visible("wrist_ui.roll_deg")
    assert form._category_index == len(CATEGORIES) - 1

    # Config sync and language/save rebuild restore provider visibility/category.
    ctl.raw_cfg["provider"] = "openai"
    form.sync_from_config()
    form.focus_field("provider")
    assert visible("openai.api_key")
    assert not visible("soniox.api_key")
    form._category_tabs.setCurrentIndex(1)
    form.populate()
    assert form._category_index == 1
    assert visible("outbound.mic_device")

    for _title, specs in GROUPS:
        for spec in specs:
            assert spec.label_key in i18n.STRINGS, spec.label_key
            for lang in i18n.LANGS:
                assert lang in i18n.STRINGS[spec.label_key], (spec.label_key, lang)

    urls = []
    banner = SetupBanner(lambda key: i18n.tr("en", key),
                         on_open_settings=lambda: None, on_open_url=urls.append)
    banner.sync("soniox", False)
    banner._open_key_page()
    assert urls[-1].toString() == "https://console.soniox.com/"
    assert "soniox" in banner._steps.text()

    root.close()
    print("smoke_settings_navigation: OK")


if __name__ == "__main__":
    main()
