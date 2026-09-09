"""SteamVR dashboard settings panel (component of the VR render thread).

Lives in the SteamVR dashboard (system-menu overlay bar). Unlike the wrist
menu it needs no laser/cursor/gaze machinery: SteamVR shows its own pointer
and delivers overlay mouse events (pollNextOverlayEvent), and the dashboard
also controls placement, so there is no transform handling either.

Texture is a persistent OpenGL texture (see vr/render.py for why).
"""
import logging
import shutil
import threading
import time

from PIL import Image, ImageDraw

from .. import __version__
from ..config import APPDATA_DIR, OVERLAY_FONT_MAX, OVERLAY_FONT_MIN
from ..i18n import tr, LANGS as UI_LANGS, UI_LANG_LABELS
from ..ui import theme
from .button_table import (
    Widget, draw_page, glyph_draw, lang_grid_widgets, lang_page_count,
    widget_at,
)
from ..resources import bundled_font, icon_path as icon_asset_path, resolve_font_path
from ..state import AppState
from .font_fallback import load_fallback_font
from .panel_common import (
    COL_BG, COL_BTN, COL_DIM, COL_DRAG, COL_INSET, COL_ON, COL_OFF,
    COL_PENDING, COL_SUB_ON, COL_TEXT,
    COL_ERR_RED as COL_ERR, COL_WARN_AMBER as COL_WARN,
    cycle, draw_fit_text, language_label, status_dot_color,
)
from .render import GlTexture, flip_bounds

log = logging.getLogger(__name__)

TEX_W, TEX_H = 1024, 950
OVERLAY_KEY = "shgeum.vrclt.dashboard"
OVERLAY_NAME = "vrclt"
WIDTH_M = 2.4  # advisory; the dashboard scales overlays itself
ICON_PATH = APPDATA_DIR / "dashboard_icon.png"
# device cycling saves + restarts the runtime; batch rapid clicks into one
# apply this long after the last click
DEVICE_APPLY_DELAY_SEC = 1.8

# Fixed pages share header/navigation positions; content controls are large
# enough to hit with SteamVR's pointer without crowding unrelated settings.
MOUSE_Y_BOTTOM_UP = True
STATUS_DOT = (24, 32, 48, 56)
STATUS_TEXT_BOX = (544, 20, 1000, 76)
NAV_RECTS = {"main": (24, 110, 338, 180),
             "audio": (354, 110, 668, 180),
             "layout": (684, 110, 1000, 180)}
NAV_KEYS = {"main": "vr_nav_live", "audio": "vr_nav_audio", "layout": "vr_nav_layout"}
BTN_TOGGLE = (40, 286, 484, 392)
BTN_LANG = (40, 412, 484, 550)
BTN_SUB_TOGGLE = (540, 286, 984, 392)
BTN_SUB_LANG = (540, 412, 984, 550)
BTN_SRC_PREV = (40, 574, 104, 678)
LBL_SRC_LANG = (112, 574, 412, 678)
BTN_SRC_NEXT = (420, 574, 484, 678)
BTN_INSRC_PREV = (540, 574, 604, 678)
LBL_INSRC_LANG = (612, 574, 912, 678)
BTN_INSRC_NEXT = (920, 574, 984, 678)
BTN_SPEAKER_CONTEXT = (24, 734, 516, 830)
CONTEXT_NOTE_BOX = (536, 734, 1000, 830)
BTN_MIC_PREV = (24, 274, 112, 402)
LBL_MIC_DEVICE = (128, 274, 896, 402)
BTN_MIC_NEXT = (912, 274, 1000, 402)
BTN_OUT_PREV = (24, 426, 112, 554)
LBL_OUT_DEVICE = (128, 426, 896, 554)
BTN_OUT_NEXT = (912, 426, 1000, 554)
BTN_VOL_MINUS = (24, 616, 152, 730)
LBL_VOL_GAIN = (168, 616, 856, 730)
BTN_VOL_PLUS = (872, 616, 1000, 730)
BTN_TEXT_ONLY = (24, 768, 1000, 854)
BTN_FONT_MINUS = (24, 264, 152, 370)
LBL_FONT_SIZE = (168, 264, 856, 370)
BTN_FONT_PLUS = (872, 264, 1000, 370)
BTN_SUB_EDIT = (24, 438, 500, 544)
BTN_WRIST_EDIT = (524, 438, 1000, 544)
BTN_RESET = (24, 568, 1000, 644)
BTN_UILANG = (24, 726, 328, 822)
BTN_AUTOSTART = (344, 726, 656, 822)
BTN_RESTART = (672, 726, 1000, 822)
GAIN_MIN, GAIN_MAX = 0.0, 2.0
PICKER_CAPTION = (24, 18, 640, 86)
PICKER_PGPREV = (656, 18, 744, 86)
PICKER_PGNEXT = (760, 18, 848, 86)
PICKER_CLOSE = (912, 18, 1000, 86)
PICKER_GRID = (24, 110, 1000, 926)
PICKER_COLS, PICKER_ROWS = 4, 5


def _build_widgets() -> tuple:
    source_hints = lambda p: p._get_provider() in ("qwen", "soniox")
    free = lambda p: not (p._devices_applying or p._context_applying or p._restart_pending)
    settled = lambda p: free(p) and p._pending_mic is None and p._pending_out is None
    widgets = []
    for page in NAV_RECTS:
        widgets.extend(Widget("nav_" + target, rect, page=page)
                       for target, rect in NAV_RECTS.items())
    widgets.extend((
        Widget("toggle", BTN_TOGGLE), Widget("lang", BTN_LANG),
        Widget("sub_toggle", BTN_SUB_TOGGLE), Widget("sub_lang", BTN_SUB_LANG),
        Widget("src_prev", BTN_SRC_PREV, enabled=source_hints),
        Widget("src_next", BTN_SRC_NEXT, enabled=source_hints),
        Widget("insrc_prev", BTN_INSRC_PREV, enabled=source_hints),
        Widget("insrc_next", BTN_INSRC_NEXT, enabled=source_hints),
        Widget("speaker_context", BTN_SPEAKER_CONTEXT,
               enabled=lambda p: p._get_provider() == "soniox" and settled(p)),
        Widget("mic_prev", BTN_MIC_PREV, page="audio", enabled=free),
        Widget("mic_next", BTN_MIC_NEXT, page="audio", enabled=free),
        Widget("out_prev", BTN_OUT_PREV, page="audio", enabled=free),
        Widget("out_next", BTN_OUT_NEXT, page="audio", enabled=free),
        Widget("vol_minus", BTN_VOL_MINUS, page="audio",
               enabled=lambda p: float(p._get_tts_gain()) > GAIN_MIN),
        Widget("vol_plus", BTN_VOL_PLUS, page="audio",
               enabled=lambda p: float(p._get_tts_gain()) < GAIN_MAX),
        Widget("text_only", BTN_TEXT_ONLY, page="audio", enabled=settled),
        Widget("font_minus", BTN_FONT_MINUS, page="layout",
               enabled=lambda p: int(p._get_font_size()) > OVERLAY_FONT_MIN),
        Widget("font_plus", BTN_FONT_PLUS, page="layout",
               enabled=lambda p: int(p._get_font_size()) < OVERLAY_FONT_MAX),
        Widget("sub_edit", BTN_SUB_EDIT, page="layout"),
        Widget("wrist_edit", BTN_WRIST_EDIT, page="layout"),
        Widget("reset", BTN_RESET, page="layout"),
        Widget("uilang", BTN_UILANG, page="layout"),
        Widget("autostart", BTN_AUTOSTART, page="layout",
               enabled=lambda p: p._get_auto_launch() is not None),
        Widget("restart", BTN_RESTART, page="layout", enabled=settled),
    ))
    return tuple(widgets)


def _ensure_icon() -> bool:
    """256px thumbnail: the bundled app icon (scripts/make_icon.py), with
    the original painted mark as fallback when the asset is missing."""
    try:
        if ICON_PATH.exists():
            return True
        ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
        bundled = icon_asset_path("icon.png")
        if bundled.exists():
            shutil.copyfile(bundled, ICON_PATH)
            return True
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
                 get_status_info=lambda: (False, "status_stopped", ""),
                 on_text_only_toggle=lambda enabled: None,
                 on_font_size=lambda size: None,
                 get_font_size=lambda: 27,
                 get_auto_launch=lambda: None,
                 set_auto_launch=lambda enabled: None,
                 on_restart=lambda: None,
                 get_devices=lambda: ([""], [""]),
                 get_mic_device=lambda: "",
                 get_tts_device=lambda: "",
                 set_audio_devices=lambda mic, tts, on_done: on_done(False),
                 on_tts_gain=lambda value: None,
                 get_tts_gain=lambda: 1.0,
                 get_provider=lambda: "gemini",
                 get_speaker_context=lambda: (True, 60.0),
                 set_speaker_context=lambda enabled, on_done: on_done(False)):
        self._state = state
        self._languages = languages or ["en"]
        self._inbound_languages = inbound_languages or ["ko", "en"]
        self._get_status_info = get_status_info
        self._on_text_only_toggle = on_text_only_toggle
        self._on_font_size = on_font_size
        self._get_font_size = get_font_size
        self._get_auto_launch = get_auto_launch
        self._set_auto_launch = set_auto_launch
        self._on_restart = on_restart
        self._get_devices = get_devices
        self._get_mic_device = get_mic_device
        self._get_tts_device = get_tts_device
        self._set_audio_devices = set_audio_devices
        self._on_tts_gain = on_tts_gain
        self._get_tts_gain = get_tts_gain
        self._get_provider = get_provider
        self._get_speaker_context = get_speaker_context
        self._set_speaker_context = set_speaker_context
        self._context_applying = False
        self._context_error_until = 0.0
        self._last_controls = None
        self._last_provider = None
        # device pickers: pending selections apply (save + runtime restart)
        # once, DEVICE_APPLY_DELAY_SEC after the last click
        self._dev_inputs, self._dev_outputs = get_devices()
        self._pending_mic: str | None = None
        self._pending_out: str | None = None
        self._devices_apply_at = 0.0
        self._devices_applying = False
        self._devices_error_until = 0.0
        self._widgets = _build_widgets()
        self._widget_by_name = {w.name: w for w in self._widgets}
        self._page = "main"
        self._pressed = None
        self._picker_idx = 0
        self._picker_cache: dict = {}
        self._restart_pending = False
        self._restart_started = 0.0
        self._restart_seen_transition = False

        font_path = resolve_font_path(font_path, "NotoSansCJKkr-Bold.otf")
        self._font_mid = load_fallback_font(font_path, 40, bold=True)
        self._font_small = load_fallback_font(font_path, 28, bold=True)
        self._font_tiny = load_fallback_font(font_path, 22, bold=True)

        self._dirty = threading.Event()
        self._dirty.set()
        state.subscribe(self._on_state)

        self._h = self._h_thumb = None
        self._tex = None

    def _on_state(self, _field: str, _value) -> None:
        self._dirty.set()

    def detach(self) -> None:
        """Drop the AppState subscription (the state outlives panels)."""
        self._state.unsubscribe(self._on_state)

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
        self._last_auto = object()  # sentinel: first poll always renders
        self._last_shown_check = 0.0
        self._dev_inputs, self._dev_outputs = self._get_devices()
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
            status = self._get_status_info()
            if status != self._last_status:
                self._last_status = status
                self._dirty.set()
            if self._restart_pending:
                # clear once the runtime left running (Starting) and came
                # back; 30 s timeout if the restart never completes
                _conn, key, _det = status
                if key != "status_running":
                    self._restart_seen_transition = True
                if (self._restart_seen_transition and key == "status_running") \
                        or (now - self._restart_started) > 30.0:
                    self._restart_pending = False
                    self._dirty.set()
            auto = self._get_auto_launch()  # cached in the controller, cheap
            if auto != self._last_auto:
                self._last_auto = auto
                self._dirty.set()
            provider = self._get_provider()  # settings save can flip it live
            if provider != self._last_provider:
                self._last_provider = provider
                self._dirty.set()
            controls = (self._get_speaker_context(), self._get_font_size(),
                        self._get_tts_gain(), self._get_mic_device(), self._get_tts_device())
            if controls != self._last_controls:
                self._last_controls = controls
                self._dirty.set()
            # events are authoritative, but resync visibility defensively
            try:
                self._visible = bool(ovl.isOverlayVisible(self._h))
            except Exception:
                pass

        self._maybe_apply_devices(now)
        if self._devices_error_until and now >= self._devices_error_until:
            self._devices_error_until = 0.0
            self._dirty.set()
        if self._context_error_until and now >= self._context_error_until:
            self._context_error_until = 0.0
            self._dirty.set()

        if self._visible and self._dirty.is_set():
            self._dirty.clear()
            self._tex.update(self._render(
                self._last_status or (False, "status_stopped", "")))
            ovl.setOverlayTexture(self._h, self._tex.vr_texture(openvr))

    def _handle_event(self, openvr, ev) -> None:
        et = ev.eventType
        if et == openvr.VREvent_MouseMove:
            self._hover_px = self._mouse_px(ev)
        elif et == openvr.VREvent_MouseButtonDown:
            if ev.data.mouse.button == openvr.VRMouseButton_Left:
                self._pressed = self._button_at(self._mouse_px(ev))
                if self._pressed is not None:
                    self._dirty.set()  # render the pressed fill
        elif et == openvr.VREvent_MouseButtonUp:
            if ev.data.mouse.button == openvr.VRMouseButton_Left:
                released_on = self._button_at(self._mouse_px(ev))
                if released_on is not None and released_on == self._pressed:
                    self._on_click(released_on)
                if self._pressed is not None:
                    self._dirty.set()
                self._pressed = None
        elif et == openvr.VREvent_OverlayShown:
            self._visible = True
            # pick up device-list changes (PortAudio reinit via Qt Refresh)
            try:
                self._dev_inputs, self._dev_outputs = self._get_devices()
            except Exception:
                pass
            self._dirty.set()
        elif et == openvr.VREvent_OverlayHidden:
            self._visible = False
            self._pressed = None
            self._close_picker()  # reopen on the main page

    @staticmethod
    def _mouse_px(ev) -> tuple[float, float]:
        x = float(ev.data.mouse.x)
        y = float(ev.data.mouse.y)
        if MOUSE_Y_BOTTOM_UP:
            y = TEX_H - y
        return x, y

    def _button_at(self, px: tuple[float, float]) -> str | None:
        x, y = px
        return widget_at(self._active_widgets(), self, x, y, self._page)

    # ---------------- language grid picker ----------------
    def label_fonts(self) -> tuple:
        return (self._font_small, self._font_tiny)

    def _open_picker(self, kind: str) -> None:
        langs = self._languages if kind == "out" else self._inbound_languages
        current = (self._state.target_language if kind == "out"
                   else self._state.inbound_language)
        per_page = PICKER_COLS * PICKER_ROWS
        self._picker_idx = (langs.index(current) // per_page
                            if current in langs else 0)
        self._page = "lang_out" if kind == "out" else "lang_in"
        self._dirty.set()

    def _close_picker(self) -> None:
        if self._page != "main":
            self._page = "main"
            self._dirty.set()

    def _flip_picker_page(self, step: int) -> None:
        langs = (self._languages if self._page == "lang_out"
                 else self._inbound_languages)
        n_pages = lang_page_count(langs, PICKER_COLS, PICKER_ROWS)
        self._picker_idx = max(0, min(self._picker_idx + step, n_pages - 1))
        self._dirty.set()

    def _active_widgets(self) -> tuple:
        if self._page in NAV_RECTS:
            return tuple(w for w in self._widgets if w.page == self._page
                         and (w.name != "speaker_context" or self._get_provider() == "soniox"))
        key = (self._page, self._picker_idx)
        cached = self._picker_cache.get(key)
        if cached is None:
            cached = self._picker_cache[key] = self._build_picker_page(*key)
        return cached

    def _build_picker_page(self, page: str, page_idx: int) -> tuple:
        out = page == "lang_out"
        langs = self._languages if out else self._inbound_languages
        n_pages = lang_page_count(langs, PICKER_COLS, PICKER_ROWS)
        widgets = [
            Widget("picker_caption", PICKER_CAPTION, kind="label", page=page,
                   fill=lambda p: (0, 0, 0, 0),
                   label=lambda p, lang, k=("out_lang" if out else "sub_lang"):
                       tr(lang, k)),
            Widget("picker_close", PICKER_CLOSE, page=page, draw=glyph_draw("×")),
        ]
        if n_pages > 1:
            widgets.append(Widget("picker_pgprev", PICKER_PGPREV, page=page,
                                  enabled=lambda p: p._picker_idx > 0,
                                  draw=glyph_draw("◀")))
            widgets.append(Widget("picker_pgnext", PICKER_PGNEXT, page=page,
                                  enabled=lambda p, n=n_pages: p._picker_idx < n - 1,
                                  draw=glyph_draw("▶")))
        widgets += lang_grid_widgets(
            page=page, languages=langs, page_idx=page_idx, area=PICKER_GRID,
            cols=PICKER_COLS, rows=PICKER_ROWS,
            name_prefix="pick_out" if out else "pick_in",
            current_of=(lambda p: p._state.target_language) if out
                       else (lambda p: p._state.inbound_language),
            accent=COL_ON if out else COL_SUB_ON)
        return tuple(widgets)

    def _enabled(self, name: str) -> bool:
        w = self._widget_by_name.get(name)
        return w is None or w.enabled is None or bool(w.enabled(self))

    def _on_click(self, button: str) -> None:
        if not any(w.name == button and w.kind == "button"
                   and (w.enabled is None or w.enabled(self)) for w in self._active_widgets()):
            return
        log.info("dashboard panel click: %s", button)
        st = self._state
        if button.startswith("nav_"):
            self._page = button.removeprefix("nav_")
            self._pressed = None
            self._dirty.set()
            return
        if button.startswith("pick_out:"):
            st.target_language = button.split(":", 1)[1]
            self._close_picker()
            return
        if button.startswith("pick_in:"):
            st.inbound_language = button.split(":", 1)[1]
            self._close_picker()
            return
        if button == "lang":
            self._open_picker("out")
        elif button == "sub_lang":
            self._open_picker("in")
        elif button == "picker_close":
            self._close_picker()
        elif button == "picker_pgprev":
            self._flip_picker_page(-1)
        elif button == "picker_pgnext":
            self._flip_picker_page(1)
        elif button == "toggle":
            st.translation_on = not st.translation_on
        elif button == "sub_toggle":
            st.subtitles_on = not st.subtitles_on
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
            if not self._restart_pending:
                self._restart_pending = True
                self._restart_started = time.time()
                self._restart_seen_transition = False
                self._on_restart()
        elif button == "reset":
            st.request_position_reset()
        elif button in ("mic_prev", "mic_next"):
            self._cycle_device("mic", 1 if button == "mic_next" else -1)
        elif button in ("out_prev", "out_next"):
            self._cycle_device("out", 1 if button == "out_next" else -1)
        elif button in ("vol_minus", "vol_plus"):
            step = 0.1 if button == "vol_plus" else -0.1
            self._on_tts_gain(float(self._get_tts_gain()) + step)
        elif button in ("src_prev", "src_next"):
            if self._get_provider() in ("qwen", "soniox"):
                st.source_language = cycle(
                    self._source_languages(self._languages), st.source_language,
                    1 if button == "src_next" else -1)
        elif button in ("insrc_prev", "insrc_next"):
            if self._get_provider() in ("qwen", "soniox"):
                st.inbound_source_language = cycle(
                    self._source_languages(self._inbound_languages), st.inbound_source_language,
                    1 if button == "insrc_next" else -1)
        elif button == "speaker_context":
            self._context_applying = True
            self._context_error_until = 0.0
            try:
                self._set_speaker_context(not self._get_speaker_context()[0], self._context_done)
            except Exception:
                log.exception("dashboard speaker context update failed")
                self._context_done(False)
        self._dirty.set()

    def _source_languages(self, languages):
        if self._get_provider() == "soniox":
            from ..languages import SONIOX_LANGUAGES, soniox_language_code
            # Soniox hints allow Auto, and only languages its model accepts.
            return [""] + list(dict.fromkeys(code for code in languages
                if soniox_language_code(code) in SONIOX_LANGUAGES))
        return languages

    def _context_done(self, ok: bool) -> None:
        self._context_error_until = 0.0 if ok else time.time() + 5.0
        self._context_applying = False
        self._dirty.set()

    # ---------------- audio device pickers ----------------
    @staticmethod
    def _resolve_device(names: list[str], value: str) -> int:
        """Index of a configured device in the picker list. '' -> 0 (the
        default entry); exact match preferred, then first substring match
        (mirrors devices.find_input/find_output); -1 = not present."""
        if not value:
            return 0
        low = value.lower()
        for i, name in enumerate(names):
            if name.lower() == low:
                return i
        for i, name in enumerate(names):
            if name and low in name.lower():
                return i
        return -1

    def _cycle_device(self, kind: str, step: int) -> None:
        if self._devices_applying:
            return  # arrows render dimmed; ignore clicks until the restart ends
        names = self._dev_inputs if kind == "mic" else self._dev_outputs
        if not names:
            return
        pending = self._pending_mic if kind == "mic" else self._pending_out
        current = pending if pending is not None else (
            self._get_mic_device() if kind == "mic" else self._get_tts_device())
        idx = self._resolve_device(names, current)
        if idx < 0:
            # configured device not in the list (unplugged / hand-edited
            # config): enter the list at either end
            new = 0 if step > 0 else len(names) - 1
        else:
            new = (idx + step) % len(names)
        if kind == "mic":
            self._pending_mic = names[new]
        else:
            self._pending_out = names[new]
        self._devices_apply_at = time.time() + DEVICE_APPLY_DELAY_SEC
        self._devices_error_until = 0.0

    def _maybe_apply_devices(self, now: float) -> None:
        if self._devices_applying or self._context_applying or self._restart_pending:
            return
        if self._pending_mic is None and self._pending_out is None:
            return
        if now < self._devices_apply_at:
            return
        # drop pendings that resolve to the already-configured device (the
        # substring config "CABLE Input" equals its full enumerated name)
        mic = self._pending_mic
        if mic is not None and self._resolve_device(self._dev_inputs, mic) == \
                self._resolve_device(self._dev_inputs, self._get_mic_device()):
            self._pending_mic = mic = None
        out = self._pending_out
        if out is not None and self._resolve_device(self._dev_outputs, out) == \
                self._resolve_device(self._dev_outputs, self._get_tts_device()):
            self._pending_out = out = None
        if mic is None and out is None:
            self._dirty.set()
            return
        log.info("dashboard panel: applying devices (mic=%r, out=%r)", mic, out)
        self._devices_applying = True
        self._dirty.set()
        self._set_audio_devices(mic, out, self._devices_done)

    def _devices_done(self, ok: bool) -> None:
        # runs on the controller worker thread: plain attribute writes only.
        # Pendings are cleared BEFORE the applying flag so an interleaved
        # tick cannot re-apply stale values.
        try:
            self._dev_inputs, self._dev_outputs = self._get_devices()
        except Exception:
            pass
        self._pending_mic = self._pending_out = None
        if not ok:
            self._devices_error_until = time.time() + 4.0
        self._devices_applying = False
        self._dirty.set()

    # ---------------- rendering ----------------
    def _fill_for(self, name: str | None, base=COL_BTN):
        """Pressed feedback: darken the base fill while the mouse is down on
        this widget (SteamVR delivers no hover state worth rendering)."""
        if name is not None and self._pressed == name:
            return theme.darken(base)
        return base

    def _btn(self, d, box, text: str, *, fill=COL_BTN, fonts=None, text_fill=COL_TEXT,
             radius: int = 16, name: str | None = None) -> None:
        d.rounded_rectangle(box, radius, fill=self._fill_for(name, fill))
        draw_fit_text(d, box, text,
                      fonts=fonts or (self._font_small, self._font_tiny),
                      fill=text_fill, max_lines=1, pad_x=8, pad_y=4)

    def _device_block(self, d, lang, prev_box, label_box, next_box,
                      names, cfg_value, pending, caption: str,
                      prev_name: str = None, next_name: str = None) -> None:
        for box, glyph, name in ((prev_box, "◀", prev_name),
                                 (next_box, "▶", next_name)):
            d.rounded_rectangle(box, 16, fill=self._fill_for(name))
            self._font_mid.draw(d, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2),
                                glyph, fill=COL_TEXT if self._enabled(name) else COL_DIM, anchor="mm")
        d.rounded_rectangle(label_box, 16, fill=COL_INSET)
        value = pending if pending is not None else cfg_value
        idx = self._resolve_device(names, value)
        if idx == 0:
            name, name_fill = tr(lang, "default_device"), COL_TEXT
        elif idx > 0:
            name, name_fill = names[idx], COL_TEXT
        else:
            name, name_fill = value, COL_WARN  # configured device not present
        if pending is not None and not self._devices_applying:
            name_fill = COL_PENDING  # selected, applies after the click pause
        draw_fit_text(d, (label_box[0] + 8, label_box[1] + 8,
                          label_box[2] - 8, label_box[3] - 40),
                      name, fonts=(self._font_small, self._font_tiny),
                      fill=name_fill, max_lines=1, pad_x=4, pad_y=2)
        if self._devices_applying:
            cap, cap_fill = tr(lang, "dash_applying"), COL_PENDING
        elif time.time() < self._devices_error_until:
            cap, cap_fill = tr(lang, "dash_apply_failed"), COL_ERR
        else:
            cap, cap_fill = caption, COL_DIM
        draw_fit_text(d, (label_box[0] + 8, label_box[3] - 36,
                          label_box[2] - 8, label_box[3] - 8),
                      cap, fonts=(self._font_tiny,), fill=cap_fill, max_lines=1,
                      pad_x=4, pad_y=1, line_spacing=0)

    def _caption(self, d, box, text, *, fill=COL_DIM, large=False):
        draw_fit_text(d, box, text,
                      fonts=(self._font_mid, self._font_small) if large
                      else (self._font_small, self._font_tiny),
                      fill=fill, max_lines=2, pad_x=8, pad_y=4)

    def _value_button(self, d, box, value, caption, name, *, fill=COL_INSET):
        self._btn(d, box, "", fill=fill, name=name)
        x0, y0, x1, y1 = box
        self._caption(d, (x0 + 8, y0 + 10, x1 - 8, y1 - 44), value,
                      fill=COL_TEXT, large=True)
        self._caption(d, (x0 + 8, y1 - 42, x1 - 8, y1 - 8), caption)

    def _render(self, info: tuple) -> Image.Image:
        connected, status_key, _detail = info
        st, lang = self._state, self._state.ui_lang
        img = Image.new("RGBA", (TEX_W, TEX_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, TEX_W - 1, TEX_H - 1), 28, fill=COL_BG)
        if self._page.startswith("lang_"):
            draw_page(self, d, self._active_widgets(), lang,
                      page=self._page, pressed=self._pressed)
            return img
        dot = status_dot_color(connected, status_key)
        d.ellipse(STATUS_DOT, fill=dot)
        self._font_small.draw(d, (64, 44), f"VRCLT v{__version__}",
                              fill=COL_TEXT, anchor="lm")
        self._caption(d, (336, 20, 524, 76),
                      {"gemini": "Gemini", "qwen": "Qwen", "openai": "OpenAI",
                       "soniox": "Soniox"}.get(self._get_provider(), self._get_provider()),
                      fill=COL_SUB_ON)
        self._caption(d, STATUS_TEXT_BOX, tr(lang, status_key), fill=dot)
        for page, rect in NAV_RECTS.items():
            self._btn(d, rect, tr(lang, NAV_KEYS[page]),
                      fill=COL_SUB_ON if page == self._page else COL_BTN,
                      name="nav_" + page)
        if self._page == "audio":
            self._render_audio(d, lang)
        elif self._page == "layout":
            self._render_layout(d, lang)
        else:
            self._render_live(d, lang)
        return img

    def _render_live(self, d, lang):
        st = self._state
        for box, caption, accent in (
                ((24, 210, 500, 704), "my_to_other", COL_ON),
                ((524, 210, 1000, 704), "other_to_sub", COL_SUB_ON)):
            d.rounded_rectangle(box, 20, fill=COL_INSET)
            self._caption(d, (box[0]+12, 222, box[2]-12, 270),
                          tr(lang, caption), fill=accent)
        self._btn(d, BTN_TOGGLE, tr(lang, "btn_trans_on" if st.translation_on else "btn_trans_off"),
                  fill=COL_ON if st.translation_on else COL_OFF,
                  fonts=(self._font_mid, self._font_small), name="toggle")
        self._btn(d, BTN_SUB_TOGGLE, tr(lang, "btn_sub_on" if st.subtitles_on else "btn_sub_off"),
                  fill=COL_SUB_ON if st.subtitles_on else COL_BTN,
                  fonts=(self._font_mid, self._font_small), name="sub_toggle")
        self._value_button(d, BTN_LANG, language_label(st.target_language),
                           tr(lang, "out_lang"), "lang", fill=COL_BTN)
        self._value_button(d, BTN_SUB_LANG, language_label(st.inbound_language),
                           tr(lang, "sub_lang"), "sub_lang", fill=COL_BTN)
        for prev, label, next_, code, caption, prefix in (
                (BTN_SRC_PREV, LBL_SRC_LANG, BTN_SRC_NEXT, st.source_language,
                 "dash_src_out", "src"),
                (BTN_INSRC_PREV, LBL_INSRC_LANG, BTN_INSRC_NEXT, st.inbound_source_language,
                 "dash_src_in", "insrc")):
            if self._get_provider() in ("qwen", "soniox"):
                self._btn(d, prev, "◀", fonts=(self._font_mid,), name=prefix+"_prev")
                self._btn(d, next_, "▶", fonts=(self._font_mid,), name=prefix+"_next")
                value = (tr(lang, "vr_auto_language") if not code and self._get_provider() == "soniox"
                         else language_label(code or "en"))
                self._value_button(d, label, value, tr(lang, caption), None)
            else:
                self._value_button(d, (prev[0], prev[1], next_[2], next_[3]),
                                   tr(lang, "vr_auto_language"), tr(lang, caption), None)
        if self._get_provider() == "soniox":
            keep, seconds = self._get_speaker_context()
            self._btn(d, BTN_SPEAKER_CONTEXT,
                      tr(lang, "dash_applying" if self._context_applying else
                         "vr_speaker_context_on" if keep else "vr_speaker_context_off"),
                      fill=COL_SUB_ON if keep else COL_BTN,
                      text_fill=COL_TEXT if self._enabled("speaker_context") else COL_DIM,
                      name="speaker_context")
            self._caption(d, CONTEXT_NOTE_BOX,
                          tr(lang, "soniox_idle_timeout_status").format(seconds=f"{seconds:g}")
                          if seconds > 0 else tr(lang, "soniox_idle_timeout_disabled"))
        note = ("msg_saved_start_failed" if time.time() < self._context_error_until
                else "vr_hint_languages")
        self._caption(d, (24, 860, 1000, 926), tr(lang, note))

    def _render_audio(self, d, lang):
        self._caption(d, (24, 214, 1000, 256), tr(lang, "grp_dev"))
        self._device_block(d, lang, BTN_MIC_PREV, LBL_MIC_DEVICE, BTN_MIC_NEXT,
                           self._dev_inputs, self._get_mic_device(), self._pending_mic,
                           tr(lang, "f.outbound.mic_device"), "mic_prev", "mic_next")
        self._device_block(d, lang, BTN_OUT_PREV, LBL_OUT_DEVICE, BTN_OUT_NEXT,
                           self._dev_outputs, self._get_tts_device(), self._pending_out,
                           tr(lang, "f.outbound.tts_device"), "out_prev", "out_next")
        for name, box, glyph in (("vol_minus", BTN_VOL_MINUS, "−"),
                                 ("vol_plus", BTN_VOL_PLUS, "+")):
            self._btn(d, box, glyph, fonts=(self._font_mid,), name=name,
                      text_fill=COL_TEXT if self._enabled(name) else COL_DIM)
        self._value_button(d, LBL_VOL_GAIN, f"{round(float(self._get_tts_gain())*100)}%",
                           tr(lang, "dash_voice_volume"), None)
        self._btn(d, BTN_TEXT_ONLY,
                  tr(lang, "btn_text_only_on" if self._state.text_only else "btn_text_only_off"),
                  fill=COL_SUB_ON if self._state.text_only else COL_BTN, name="text_only",
                  text_fill=COL_TEXT if self._enabled("text_only") else COL_DIM)
        note = "dash_applying" if self._devices_applying else "vr_hint_audio_apply"
        self._caption(d, (24, 874, 1000, 932), tr(lang, note))

    def _render_layout(self, d, lang):
        self._caption(d, (24, 210, 1000, 250), tr(lang, "vr_section_subtitles"))
        for name, box, glyph in (("font_minus", BTN_FONT_MINUS, "−"),
                                 ("font_plus", BTN_FONT_PLUS, "+")):
            self._btn(d, box, glyph, fonts=(self._font_mid,), name=name,
                      text_fill=COL_TEXT if self._enabled(name) else COL_DIM)
        self._value_button(d, LBL_FONT_SIZE, str(int(self._get_font_size())),
                           tr(lang, "dash_font_size"), None)
        self._caption(d, (24, 386, 1000, 426), tr(lang, "vr_section_position"))
        self._btn(d, BTN_SUB_EDIT, tr(lang, "vr_move_subtitles"),
                  fill=COL_DRAG if self._state.edit_mode else COL_BTN, name="sub_edit")
        self._btn(d, BTN_WRIST_EDIT, tr(lang, "vr_move_wrist"),
                  fill=COL_DRAG if self._state.wrist_edit_mode else COL_BTN, name="wrist_edit")
        self._btn(d, BTN_RESET, tr(lang, "vr_reset_positions"), name="reset")
        self._caption(d, (24, 666, 1000, 712), tr(lang, "vr_section_app"))
        self._btn(d, BTN_UILANG, UI_LANG_LABELS.get(lang, lang), name="uilang")
        auto = self._get_auto_launch()
        self._btn(d, BTN_AUTOSTART, tr(lang, "btn_autostart_on" if auto else "btn_autostart_off"),
                  fill=COL_SUB_ON if auto else COL_BTN, name="autostart",
                  text_fill=COL_TEXT if auto is not None else COL_DIM)
        self._btn(d, BTN_RESTART, tr(lang, "btn_restarting" if self._restart_pending else "btn_restart_runtime"),
                  name="restart", text_fill=COL_TEXT if self._enabled("restart") else COL_DIM)
        self._caption(d, (24, 856, 1000, 926), tr(lang, "vr_hint_position"))
