"""Speaker metadata survives subtitle updates without changing legacy tuples."""
import pathlib
import sys
from dataclasses import FrozenInstanceError
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vrclt.subtitles import SubtitleLine, SubtitleStore


def test_legacy_and_rich_snapshots():
    store = SubtitleStore()
    store.add_final("hello", "안녕하세요", "en")
    store.set_partial("thanks", "고마워요")
    assert store.snapshot() == ([("hello", "안녕하세요", "en")], ("thanks", "고마워요"))
    finals, partial = store.snapshot_with_speakers()
    assert finals == [SubtitleLine("hello", "안녕하세요", "en")]
    assert partial == SubtitleLine("thanks", "고마워요")
    assert store.has_content()


def test_speaker_turns_and_delayed_final():
    store = SubtitleStore(max_lines=4)
    store.set_partial("source A", "translation A", speaker_id="1")
    store.add_final("source A", "translation A", "en", speaker_id="1")
    assert store.snapshot_with_speakers()[1] == SubtitleLine()
    store.set_partial("source B", "translation B", speaker_id="2")
    store.add_final("delayed A", "translation A2", "en", speaker_id="1")
    finals, partial = store.snapshot_with_speakers()
    assert [line.speaker_id for line in finals] == ["1", "1"]
    assert partial.speaker_id == "2" and partial.src == "source B"
    store.add_final("source B", "translation B", "ja", speaker_id="2")
    finals, partial = store.snapshot_with_speakers()
    assert [line.speaker_id for line in finals] == ["1", "1", "2"]
    assert partial == SubtitleLine()


def test_metadata_changes_notify_and_are_immutable():
    store = SubtitleStore()
    notifications = []
    store.subscribe(lambda: notifications.append(True))
    store.set_partial("same", "같음", speaker_id=1)
    store.set_partial("same", "같음", speaker_id="1")
    assert len(notifications) == 1, "unchanged speaker/text caused a redraw"
    store.set_partial("same", "같음", speaker_id="2")
    assert len(notifications) == 2, "speaker-only change was not published"
    _, partial = store.snapshot_with_speakers()
    try:
        partial.speaker_id = "3"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("render consumer could mutate shared subtitle metadata")
    store.set_partial("unknown", "알 수 없음", speaker_id="  ")
    assert store.snapshot_with_speakers()[1].speaker_id is None


def test_history_and_expiry_keep_metadata():
    store = SubtitleStore(max_lines=3, display_sec=7)
    with patch("vrclt.subtitles.time.time", return_value=100):
        for speaker in ("1", "2", "3", "4"):
            store.add_final(speaker, "translation", "en", speaker_id=speaker)
        assert [line.speaker_id for line in store.snapshot_with_speakers()[0]] == ["2", "3", "4"]
        store.configure(max_lines=2, display_sec=7)
        assert [line.speaker_id for line in store.snapshot_with_speakers()[0]] == ["3", "4"]
    with patch("vrclt.subtitles.time.time", return_value=108):
        assert store.snapshot_with_speakers() == ([], SubtitleLine())
        assert store.snapshot() == ([], ("", ""))
        assert not store.has_content()


if __name__ == "__main__":
    test_legacy_and_rich_snapshots()
    test_speaker_turns_and_delayed_final()
    test_metadata_changes_notify_and_are_immutable()
    test_history_and_expiry_keep_metadata()
    print("smoke_subtitle_speakers: OK")
