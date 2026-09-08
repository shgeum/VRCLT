"""PIL-only VR regression for diarized subtitles; no SteamVR/GL session needed."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vrclt import i18n
from vrclt.state import AppState
from vrclt.subtitles import SubtitleLine, SubtitleStore
from vrclt.ui.theme import speaker_color
from vrclt.vr.subtitle_overlay import SubtitlePanel, MAX_TEX_H, TEX_W


class RecordingFont:
    def __init__(self, font):
        self.font = font
        self.drawn = []

    def __getattr__(self, name):
        return getattr(self.font, name)

    def draw(self, draw, xy, text, **kwargs):
        self.drawn.append((text, kwargs.get("fill")))
        return self.font.draw(draw, xy, text, **kwargs)


def main():
    store = SubtitleStore(display_sec=60)
    state = AppState()
    state.subtitles_on = True
    state.ui_lang = "ko"
    panel = SubtitlePanel(store, state, height_m=0.4)
    panel._font_small = RecordingFont(panel._font_small)

    store.add_final("hello", "안녕하세요", "ko", speaker_id="1")
    store.add_final("welcome", "반갑습니다", "ko", speaker_id="2")
    store.set_partial("let us begin", "이제 시작하겠습니다", speaker_id="1")
    has, signature, finals, partial, edit, phase = panel._render_state()
    assert has and phase is None
    img = panel._render(finals, partial, edit, phase)
    assert img.size == (TEX_W, MAX_TEX_H)
    assert panel._font_small.drawn == [
        ("화자 1", speaker_color("1")),
        ("화자 2", speaker_color("2")),
        ("화자 1", speaker_color("1")),
    ]

    # A display-language change changes the render signature even if text is unchanged.
    state.ui_lang = "ja"
    assert panel._render_state()[1] != signature
    panel._font_small.drawn.clear()
    panel._render(finals, partial)
    assert panel._font_small.drawn[0][0] == "話者 1"

    # When a long utterance fills the panel and its beginning gets cropped, the
    # first visible wrapped line still identifies its speaker.
    panel.set_size_m(0.9, 0.1)
    panel._font_small.drawn.clear()
    panel._render([SubtitleLine("", "long speech " * 100, "en", "2")], SubtitleLine())
    assert panel._font_small.drawn == [("話者 2", speaker_color("2"))]

    # Providers without speaker metadata keep plain subtitles without invented IDs.
    panel._font_small.drawn.clear()
    panel._render([SubtitleLine("hello", "안녕하세요", "ko")], SubtitleLine())
    assert panel._font_small.drawn == []

    # Verify the actual image contains both stable speaker colors.
    colors = {pixel for _count, pixel in img.getcolors(img.width * img.height)}
    assert speaker_color("1") in colors
    assert speaker_color("2") in colors
    assert speaker_color("1") != speaker_color("2")
    for lang in i18n.LANGS:
        assert "{speaker}" in i18n.STRINGS["speaker_label"][lang]
    panel.detach()
    print("smoke_vr_speakers: OK")


if __name__ == "__main__":
    main()
