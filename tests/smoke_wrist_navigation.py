"""Exercise the wrist menu's page boundaries and async Soniox control.

Uses the actual PIL widget tables and callbacks without OpenVR or an API key.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrclt.state import AppState
from vrclt.vr.button_table import widget_at
from vrclt.vr.wrist_ui import WristPanel, TEX_W, TEX_H


def main():
    state = AppState()
    current = {"provider": "soniox", "context": True, "timeout": 60.0}
    pending = []
    text_only = []
    restarts = []
    panel = WristPanel(
        state, ["en", "ko", "ja"], inbound_languages=["ko", "en"],
        get_provider=lambda: current["provider"],
        get_speaker_context=lambda: (current["context"], current["timeout"]),
        set_speaker_context=lambda enabled, done: pending.append((enabled, done)),
        on_text_only_toggle=text_only.append,
        on_restart=lambda: restarts.append(True),
    )

    def names():
        return {w.name for w in panel._active_widgets() if w.kind == "button"}

    assert names() == {"toggle", "sub_toggle", "lang", "sub_lang",
                       "nav_live", "nav_settings"}
    panel._on_click("speaker_context")
    panel._on_click("text_only")
    panel._on_click("restart")
    assert not pending and not text_only and not restarts

    panel._pressed_name = "nav_settings"
    panel._on_click("nav_settings")
    assert panel._page == "settings" and panel._pressed_name is None
    assert {"speaker_context", "edit", "sub_edit", "reset", "font_minus",
            "font_plus", "uilang", "text_only", "restart"} <= names()
    before = state.translation_on
    panel._on_click("toggle")  # hidden controls cannot fire after navigation
    assert state.translation_on == before

    panel._on_click("speaker_context")
    assert panel._speaker_context_pending and pending[0][0] is False
    panel._on_click("speaker_context")
    panel._on_click("restart")
    panel._on_click("text_only")
    assert len(pending) == 1 and not restarts and not text_only
    button = next(w for w in panel._active_widgets() if w.name == "speaker_context")
    x0, y0, x1, y1 = button.rect
    assert widget_at(panel._active_widgets(), panel, (x0 + x1) / 2,
                     (y0 + y1) / 2, "settings") is None
    pending.pop()[1](False)
    assert not panel._speaker_context_pending and panel._speaker_context_failed
    assert current["context"] is True
    panel._update_context_feedback(time.time() + 6)
    assert not panel._speaker_context_failed
    panel._on_click("speaker_context")
    value, done = pending.pop()
    current["context"] = value
    done(True)
    assert not panel._speaker_context_pending and not panel._speaker_context_failed
    assert current["context"] is False

    # Closing a language picker returns to live; looking away from settings
    # should retain that page rather than unexpectedly reopening live.
    panel._close_picker()
    assert panel._page == "settings"
    panel._on_click("nav_live")
    panel._on_click("lang")
    assert panel._page == "lang_out"
    assert {"nav_live", "nav_settings", "picker_close", "pick_out:ko"} <= names()
    panel._on_click("pick_out:ko")
    assert panel._page == "main" and state.target_language == "ko"
    panel._on_click("sub_lang")
    panel._on_click("nav_settings")
    assert panel._page == "settings"

    panel._on_click("speaker_context")
    pending.pop()[1](False)
    assert panel._speaker_context_failed
    current["context"] = True  # a successful change from the desktop UI
    panel._update_context_feedback(time.time())
    assert not panel._speaker_context_failed

    current["provider"] = "gemini"
    assert "speaker_context" not in names()
    panel._on_click("speaker_context")
    assert not pending

    # Every page shares visible draw and hit bounds, in every UI language.
    for provider in ("gemini", "soniox"):
        current["provider"] = provider
        for lang in ("en", "ko", "ja", "zh"):
            state.ui_lang = lang
            for page in ("main", "settings", "lang_out", "lang_in"):
                panel._set_page(page)
                widgets = panel._active_widgets()
                buttons = [w for w in widgets if w.kind == "button"]
                for index, w in enumerate(buttons):
                    x0, y0, x1, y1 = w.rect
                    assert 0 <= x0 < x1 < TEX_W and 0 <= y0 < y1 < TEX_H
                    assert widget_at(widgets, panel, (x0 + x1) / 2,
                                     (y0 + y1) / 2, page) == w.name
                    for other in buttons[index + 1:]:
                        a0, b0, a1, b1 = other.rect
                        assert min(x1, a1) <= max(x0, a0) or \
                            min(y1, b1) <= max(y0, b0), (w.name, other.name)
                assert panel._render((True, "status_running", ""), False).size == \
                    (TEX_W, TEX_H)
    panel.detach()
    print("smoke_wrist_navigation: OK")


if __name__ == "__main__":
    main()
