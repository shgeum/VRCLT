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
QT_BG: Color = (18, 20, 26, 255)              # #12141a
QT_SURFACE: Color = (28, 31, 41, 255)         # #1c1f29
QT_SURFACE_HI: Color = (42, 48, 64, 255)      # #2a3040
QT_BORDER: Color = (48, 53, 66, 255)          # #303542
QT_HOVER: Color = (56, 66, 89, 255)           # #384259
QT_PRIMARY: Color = (31, 143, 77, 255)        # #1f8f4d
QT_PRIMARY_HOVER: Color = (38, 168, 93, 255)  # #26a85d
QT_PRIMARY_DISABLED: Color = (50, 81, 61, 255)  # #32513d
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
        QTabWidget::pane {{ border: 1px solid {border}; }}
        QTabBar::tab {{ padding: 10px 18px; background: {surface}; }}
        QTabBar::tab:selected {{ background: {surface_hi}; }}
        QGroupBox {{ border: 1px solid {border}; border-radius: 6px; margin-top: 10px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
            background: {surface}; color: {text}; border: 1px solid {border};
            border-radius: 4px; padding: 6px 8px; min-height: 28px;
        }}
        QPushButton {{
            background: {surface_hi}; color: {text}; border: 0; border-radius: 4px;
            padding: 8px 14px; min-height: 30px;
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton#primaryButton {{
            background: {primary}; color: #ffffff; font-weight: 800;
            padding: 9px 18px;
        }}
        QPushButton#primaryButton:hover {{ background: {primary_hover}; }}
        QPushButton#primaryButton:disabled {{
            background: {primary_disabled}; color: {text_dim};
        }}
        #statusText {{ font-weight: 700; }}
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
            padding: 10px 14px; font-weight: 600;
        }}
        QPushButton[modeButton="true"]:checked {{
            background: {text}; color: {bg}; border: 2px solid {text_idle};
            font-weight: 800;
        }}
        #statusDot {{ border-radius: 7px; background: {text_idle}; }}
        #statusDot[state="ok"] {{ background: {ok}; }}
        #statusDot[state="err"] {{ background: {err}; }}
        #statusDot[state="warn"] {{ background: {warn}; }}
        QPushButton#transToggle[on="true"] {{ background: {ok}; }}
        QPushButton#transToggle[on="false"] {{ background: {trans_off}; }}
        QPushButton#subToggle[on="true"] {{ background: {sub_blue}; }}
        QPushButton#overlayMoveBtn[active="true"] {{ background: {sub_blue}; }}
        QTextEdit#subtitleView {{
            background: {surface}; color: {text}; border: 1px solid {border};
            border-radius: 4px; padding: 6px 10px; font-size: 13pt;
        }}
    """.format(**c)
