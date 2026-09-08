"""Shared, escaped speaker-aware subtitle presentation for Qt surfaces."""
from html import escape

from ..subtitles import SubtitleLine
from . import theme


def subtitle_snapshot(controller):
    rich = getattr(controller, "subtitles_snapshot_with_speakers", None)
    if rich is not None:
        return rich()
    finals, partial = controller.subtitles_snapshot()
    return ([SubtitleLine(src, dst, lang) for src, dst, lang in finals],
            SubtitleLine(*partial))


def subtitle_html(finals, partial, tr, *, show_source=False) -> str:
    rows = []
    for line, provisional in [(line, False) for line in finals] + [(partial, True)]:
        if not (line.src or line.dst):
            continue
        text = escape(line.dst or line.src).replace("\n", "<br>")
        if show_source and line.src and line.dst:
            text = escape(line.src).replace("\n", "<br>") + "<br>" + text
        label = ""
        if line.speaker_id:
            color = theme.hex_rgb(theme.speaker_color(line.speaker_id))
            speaker = escape(tr("speaker_label").format(speaker=line.speaker_id))
            label = f'<span style="color:{color}; font-weight:600;">{speaker}</span>&nbsp; '
        style = f"color:{theme.hex_rgb(theme.QT_TEXT_DIM)}; font-style:italic;" if provisional else ""
        rows.append(f'<div style="margin-bottom:6px; {style}">{label}{text}</div>')
    return "".join(rows)
