"""Canonical UI color tokens shared by the Qt desktop UI and the VR panels.

RGBA tuples are the canonical form (the VR panels draw with PIL); the Qt
stylesheet derives hex strings via hex_rgb(). This module must stay free of
Qt and PIL imports so the VR render thread can import it standalone.

Shared tokens carry the exact values both sides already used; QT_*/VR_*
tokens intentionally differ between the two UIs and must not be merged
without a deliberate visual decision.
"""
from __future__ import annotations

Color = tuple[int, int, int, int]

# ---- shared semantic colors (identical on both sides) ----
ON_GREEN: Color = (46, 160, 67, 255)      # #2ea043 - translation on / status ok
OFF_AMBER: Color = (120, 84, 30, 255)     # #78541e - translation off
# Qt used #2870aa while the VR panels drew (40, 110, 170) - the same intended
# color differing by 2/255 in green; unified on the Qt value.
SUB_BLUE: Color = (40, 112, 170, 255)     # #2870aa - subtitles on / info accent
ERR_RED: Color = (224, 100, 80, 255)      # #e06450 - hard errors
TEXT: Color = (240, 240, 240, 255)        # #f0f0f0 - primary text

# ---- Qt desktop palette ----
QT_BG: Color = (18, 24, 35, 255)             # #121823
QT_SURFACE: Color = (27, 37, 51, 255)        # #1b2533
QT_SURFACE_HI: Color = (39, 53, 71, 255)     # #273547
QT_BORDER: Color = (52, 68, 88, 255)         # #344458
QT_HOVER: Color = (54, 74, 97, 255)          # #364a61
QT_PRIMARY: Color = (54, 112, 168, 255)      # #3670a8
QT_PRIMARY_HOVER: Color = (68, 133, 196, 255)  # #4485c4
QT_PRIMARY_DISABLED: Color = (42, 62, 83, 255)  # #2a3e53
QT_TEXT_DIM: Color = (154, 160, 173, 255)     # #9aa0ad
QT_TEXT_IDLE: Color = (139, 148, 158, 255)    # #8b949e
QT_WARN: Color = (210, 153, 34, 255)          # #d29922
QT_WARN_TEXT: Color = (255, 213, 128, 255)    # #ffd580
QT_ERR_TEXT: Color = (255, 180, 168, 255)     # #ffb4a8
QT_INFO_TITLE: Color = (125, 184, 232, 255)   # #7db8e8
QT_INFO_BODY: Color = (201, 212, 227, 255)    # #c9d4e3
QT_TRAY_BLUE: Color = (74, 110, 180, 255)     # #4a6eb4
QT_EDIT_BLUE: Color = (88, 166, 255, 255)     # #58a6ff - overlay edit border

# ---- VR panel palette (PIL RGBA; alpha matters) ----
VR_BG: Color = (16, 18, 24, 235)
VR_BTN: Color = (38, 42, 54, 255)
VR_INSET: Color = (28, 30, 38, 255)           # label wells inside panels
VR_DIM: Color = (150, 150, 150, 255)
VR_DRAG: Color = (70, 110, 180, 255)
VR_WARN_AMBER: Color = (230, 168, 70, 255)
VR_DOT_IDLE: Color = (110, 110, 110, 255)
PENDING: Color = (130, 175, 255, 255)         # selected but not applied yet

# Speaker IDs describe voices within one recognition session, not identities.
# A fixed palette keeps a speaker consistent across desktop and VR surfaces;
# labels carry the distinction as well, so color is never the only cue.
SPEAKER_COLORS: tuple[Color, ...] = (
    (125, 190, 246, 255), (238, 184, 110, 255), (140, 212, 172, 255),
    (204, 164, 232, 255), (239, 152, 174, 255), (129, 211, 218, 255),
)


def speaker_color(speaker_id: str) -> Color:
    value = str(speaker_id)
    try:
        index = max(0, int(value) - 1)
    except ValueError:
        # Python's hash is randomized between processes; use a stable mapping.
        index = sum((i + 1) * ord(char) for i, char in enumerate(value))
    return SPEAKER_COLORS[index % len(SPEAKER_COLORS)]


def hex_rgb(col: Color) -> str:
    """'#rrggbb' for Qt stylesheets (alpha dropped)."""
    return "#%02x%02x%02x" % col[:3]


def rgba(col: Color, alpha: int = 255) -> Color:
    return (col[0], col[1], col[2], alpha)


def lighten(col: Color, f: float = 0.18) -> Color:
    """Lerp RGB toward white, keeping alpha - hover fills."""
    r, g, b = (round(c + (255 - c) * f) for c in col[:3])
    return (r, g, b, col[3] if len(col) > 3 else 255)


def darken(col: Color, f: float = 0.22) -> Color:
    """Scale RGB toward black, keeping alpha - pressed fills."""
    r, g, b = (round(c * (1.0 - f)) for c in col[:3])
    return (r, g, b, col[3] if len(col) > 3 else 255)


def build_qss() -> str:
    """The full application stylesheet, templated over the tokens above."""
    c = {
        "bg": hex_rgb(QT_BG),
        "surface": hex_rgb(QT_SURFACE),
        "surface_hi": hex_rgb(QT_SURFACE_HI),
        "border": hex_rgb(QT_BORDER),
        "hover": hex_rgb(QT_HOVER),
        "text": hex_rgb(TEXT),
        "text_dim": hex_rgb(QT_TEXT_DIM),
        "text_idle": hex_rgb(QT_TEXT_IDLE),
        "primary": hex_rgb(QT_PRIMARY),
        "primary_hover": hex_rgb(QT_PRIMARY_HOVER),
        "primary_disabled": hex_rgb(QT_PRIMARY_DISABLED),
        "warn": hex_rgb(QT_WARN),
        "warn_text": hex_rgb(QT_WARN_TEXT),
        "err_text": hex_rgb(QT_ERR_TEXT),
        "info_title": hex_rgb(QT_INFO_TITLE),
        "info_body": hex_rgb(QT_INFO_BODY),
        "sub_blue": hex_rgb(SUB_BLUE),
        "ok": hex_rgb(ON_GREEN),
        "err": hex_rgb(ERR_RED),
        "trans_off": hex_rgb(OFF_AMBER),
    }
    return """
        QMainWindow, QWidget {{ background: {bg}; color: {text}; }}
        QTabWidget::pane {{ border: 0; border-top: 1px solid {border}; }}
        QTabBar::tab {{ padding: 12px 24px; background: {bg}; color: {text_dim};
                       border-bottom: 2px solid transparent; }}
        QTabBar::tab:selected {{ color: {text}; border-bottom: 2px solid {info_title}; }}
        QTabBar::tab:hover {{ background: {surface}; color: {text}; }}
        QGroupBox {{ border: 1px solid {border}; border-radius: 8px;
                     margin-top: 12px; padding: 12px 8px 8px 8px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 14px;
                           padding: 0 6px; color: {text_dim}; }}
        QGroupBox#outboundPanel {{ border-top: 2px solid {ok}; }}
        QGroupBox#inboundPanel {{ border-top: 2px solid {info_title}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
            background: {surface}; color: {text}; border: 1px solid {border};
            border-radius: 5px; padding: 4px 8px; min-height: 26px;
        }}
        QPushButton {{
            background: {surface_hi}; color: {text}; border: 1px solid transparent;
            border-radius: 5px; padding: 6px 12px; min-height: 26px;
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:disabled, QToolButton:disabled {{ color: {text_idle}; background: {surface}; }}
        QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus,
        QAbstractSpinBox:focus {{ border: 1px solid {info_title}; }}
        QComboBox QAbstractItemView {{ background: {surface}; color: {text};
                                     selection-background-color: {hover}; }}
        QCheckBox {{ spacing: 8px; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; }}
        QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
        QSlider::sub-page:horizontal {{ background: {info_title}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ width: 14px; margin: -5px 0;
                                      background: {text}; border-radius: 7px; }}
        QScrollArea {{ border: 0; }}
        QScrollBar:vertical {{ background: {bg}; width: 10px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {border}; min-height: 32px; border-radius: 5px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        QPushButton#primaryButton {{
            background: {primary}; color: #ffffff; font-weight: 800;
            padding: 9px 18px;
        }}
        QPushButton#primaryButton:hover {{ background: {primary_hover}; }}
        QPushButton#primaryButton:disabled {{
            background: {primary_disabled}; color: {text_dim};
        }}
        #appWordmark {{ font-family: "Segoe UI"; font-size: 22pt; font-weight: 700; }}
        #statusText {{ color: {text_dim}; font-size: 10pt; }}
        #sectionTitle {{ font-weight: 600; color: {text_dim}; }}
        #speakerBadge {{ color: {info_title}; font-size: 10pt; }}
        QPushButton#engineButton {{ background: {surface}; border: 1px solid {border};
                                   color: {info_title}; }}
        QToolButton#disclosureButton {{ border: 1px solid transparent;
            border-radius: 4px; padding: 5px 0; color: {text_dim}; text-align: left; }}
        QToolButton#disclosureButton:hover {{ color: {text}; background: {surface}; }}
        QTabBar#settingsCategories::tab {{ padding: 9px 14px; }}
        #settingsSectionHint, #settingsEmpty {{ color: {text_dim}; }}
        #errorText {{ color: {err_text}; }}
        #noteText {{ color: {text_dim}; }}
        #updateBar {{
            background: {surface}; border: 1px solid {warn}; border-radius: 6px;
        }}
        #updateText {{ color: {warn_text}; font-weight: 600; }}
        #setupBar {{
            background: {surface}; border: 1px solid {sub_blue}; border-radius: 6px;
        }}
        #setupTitle {{ color: {info_title}; font-weight: 700; }}
        #setupText {{ color: {info_body}; }}
        QToolTip {{
            background: {surface}; color: {text};
            border: 1px solid {border}; padding: 4px 6px;
        }}
        QPushButton[modeButton="true"] {{
            background: {surface}; border: 1px solid {border}; border-radius: 8px;
            padding: 4px 12px; font-weight: 600;
        }}
        QPushButton[modeButton="true"]:checked {{
            background: {surface_hi}; color: {text}; border: 1px solid {info_title};
            font-weight: 700;
        }}
        #statusDot {{ border-radius: 7px; background: {text_idle}; }}
        #statusDot[state="ok"] {{ background: {ok}; }}
        #statusDot[state="err"] {{ background: {err}; }}
        #statusDot[state="warn"] {{ background: {warn}; }}
        QPushButton#transToggle, QPushButton#subToggle {{ min-height: 30px; }}
        QPushButton#transToggle[on="true"] {{ background: {ok}; }}
        QPushButton#transToggle[on="false"] {{ background: {trans_off}; }}
        QPushButton#subToggle[on="true"] {{ background: {sub_blue}; }}
        QPushButton#overlayMoveBtn[active="true"] {{ background: {sub_blue}; }}
        QTextEdit#subtitleView {{
            background: {surface}; color: {text}; border: 1px solid {border};
            border-radius: 4px; padding: 6px 10px; font-size: 13pt;
        }}
        QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"],
        QComboBox[invalid="true"], QAbstractSpinBox[invalid="true"] {{
            border: 1px solid {err};
        }}
    """.format(**c)
