"""SteamVR dashboard settings panel (component of the VR render thread).

Lives in the SteamVR dashboard (system-menu overlay bar). Unlike the wrist
menu it needs no laser/cursor/gaze machinery: SteamVR shows its own pointer
and delivers overlay mouse events (pollNextOverlayEvent), and the dashboard
also controls placement, so there is no transform handling either.

Texture is a persistent OpenGL texture (see vr/render.py for why).
"""
import logging
import threading
import time

from PIL import Image, ImageDraw

from .. import __version__
from ..config import APPDATA_DIR, OVERLAY_FONT_MAX, OVERLAY_FONT_MIN
from ..i18n import tr, LANGS as UI_LANGS, UI_LANG_LABELS
from .button_table import Widget, widget_at
from ..resources import bundled_font, resolve_font_path
from ..state import AppState
from .font_fallback import load_fallback_font
from .panel_common import (
    COL_BG, COL_BTN, COL_DIM, COL_DRAG, COL_INSET, COL_ON, COL_OFF,
    COL_PENDING, COL_SUB_ON, COL_TEXT,
    COL_ERR_RED as COL_ERR, COL_WARN_AMBER as COL_WARN,
    cycle, draw_fit_text, lang_block, status_dot_color,
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

STATUS_TEXT_BOX = (280, 18, 548, 70)  # header band between version and buttons

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
# devices row (mic / voice output pickers)
BTN_MIC_PREV = (16, 546, 80, 642)
LBL_MIC_DEVICE = (88, 546, 424, 642)   # label only
BTN_MIC_NEXT = (432, 546, 496, 642)
BTN_OUT_PREV = (528, 546, 592, 642)
LBL_OUT_DEVICE = (600, 546, 936, 642)  # label only
BTN_OUT_NEXT = (944, 546, 1008, 642)
# bottom row
BTN_TEXT_ONLY = (16, 662, 240, 740)
BTN_FONT_MINUS = (264, 662, 344, 740)
LBL_FONT_SIZE = (352, 662, 452, 740)  # label only
BTN_FONT_PLUS = (460, 662, 540, 740)
BTN_SUB_EDIT = (564, 662, 724, 740)
BTN_WRIST_EDIT = (748, 662, 908, 740)
BTN_RESET = (924, 662, 1008, 740)
# volume row (translated-voice gain)
BTN_VOL_MINUS = (16, 760, 96, 838)
LBL_VOL_GAIN = (104, 760, 244, 838)   # label only
BTN_VOL_PLUS = (252, 760, 332, 838)
# source-language row (Qwen has no auto-detect; Gemini renders a dim note
# instead and the buttons are click-gated by provider)
BTN_SRC_PREV = (16, 858, 80, 936)
LBL_SRC_LANG = (88, 858, 424, 936)     # label only
BTN_SRC_NEXT = (432, 858, 496, 936)
BTN_INSRC_PREV = (528, 858, 592, 936)
LBL_INSRC_LANG = (600, 858, 936, 936)  # label only
BTN_INSRC_NEXT = (944, 858, 1008, 936)
SRC_ROW_BOX = (16, 858, 1008, 936)     # gemini-mode note area

# TTS gain clamp (mirrors app_controller.set_tts_gain)
GAIN_MIN, GAIN_MAX = 0.0, 2.0


def _build_widgets() -> tuple:
    """Hit-test + enabled table. Rendering stays in _render (SteamVR mouse
    events, no hover), but disabled widgets are dead to clicks here and
    rendered dim there via the same `enabled` functions."""
    _qwen = lambda p: p._get_provider() == "qwen"
    _devices_free = lambda p: not p._devices_applying
    return (
        Widget("toggle", BTN_TOGGLE), Widget("prev", BTN_PREV),
        Widget("next", BTN_NEXT),
        Widget("sub_toggle", BTN_SUB_TOGGLE), Widget("sub_prev", BTN_SUB_PREV),
        Widget("sub_next", BTN_SUB_NEXT), Widget("text_only", BTN_TEXT_ONLY),
        Widget("font_minus", BTN_FONT_MINUS,
               enabled=lambda p: int(p._get_font_size()) > OVERLAY_FONT_MIN),
        Widget("font_plus", BTN_FONT_PLUS,
               enabled=lambda p: int(p._get_font_size()) < OVERLAY_FONT_MAX),
        Widget("sub_edit", BTN_SUB_EDIT), Widget("wrist_edit", BTN_WRIST_EDIT),
        Widget("reset", BTN_RESET), Widget("uilang", BTN_UILANG),
        Widget("autostart", BTN_AUTOSTART,
               enabled=lambda p: p._get_auto_launch() is not None),
        Widget("restart", BTN_RESTART,
               enabled=lambda p: not p._restart_pending),
        Widget("mic_prev", BTN_MIC_PREV, enabled=_devices_free),
        Widget("mic_next", BTN_MIC_NEXT, enabled=_devices_free),
        Widget("out_prev", BTN_OUT_PREV, enabled=_devices_free),
        Widget("out_next", BTN_OUT_NEXT, enabled=_devices_free),
        Widget("vol_minus", BTN_VOL_MINUS,
               enabled=lambda p: float(p._get_tts_gain()) > GAIN_MIN),
        Widget("vol_plus", BTN_VOL_PLUS,
               enabled=lambda p: float(p._get_tts_gain()) < GAIN_MAX),
        Widget("src_prev", BTN_SRC_PREV, enabled=_qwen),
        Widget("src_next", BTN_SRC_NEXT, enabled=_qwen),
        Widget("insrc_prev", BTN_INSRC_PREV, enabled=_qwen),
        Widget("insrc_next", BTN_INSRC_NEXT, enabled=_qwen),
    )


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
                 get_provider=lambda: "gemini"):
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
        self._restart_pending = False

        font_path = resolve_font_path(font_path, "NotoSansCJKkr-Bold.otf")
        self._font_big = load_fallback_font(font_path, 64, bold=True)
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
            auto = self._get_auto_launch()  # cached in the controller, cheap
            if auto != self._last_auto:
                self._last_auto = auto
                self._dirty.set()
            provider = self._get_provider()  # settings save can flip it live
            if provider != self._last_provider:
                self._last_provider = provider
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
        elif et == openvr.VREvent_MouseButtonUp:
            if ev.data.mouse.button == openvr.VRMouseButton_Left:
                released_on = self._button_at(self._mouse_px(ev))
                if released_on is not None and released_on == self._pressed:
                    self._on_click(released_on)
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

    @staticmethod
    def _mouse_px(ev) -> tuple[float, float]:
        x = float(ev.data.mouse.x)
        y = float(ev.data.mouse.y)
        if MOUSE_Y_BOTTOM_UP:
            y = TEX_H - y
        return x, y

    def _button_at(self, px: tuple[float, float]) -> str | None:
        x, y = px
        return widget_at(self._widgets, self, x, y, self._page)

    def _enabled(self, name: str) -> bool:
        w = self._widget_by_name.get(name)
        return w is None or w.enabled is None or bool(w.enabled(self))

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
        elif button in ("mic_prev", "mic_next"):
            self._cycle_device("mic", 1 if button == "mic_next" else -1)
        elif button in ("out_prev", "out_next"):
            self._cycle_device("out", 1 if button == "out_next" else -1)
        elif button in ("vol_minus", "vol_plus"):
            step = 0.1 if button == "vol_plus" else -0.1
            self._on_tts_gain(float(self._get_tts_gain()) + step)
        elif button in ("src_prev", "src_next"):
            if self._get_provider() == "qwen":  # row is a dim note otherwise
                st.source_language = cycle(
                    self._languages, st.source_language,
                    1 if button == "src_next" else -1)
        elif button in ("insrc_prev", "insrc_next"):
            if self._get_provider() == "qwen":
                st.inbound_source_language = cycle(
                    self._inbound_languages, st.inbound_source_language,
                    1 if button == "insrc_next" else -1)

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
        if self._devices_applying:
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
    def _btn(self, d, box, text: str, *, fill=COL_BTN, fonts=None, text_fill=COL_TEXT,
             radius: int = 16) -> None:
        d.rounded_rectangle(box, radius, fill=fill)
        draw_fit_text(d, box, text,
                      fonts=fonts or (self._font_small, self._font_tiny),
                      fill=text_fill, max_lines=1, pad_x=8, pad_y=4)

    def _lang_block(self, d, prev_box, lang_box, next_box, code: str,
                    caption: str) -> None:
        lang_block(d, prev_box, lang_box, next_box, code, caption,
                   fonts=(self._font_big, self._font_mid, self._font_small,
                          self._font_tiny),
                   arrow_font=self._font_mid, x_inset=6,
                   label_top=26, label_bottom=66,
                   caption_top=62, caption_bottom=12,
                   label_pad=(4, 2), caption_pad=(4, 2))

    def _device_block(self, d, lang, prev_box, label_box, next_box,
                      names, cfg_value, pending, caption: str) -> None:
        arrow_fill = COL_DIM if self._devices_applying else COL_TEXT
        for box, glyph in ((prev_box, "◀"), (next_box, "▶")):
            d.rounded_rectangle(box, 16, fill=COL_BTN)
            self._font_mid.draw(d, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2),
                                glyph, fill=arrow_fill, anchor="mm")
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

    def _render(self, info: tuple) -> Image.Image:
        connected, status_key, _detail = info
        st = self._state
        lang = st.ui_lang
        img = Image.new("RGBA", (TEX_W, TEX_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, TEX_W - 1, TEX_H - 1), 28, fill=COL_BG)

        # header: status dot + version + (only when non-nominal) status text
        dot = status_dot_color(connected, status_key)
        d.ellipse(STATUS_DOT, fill=dot)
        self._font_small.draw(d, (72, (STATUS_DOT[1] + STATUS_DOT[3]) // 2),
                              f"vrclt v{__version__}", fill=COL_TEXT, anchor="lm")
        if status_key != "status_running":
            draw_fit_text(d, STATUS_TEXT_BOX, tr(lang, status_key),
                          fonts=(self._font_small, self._font_tiny),
                          fill=dot, max_lines=1, pad_x=4, pad_y=2)
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
        self._lang_block(d, BTN_PREV, BTN_LANG, BTN_NEXT,
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
        self._lang_block(d, BTN_SUB_PREV, BTN_SUB_LANG, BTN_SUB_NEXT,
                         st.inbound_language, tr(lang, "sub_lang"))

        # devices row
        self._device_block(d, lang, BTN_MIC_PREV, LBL_MIC_DEVICE, BTN_MIC_NEXT,
                           self._dev_inputs, self._get_mic_device(),
                           self._pending_mic, tr(lang, "label_mic_device"))
        self._device_block(d, lang, BTN_OUT_PREV, LBL_OUT_DEVICE, BTN_OUT_NEXT,
                           self._dev_outputs, self._get_tts_device(),
                           self._pending_out, tr(lang, "label_voice_out_device"))

        # bottom row
        text_only = st.text_only
        self._btn(d, BTN_TEXT_ONLY,
                  tr(lang, "btn_text_only_on" if text_only else "btn_text_only_off"),
                  fill=COL_SUB_ON if text_only else COL_BTN)
        self._btn(d, BTN_FONT_MINUS, "−", fonts=(self._font_mid,),
                  text_fill=COL_TEXT if self._enabled("font_minus") else COL_DIM)
        d.rounded_rectangle(LBL_FONT_SIZE, 16, fill=COL_INSET)
        draw_fit_text(d, (LBL_FONT_SIZE[0], LBL_FONT_SIZE[1] + 6,
                          LBL_FONT_SIZE[2], LBL_FONT_SIZE[1] + 46),
                      str(int(self._get_font_size())),
                      fonts=(self._font_small,), max_lines=1, pad_x=4, pad_y=2)
        draw_fit_text(d, (LBL_FONT_SIZE[0], LBL_FONT_SIZE[3] - 34,
                          LBL_FONT_SIZE[2], LBL_FONT_SIZE[3] - 6),
                      tr(lang, "dash_font_size"),
                      fonts=(self._font_tiny,), fill=COL_DIM, max_lines=1,
                      pad_x=2, pad_y=1, line_spacing=0)
        self._btn(d, BTN_FONT_PLUS, "+", fonts=(self._font_mid,),
                  text_fill=COL_TEXT if self._enabled("font_plus") else COL_DIM)
        self._btn(d, BTN_SUB_EDIT, tr(lang, "sub_move"),
                  fill=COL_DRAG if st.edit_mode else COL_BTN)
        self._btn(d, BTN_WRIST_EDIT, tr(lang, "wrist_move"),
                  fill=COL_DRAG if st.wrist_edit_mode else COL_BTN)
        self._btn(d, BTN_RESET, tr(lang, "pos_reset"))

        # volume row (mirrors the font-size triple)
        self._btn(d, BTN_VOL_MINUS, "−", fonts=(self._font_mid,),
                  text_fill=COL_TEXT if self._enabled("vol_minus") else COL_DIM)
        d.rounded_rectangle(LBL_VOL_GAIN, 16, fill=COL_INSET)
        draw_fit_text(d, (LBL_VOL_GAIN[0], LBL_VOL_GAIN[1] + 6,
                          LBL_VOL_GAIN[2], LBL_VOL_GAIN[1] + 46),
                      f"{round(float(self._get_tts_gain()) * 100)}%",
                      fonts=(self._font_small,), max_lines=1, pad_x=4, pad_y=2)
        draw_fit_text(d, (LBL_VOL_GAIN[0], LBL_VOL_GAIN[3] - 34,
                          LBL_VOL_GAIN[2], LBL_VOL_GAIN[3] - 6),
                      tr(lang, "dash_voice_volume"),
                      fonts=(self._font_tiny,), fill=COL_DIM, max_lines=1,
                      pad_x=2, pad_y=1, line_spacing=0)
        self._btn(d, BTN_VOL_PLUS, "+", fonts=(self._font_mid,),
                  text_fill=COL_TEXT if self._enabled("vol_plus") else COL_DIM)

        # source-language row (Qwen only; Gemini auto-detects)
        if self._get_provider() == "qwen":
            self._source_block(d, BTN_SRC_PREV, LBL_SRC_LANG, BTN_SRC_NEXT,
                               st.source_language, tr(lang, "dash_src_out"))
            self._source_block(d, BTN_INSRC_PREV, LBL_INSRC_LANG, BTN_INSRC_NEXT,
                               st.inbound_source_language,
                               tr(lang, "dash_src_in"))
        else:
            d.rounded_rectangle(SRC_ROW_BOX, 16, fill=COL_INSET)
            draw_fit_text(d, (SRC_ROW_BOX[0] + 12, SRC_ROW_BOX[1] + 8,
                              SRC_ROW_BOX[2] - 12, SRC_ROW_BOX[3] - 8),
                          tr(lang, "dash_src_auto"),
                          fonts=(self._font_small, self._font_tiny),
                          fill=COL_DIM, max_lines=1, pad_x=4, pad_y=2)
        return img

    def _source_block(self, d, prev_box, lang_box, next_box, code: str,
                      caption: str) -> None:
        lang_block(d, prev_box, lang_box, next_box, code or "—", caption,
                   fonts=(self._font_mid, self._font_small, self._font_tiny),
                   arrow_font=self._font_mid, x_inset=6,
                   label_top=4, label_bottom=36,
                   caption_top=34, caption_bottom=6,
                   label_pad=(4, 1), caption_pad=(4, 1))
