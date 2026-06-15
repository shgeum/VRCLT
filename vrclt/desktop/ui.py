"""Desktop (non-VR / PC mode) UI: always-on-top subtitle window + control bar.

Used for PC VRChat when SteamVR isn't running. Shares the same AppState and
SubtitleStore as the VR overlays, so every control stays in sync regardless
of mode. tkinter runs on its own thread and is only touched from that thread:
AppState/SubtitleStore are POLLED every 100 ms, and control widgets push back
into AppState (which is thread-safe). Both windows are draggable and remember
their position in %LOCALAPPDATA%/vrclt/desktop_layout.json.
"""
import ctypes
import json
import logging
import os
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from ..state import AppState
from ..subtitles import SubtitleStore
from ..i18n import tr, LANGS as UI_LANGS, UI_LANG_LABELS

log = logging.getLogger(__name__)

LAYOUT_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "vrclt" / "desktop_layout.json"

LANG_LABELS = {
    "ja": "日本語", "en": "English", "ko": "한국어",
    "zh-Hans": "中文(简)", "zh-Hant": "中文(繁)", "yue": "廣東話",
    "es": "Español", "ru": "Русский", "fr": "Français", "de": "Deutsch",
}


def _uilabel_to_code(label: str) -> str:
    for c in UI_LANGS:
        if UI_LANG_LABELS[c] == label:
            return c
    return "en"

BG = "#12141a"
PANEL = "#1c1f29"
FG = "#f0f0f0"
DIM = "#9aa0ad"
ON_COL = "#2ea043"
OFF_COL = "#78541e"
SUB_COL = "#2870aa"
ACCENT = "#4a6eb4"
CHROMA = "#010203"  # transparent color key for the subtitle window


def _label_to_code(label: str, codes: list[str]) -> str:
    for c in codes:
        if LANG_LABELS.get(c, c) == label:
            return c
    return codes[0] if codes else label


class DesktopUI:
    def __init__(self, state: AppState, store: SubtitleStore, *,
                 out_languages: list[str], sub_languages: list[str],
                 get_status=lambda: False, font_size: int = 30,
                 opacity: float = 0.85, width: int = 900,
                 show_source: bool = False, lines: int = 3):
        self._state = state
        self._store = store
        self._out_langs = out_languages or ["en"]
        self._sub_langs = sub_languages or ["ko"]
        self._get_status = get_status
        self._font_size = font_size
        self._opacity = max(0.2, min(1.0, opacity))
        self._width = width
        self._show_source = show_source
        self._lines = lines

        self._stopping = False
        self._root: tk.Tk | None = None
        self._sub_win = None
        self._ctl_win = None
        self._last_sub_text = None
        self._last_status = None
        self._last_edit = None
        self._last_uilang = None

    # ---------------- lifecycle ----------------
    def run_blocking(self) -> None:
        """Run the tkinter UI on the CALLING thread (must be the main thread -
        tkinter is not thread-safe). Returns when the windows are closed via
        the ✕ button, request_stop(), or Ctrl+C."""
        try:
            root = tk.Tk()
        except Exception:
            log.exception("desktop UI: tkinter init failed")
            return
        self._root = root
        root.withdraw()
        layout = self._load_layout()
        try:
            self._build_subtitle_window(root, layout)
            self._build_control_window(root, layout)
        except Exception:
            log.exception("desktop UI: failed to build windows")
            return
        log.info("desktop UI running (always-on-top subtitle window + control bar)")
        root.after(100, self._poll)
        try:
            root.mainloop()
        except KeyboardInterrupt:
            pass
        except Exception:
            log.exception("desktop UI mainloop crashed")

    def request_stop(self) -> None:
        """Ask the UI to close (safe to call from any thread)."""
        self._stopping = True

    # ---------------- subtitle window ----------------
    def _build_subtitle_window(self, root: tk.Tk, layout: dict) -> None:
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", self._opacity)
        win.configure(bg=BG)
        h = int(self._font_size * (self._lines + 1) * 1.8)
        pos = layout.get("subtitle", {})
        x = pos.get("x", 200)
        y = pos.get("y", 700)
        win.geometry(f"{self._width}x{h}+{x}+{y}")

        font = tkfont.Font(family="Malgun Gothic", size=self._font_size, weight="bold")
        lbl = tk.Label(win, text="", font=font, fg=FG, bg=BG, wraplength=self._width - 40,
                       justify="center", anchor="s")
        lbl.pack(fill="both", expand=True, padx=16, pady=10)
        self._make_draggable(win, lbl, "subtitle")
        self._sub_win = win
        self._sub_label = lbl
        win.withdraw()  # shown when there is content
        # Discord-style overlay: click-through + no focus steal, so it floats
        # over the game without blocking input (toggled off in edit mode)
        self._apply_overlay_style(win, click_through=True)

    # ---------------- control window ----------------
    def _build_control_window(self, root: tk.Tk, layout: dict) -> None:
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=PANEL)
        pos = layout.get("control", {})
        x = pos.get("x", 60)
        y = pos.get("y", 60)
        win.geometry(f"+{x}+{y}")

        bar = tk.Frame(win, bg=PANEL)
        bar.pack(padx=10, pady=8)

        # drag handle / title + status dot
        head = tk.Frame(bar, bg=PANEL)
        head.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        self._status_dot = tk.Canvas(head, width=14, height=14, bg=PANEL, highlightthickness=0)
        self._status_dot.pack(side="left")
        self._dot_id = self._status_dot.create_oval(2, 2, 12, 12, fill=DIM, outline="")
        tk.Label(head, text=" vrclt", font=("Malgun Gothic", 9),
                 fg=DIM, bg=PANEL).pack(side="left")
        lang = self._state.ui_lang
        # "이동" toggles edit mode: subtitle becomes grabbable (not click-through)
        self._btn_move = tk.Button(head, text=tr(lang, "sub_move"), relief="flat", fg=DIM, bg=PANEL,
                                   activebackground=ACCENT, font=("Malgun Gothic", 9),
                                   command=self._toggle_edit)
        self._btn_move.pack(side="left", padx=(8, 0))
        # UI display-language picker
        self._uilang_var = tk.StringVar(win)
        self._uilang_menu = tk.OptionMenu(
            head, self._uilang_var, *[UI_LANG_LABELS[c] for c in UI_LANGS],
            command=self._pick_ui_lang)
        self._uilang_menu.configure(relief="flat", fg=DIM, bg=PANEL, activebackground=ACCENT,
                                    highlightthickness=0, font=("Malgun Gothic", 9))
        self._uilang_menu["menu"].configure(bg=BG, fg=FG)
        self._uilang_menu.pack(side="left", padx=(4, 0))
        self._make_draggable(win, head, "control")

        # translation toggle + output language
        self._btn_trans = tk.Button(bar, text="번역 ON", width=10, relief="flat",
                                    fg=FG, bg=ON_COL, activebackground=ON_COL,
                                    font=("Malgun Gothic", 10, "bold"),
                                    command=self._toggle_translation)
        self._btn_trans.grid(row=1, column=0, padx=3, pady=3)
        self._out_var = tk.StringVar(win)
        self._out_menu = tk.OptionMenu(
            bar, self._out_var, *[LANG_LABELS.get(c, c) for c in self._out_langs],
            command=self._pick_out_lang)
        self._out_menu.configure(width=8, relief="flat", fg=FG, bg=BG,
                                 activebackground=ACCENT, highlightthickness=0,
                                 font=("Malgun Gothic", 9))
        self._out_menu["menu"].configure(bg=BG, fg=FG)
        self._out_menu.grid(row=1, column=1, padx=3, pady=3)

        # subtitle toggle + subtitle language
        self._btn_sub = tk.Button(bar, text="자막 ON", width=10, relief="flat",
                                  fg=FG, bg=SUB_COL, activebackground=SUB_COL,
                                  font=("Malgun Gothic", 10, "bold"),
                                  command=self._toggle_subtitles)
        self._btn_sub.grid(row=1, column=2, padx=3, pady=3)
        self._sub_var = tk.StringVar(win)
        self._sub_menu = tk.OptionMenu(
            bar, self._sub_var, *[LANG_LABELS.get(c, c) for c in self._sub_langs],
            command=self._pick_sub_lang)
        self._sub_menu.configure(width=8, relief="flat", fg=FG, bg=BG,
                                 activebackground=ACCENT, highlightthickness=0,
                                 font=("Malgun Gothic", 9))
        self._sub_menu["menu"].configure(bg=BG, fg=FG)
        self._sub_menu.grid(row=1, column=3, padx=3, pady=3)

        # close button
        tk.Button(bar, text="✕", width=2, relief="flat", fg=DIM, bg=PANEL,
                  activebackground="#aa3333", font=("Malgun Gothic", 9),
                  command=self._request_quit).grid(row=0, column=3, sticky="e")
        self._ctl_win = win

    # ---------------- control callbacks ----------------
    def _apply_overlay_style(self, win, click_through: bool) -> None:
        """Layered + no-activate (Discord-style); + transparent = click-through."""
        try:
            win.update_idletasks()
            u = ctypes.windll.user32
            hwnd = u.GetParent(win.winfo_id()) or win.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            if click_through:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            u.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            log.debug("overlay style apply failed", exc_info=True)

    def _toggle_edit(self) -> None:
        self._state.edit_mode = not self._state.edit_mode

    def _toggle_translation(self) -> None:
        self._state.translation_on = not self._state.translation_on

    def _toggle_subtitles(self) -> None:
        self._state.subtitles_on = not self._state.subtitles_on

    def _pick_out_lang(self, label: str) -> None:
        self._state.target_language = _label_to_code(label, self._out_langs)

    def _pick_sub_lang(self, label: str) -> None:
        self._state.inbound_language = _label_to_code(label, self._sub_langs)

    def _pick_ui_lang(self, label: str) -> None:
        self._state.ui_lang = _uilabel_to_code(label)

    def _request_quit(self) -> None:
        self._stopping = True

    # ---------------- polling ----------------
    def _poll(self) -> None:
        root = self._root
        if root is None:
            return
        if self._stopping:
            self._save_layout()
            try:
                root.destroy()
            except Exception:
                pass
            return
        try:
            self._refresh()
        except Exception:
            log.debug("desktop UI refresh error", exc_info=True)
        root.after(100, self._poll)

    def _refresh(self) -> None:
        st = self._state
        lang = st.ui_lang
        edit = st.edit_mode
        # edit mode: subtitle becomes grabbable (not click-through) + bordered,
        # and stays visible (placeholder) so it can be positioned over the game
        if edit != self._last_edit or lang != self._last_uilang:
            self._last_edit = edit
            self._apply_overlay_style(self._sub_win, click_through=not edit)
            self._sub_win.configure(highlightthickness=3 if edit else 0,
                                    highlightbackground=ACCENT, highlightcolor=ACCENT)
            self._btn_move.configure(text=tr(lang, "edit_done" if edit else "sub_move"),
                                     bg=ACCENT if edit else PANEL)

        # subtitle content
        text = ""
        if st.subtitles_on:
            finals, partial = self._store.snapshot()
            rows = []
            for src, dst, _lang in finals[-self._lines:]:
                if self._show_source and src:
                    rows.append(src)
                rows.append(dst or src)
            p_src, p_dst = partial
            if p_dst or p_src:
                rows.append(p_dst or p_src)
            text = "\n".join(rows[-(self._lines + 1):])
        show_text = text or (tr(lang, "sub_placeholder") if edit else "")
        if show_text != self._last_sub_text:
            self._last_sub_text = show_text
            self._sub_label.configure(text=show_text)
            if show_text:
                self._sub_win.deiconify()
            else:
                self._sub_win.withdraw()

        # translation button
        trans_on = st.translation_on
        connected = bool(self._get_status())
        self._btn_trans.configure(
            text=tr(lang, "btn_trans_on" if trans_on else "btn_trans_off"),
            bg=ON_COL if trans_on else OFF_COL,
            activebackground=ON_COL if trans_on else OFF_COL)
        # subtitle button
        sub_on = st.subtitles_on
        self._btn_sub.configure(
            text=tr(lang, "btn_sub_on" if sub_on else "btn_sub_off"),
            bg=SUB_COL if sub_on else PANEL,
            activebackground=SUB_COL if sub_on else PANEL)
        # UI-language picker (reflect changes made elsewhere)
        if lang != self._last_uilang:
            self._last_uilang = lang
            ui_label = UI_LANG_LABELS.get(lang, lang)
            if self._uilang_var.get() != ui_label:
                self._uilang_var.set(ui_label)
        # language menus (reflect changes made elsewhere)
        out_label = LANG_LABELS.get(st.target_language, st.target_language)
        if self._out_var.get() != out_label:
            self._out_var.set(out_label)
        sub_label = LANG_LABELS.get(st.inbound_language, st.inbound_language)
        if self._sub_var.get() != sub_label:
            self._sub_var.set(sub_label)
        # status dot
        if connected != self._last_status:
            self._last_status = connected
            self._status_dot.itemconfigure(self._dot_id, fill=ON_COL if connected else DIM)

    # ---------------- drag + layout persistence ----------------
    def _make_draggable(self, win, widget, key: str) -> None:
        state = {"x": 0, "y": 0}

        def press(e):
            state["x"], state["y"] = e.x_root, e.y_root

        def drag(e):
            dx = e.x_root - state["x"]
            dy = e.y_root - state["y"]
            state["x"], state["y"] = e.x_root, e.y_root
            win.geometry(f"+{win.winfo_x() + dx}+{win.winfo_y() + dy}")

        widget.bind("<Button-1>", press)
        widget.bind("<B1-Motion>", drag)

    def _load_layout(self) -> dict:
        try:
            return json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_layout(self) -> None:
        try:
            data = {}
            if self._sub_win is not None:
                data["subtitle"] = {"x": self._sub_win.winfo_x(), "y": self._sub_win.winfo_y()}
            if self._ctl_win is not None:
                data["control"] = {"x": self._ctl_win.winfo_x(), "y": self._ctl_win.winfo_y()}
            LAYOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            LAYOUT_PATH.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            log.debug("desktop UI: failed to save layout", exc_info=True)
