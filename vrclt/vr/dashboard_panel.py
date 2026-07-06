"""SteamVR dashboard settings panel (component of the VR render thread).

Lives in the SteamVR dashboard (system-menu overlay bar). Unlike the wrist
menu it needs no laser/cursor/gaze machinery: SteamVR shows its own pointer
and delivers overlay mouse events (pollNextOverlayEvent), and the dashboard
also controls placement, so there is no transform handling either.

Texture is a persistent OpenGL texture (see vr/render.py for why).
"""
import logging
import threading

from PIL import Image, ImageDraw

from .. import __version__
from ..config import APPDATA_DIR
from ..i18n import tr, LANGS as UI_LANGS, UI_LANG_LABELS
from ..resources import bundled_font, resolve_font_path
from ..state import AppState
from .font_fallback import load_fallback_font
from .panel_common import (
    COL_BG, COL_BTN, COL_DIM, COL_DRAG, COL_ON, COL_OFF, COL_SUB_ON, COL_TEXT,
    cycle, draw_fit_text, language_label,
)
from .render import GlTexture, flip_bounds

log = logging.getLogger(__name__)

TEX_W, TEX_H = 1024, 640
OVERLAY_KEY = "shgeum.vrclt.dashboard"
OVERLAY_NAME = "vrclt"
WIDTH_M = 2.4  # advisory; the dashboard scales overlays itself
ICON_PATH = APPDATA_DIR / "dashboard_icon.png"

# OpenVR overlay mouse coords use a bottom-left origin; our button rects are
# top-left. Flip determined empirically - if rows ever hit mirrored, flip this.
MOUSE_Y_BOTTOM_UP = True

# header row
STATUS_DOT = (24, 24, 56, 56)
BTN_UILANG = (560, 14, 668, 74)
BTN_AUTOSTART = (684, 14, 856, 74)
BTN_RESTART = (872, 14, 1008, 74)
# translation row
BTN_TOGGLE = (16, 94, 500, 300)
BTN_PREV = (516, 94, 596, 300)
BTN_LANG = (604, 94, 924, 300)       # label only
BTN_NEXT = (932, 94, 1008, 300)
# subtitles row
BTN_SUB_TOGGLE = (16, 320, 500, 526)
BTN_SUB_PREV = (516, 320, 596, 526)
BTN_SUB_LANG = (604, 320, 924, 526)  # label only
BTN_SUB_NEXT = (932, 320, 1008, 526)
# bottom row
BTN_TEXT_ONLY = (16, 546, 240, 624)
BTN_FONT_MINUS = (264, 546, 344, 624)
LBL_FONT_SIZE = (352, 546, 452, 624)  # label only
BTN_FONT_PLUS = (460, 546, 540, 624)
BTN_SUB_EDIT = (564, 546, 724, 624)
BTN_WRIST_EDIT = (748, 546, 908, 624)
BTN_RESET = (924, 546, 1008, 624)

BUTTONS = (("toggle", BTN_TOGGLE), ("prev", BTN_PREV), ("next", BTN_NEXT),
           ("sub_toggle", BTN_SUB_TOGGLE), ("sub_prev", BTN_SUB_PREV),
           ("sub_next", BTN_SUB_NEXT), ("text_only", BTN_TEXT_ONLY),
           ("font_minus", BTN_FONT_MINUS), ("font_plus", BTN_FONT_PLUS),
           ("sub_edit", BTN_SUB_EDIT), ("wrist_edit", BTN_WRIST_EDIT),
           ("reset", BTN_RESET), ("uilang", BTN_UILANG),
           ("autostart", BTN_AUTOSTART), ("restart", BTN_RESTART))


def _ensure_icon() -> bool:
    """256px thumbnail matching the Qt tray icon (blue rounded rect + V)."""
    try:
        if ICON_PATH.exists():
            return True
        ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
        s = 256
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((24, 24, s - 24, s - 24), 56, fill=(74, 110, 180, 255))
        d.polygon([(70, 84), (108, 84), (128, 156), (148, 84), (186, 84),
                   (148, 196), (108, 196)], fill=(255, 255, 255, 255))
        img.save(ICON_PATH, "PNG")
        return True
    except Exception:
        log.warning("failed to create dashboard icon", exc_info=True)
        return False


class DashboardPanel:
    def __init__(self, state: AppState, languages: list[str], *,
                 inbound_languages: list[str] | None = None,
                 font_path: str = bundled_font("NotoSansCJKkr-Bold.otf"),
                 get_status=lambda: False,
                 on_text_only_toggle=lambda enabled: None,
                 on_font_size=lambda size: None,
                 get_font_size=lambda: 27,
                 get_auto_launch=lambda: None,
                 set_auto_launch=lambda enabled: None,
                 on_restart=lambda: None):
        self._state = state
        self._languages = languages or ["en"]
        self._inbound_languages = inbound_languages or ["ko", "en"]
        self._get_status = get_status
        self._on_text_only_toggle = on_text_only_toggle
        self._on_font_size = on_font_size
        self._get_font_size = get_font_size
        self._get_auto_launch = get_auto_launch
        self._set_auto_launch = set_auto_launch
        self._on_restart = on_restart

        font_path = resolve_font_path(font_path, "NotoSansCJKkr-Bold.otf")
        self._font_big = load_fallback_font(font_path, 64, bold=True)
        self._font_mid = load_fallback_font(font_path, 40, bold=True)
        self._font_small = load_fallback_font(font_path, 28, bold=True)
        self._font_tiny = load_fallback_font(font_path, 22, bold=True)

        self._dirty = threading.Event()
        self._dirty.set()
        state.subscribe(lambda *_: self._dirty.set())

        self._h = self._h_thumb = None
        self._tex = None

    # ---------------- component lifecycle ----------------
    def setup(self, ctx) -> bool:
        openvr, ovl = ctx.openvr, ctx.ovl
        try:
            self._h, self._h_thumb = ovl.createDashboardOverlay(
                OVERLAY_KEY, OVERLAY_NAME)
        except Exception as e:
            if "KeyInUse" in type(e).__name__:
                log.warning(
                    "dashboard panel: overlay key in use - another vrclt instance running?")
                return False
            raise

        ovl.setOverlayWidthInMeters(self._h, WIDTH_M)
        ovl.setOverlayTextureBounds(self._h, flip_bounds(openvr))
        ovl.setOverlayInputMethod(self._h, openvr.VROverlayInputMethod_Mouse)
        scale = openvr.HmdVector2_t()
        scale.v[0], scale.v[1] = float(TEX_W), float(TEX_H)
        ovl.setOverlayMouseScale(self._h, scale)
        if _ensure_icon():
            try:
                ovl.setOverlayFromFile(self._h_thumb, str(ICON_PATH))
            except Exception:
                log.debug("dashboard thumbnail failed", exc_info=True)

        self._tex = GlTexture(TEX_W, TEX_H)
        self._event = openvr.VREvent_t()
        self._visible = bool(ovl.isOverlayVisible(self._h))
        self._pressed = None
        self._hover_px = None
        self._last_status = None
        self._last_shown_check = 0.0
        self._dirty.set()
        log.info("dashboard panel ready (GL texture)")
        return True

    def teardown(self, ctx) -> None:
        for h in (self._h, self._h_thumb):
            if h is None:
                continue
            try:
                ctx.ovl.destroyOverlay(h)
            except Exception:
                pass
        self._h = self._h_thumb = None
        if self._tex is not None:
            self._tex.delete()
            self._tex = None

    # ---------------- per-frame ----------------
    def tick(self, ctx, now: float) -> None:
        openvr, ovl = ctx.openvr, ctx.ovl

        while True:
            ok, self._event = ovl.pollNextOverlayEvent(self._h, self._event)
            if not ok:
                break
            self._handle_event(openvr, self._event)

        if (now - self._last_shown_check) > 1.0:
            self._last_shown_check = now
            status = bool(self._get_status())
            if status != self._last_status:
                self._last_status = status
                self._dirty.set()
            # events are authoritative, but resync visibility defensively
            try:
                self._visible = bool(ovl.isOverlayVisible(self._h))
            except Exception:
                pass

        if self._visible and self._dirty.is_set():
            self._dirty.clear()
            self._tex.update(self._render(bool(self._last_status)))
            ovl.setOverlayTexture(self._h, self._tex.vr_texture(openvr))

    def _handle_event(self, openvr, ev) -> None:
        et = ev.eventType
        if et == openvr.VREvent_MouseMove:
            self._hover_px = self._mouse_px(ev)
        elif et == openvr.VREvent_MouseButtonDown:
            if ev.data.mouse.button == openvr.VRMouseButton_Left:
                self._pressed = self._button_at(self._mouse_px(ev))
        elif et == openvr.VREvent_MouseButtonUp:
            if ev.data.mouse.button == openvr.VRMouseButton_Left:
                released_on = self._button_at(self._mouse_px(ev))
                if released_on is not None and released_on == self._pressed:
                    self._on_click(released_on)
                    self._dirty.set()
                self._pressed = None
        elif et == openvr.VREvent_OverlayShown:
            self._visible = True
            self._dirty.set()
        elif et == openvr.VREvent_OverlayHidden:
            self._visible = False
            self._pressed = None

    @staticmethod
    def _mouse_px(ev) -> tuple[float, float]:
        x = float(ev.data.mouse.x)
        y = float(ev.data.mouse.y)
        if MOUSE_Y_BOTTOM_UP:
            y = TEX_H - y
        return x, y

    @staticmethod
    def _button_at(px: tuple[float, float]) -> str | None:
        x, y = px
        for name, (x0, y0, x1, y1) in BUTTONS:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return name
        return None

    def _on_click(self, button: str) -> None:
        log.info("dashboard panel click: %s", button)
        st = self._state
        if button == "toggle":
            st.translation_on = not st.translation_on
        elif button == "sub_toggle":
            st.subtitles_on = not st.subtitles_on
        elif button in ("prev", "next"):
            st.target_language = cycle(self._languages, st.target_language,
                                       1 if button == "next" else -1)
        elif button in ("sub_prev", "sub_next"):
            st.inbound_language = cycle(self._inbound_languages, st.inbound_language,
                                        1 if button == "sub_next" else -1)
        elif button == "text_only":
            self._on_text_only_toggle(not st.text_only)
        elif button == "font_minus":
            self._on_font_size(int(self._get_font_size()) - 2)
        elif button == "font_plus":
            self._on_font_size(int(self._get_font_size()) + 2)
        elif button == "sub_edit":
            st.edit_mode = not st.edit_mode
        elif button == "wrist_edit":
            st.wrist_edit_mode = not st.wrist_edit_mode
        elif button == "uilang":
            st.ui_lang = cycle(UI_LANGS, st.ui_lang, 1)
        elif button == "autostart":
            current = self._get_auto_launch()
            if current is not None:
                self._set_auto_launch(not current)
        elif button == "restart":
            self._on_restart()
        elif button == "reset":
            st.request_position_reset()

    # ---------------- rendering ----------------
    def _btn(self, d, box, text: str, *, fill=COL_BTN, fonts=None, text_fill=COL_TEXT,
             radius: int = 16) -> None:
        d.rounded_rectangle(box, radius, fill=fill)
        draw_fit_text(d, box, text,
                      fonts=fonts or (self._font_small, self._font_tiny),
                      fill=text_fill, max_lines=1, pad_x=8, pad_y=4)

    def _lang_block(self, d, lang, prev_box, lang_box, next_box, code: str,
                    caption: str) -> None:
        for box, label in ((prev_box, "◀"), (next_box, "▶")):
            d.rounded_rectangle(box, 16, fill=COL_BTN)
            self._font_mid.draw(d, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2),
                                label, fill=COL_TEXT, anchor="mm")
        d.rounded_rectangle(lang_box, 16, fill=(28, 30, 38, 255))
        draw_fit_text(
            d, (lang_box[0] + 6, lang_box[1] + 26, lang_box[2] - 6, lang_box[3] - 66),
            language_label(code),
            fonts=(self._font_big, self._font_mid, self._font_small, self._font_tiny),
            max_lines=1, pad_x=4, pad_y=2)
        draw_fit_text(
            d, (lang_box[0] + 6, lang_box[3] - 62, lang_box[2] - 6, lang_box[3] - 12),
            caption, fonts=(self._font_tiny,), fill=COL_DIM, max_lines=1,
            pad_x=4, pad_y=2, line_spacing=0)

    def _render(self, connected: bool) -> Image.Image:
        st = self._state
        lang = st.ui_lang
        img = Image.new("RGBA", (TEX_W, TEX_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, TEX_W - 1, TEX_H - 1), 28, fill=COL_BG)

        # header: status + version
        dot = COL_ON if connected else (110, 110, 110, 255)
        d.ellipse(STATUS_DOT, fill=dot)
        self._font_small.draw(d, (72, (STATUS_DOT[1] + STATUS_DOT[3]) // 2),
                              f"vrclt v{__version__}", fill=COL_TEXT, anchor="lm")
        self._btn(d, BTN_UILANG, UI_LANG_LABELS.get(lang, lang))
        auto = self._get_auto_launch()
        if auto is None:
            self._btn(d, BTN_AUTOSTART, tr(lang, "btn_autostart_off"),
                      text_fill=COL_DIM)
        else:
            self._btn(d, BTN_AUTOSTART,
                      tr(lang, "btn_autostart_on" if auto else "btn_autostart_off"),
                      fill=COL_SUB_ON if auto else COL_BTN)
        self._btn(d, BTN_RESTART, tr(lang, "btn_restart_runtime"))

        # translation row
        on = st.translation_on
        d.rounded_rectangle(BTN_TOGGLE, 20, fill=COL_ON if on else COL_OFF)
        cy = (BTN_TOGGLE[1] + BTN_TOGGLE[3]) // 2
        draw_fit_text(d, (BTN_TOGGLE[0] + 12, BTN_TOGGLE[1] + 34,
                          BTN_TOGGLE[2] - 12, cy + 20),
                      tr(lang, "btn_trans_on" if on else "btn_trans_off"),
                      fonts=(self._font_big, self._font_mid, self._font_small),
                      max_lines=1, pad_x=0, pad_y=0)
        draw_fit_text(d, (BTN_TOGGLE[0] + 12, cy + 24,
                          BTN_TOGGLE[2] - 12, BTN_TOGGLE[3] - 26),
                      tr(lang, "my_to_other"),
                      fonts=(self._font_small, self._font_tiny),
                      max_lines=1, pad_x=0, pad_y=0, line_spacing=0)
        self._lang_block(d, lang, BTN_PREV, BTN_LANG, BTN_NEXT,
                         st.target_language, tr(lang, "out_lang"))

        # subtitles row
        sub_on = st.subtitles_on
        d.rounded_rectangle(BTN_SUB_TOGGLE, 20, fill=COL_SUB_ON if sub_on else COL_BTN)
        cy = (BTN_SUB_TOGGLE[1] + BTN_SUB_TOGGLE[3]) // 2
        draw_fit_text(d, (BTN_SUB_TOGGLE[0] + 12, BTN_SUB_TOGGLE[1] + 34,
                          BTN_SUB_TOGGLE[2] - 12, cy + 20),
                      tr(lang, "btn_sub_on" if sub_on else "btn_sub_off"),
                      fonts=(self._font_big, self._font_mid, self._font_small),
                      max_lines=1, pad_x=0, pad_y=0)
        draw_fit_text(d, (BTN_SUB_TOGGLE[0] + 12, cy + 24,
                          BTN_SUB_TOGGLE[2] - 12, BTN_SUB_TOGGLE[3] - 26),
                      tr(lang, "other_to_sub"),
                      fonts=(self._font_small, self._font_tiny),
                      max_lines=1, pad_x=0, pad_y=0, line_spacing=0)
        self._lang_block(d, lang, BTN_SUB_PREV, BTN_SUB_LANG, BTN_SUB_NEXT,
                         st.inbound_language, tr(lang, "sub_lang"))

        # bottom row
        text_only = st.text_only
        self._btn(d, BTN_TEXT_ONLY,
                  tr(lang, "btn_text_only_on" if text_only else "btn_text_only_off"),
                  fill=COL_SUB_ON if text_only else COL_BTN)
        self._btn(d, BTN_FONT_MINUS, "−", fonts=(self._font_mid,))
        d.rounded_rectangle(LBL_FONT_SIZE, 16, fill=(28, 30, 38, 255))
        draw_fit_text(d, (LBL_FONT_SIZE[0], LBL_FONT_SIZE[1] + 6,
                          LBL_FONT_SIZE[2], LBL_FONT_SIZE[1] + 46),
                      str(int(self._get_font_size())),
                      fonts=(self._font_small,), max_lines=1, pad_x=4, pad_y=2)
        draw_fit_text(d, (LBL_FONT_SIZE[0], LBL_FONT_SIZE[3] - 34,
                          LBL_FONT_SIZE[2], LBL_FONT_SIZE[3] - 6),
                      tr(lang, "dash_font_size"),
                      fonts=(self._font_tiny,), fill=COL_DIM, max_lines=1,
                      pad_x=2, pad_y=1, line_spacing=0)
        self._btn(d, BTN_FONT_PLUS, "+", fonts=(self._font_mid,))
        self._btn(d, BTN_SUB_EDIT, tr(lang, "sub_move"),
                  fill=COL_DRAG if st.edit_mode else COL_BTN)
        self._btn(d, BTN_WRIST_EDIT, tr(lang, "wrist_move"),
                  fill=COL_DRAG if st.wrist_edit_mode else COL_BTN)
        self._btn(d, BTN_RESET, tr(lang, "pos_reset"))
        return img
