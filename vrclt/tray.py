"""System tray icon: quick control + open web UI + quit, without a console.

Runs detached (its own thread); menu callbacks touch the thread-safe AppState
or call on_quit() to shut the app down.
"""
import logging
import webbrowser

log = logging.getLogger(__name__)


class Tray:
    def __init__(self, state, web_port: int, on_quit):
        self._state = state
        self._port = web_port
        self._on_quit = on_quit
        self._icon = None

    def start(self) -> bool:
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception:
            log.exception("tray unavailable")
            return False
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((6, 6, 58, 58), 14, fill=(74, 110, 180, 255))
        d.text((23, 18), "V", fill=(255, 255, 255, 255))
        self._icon = pystray.Icon("vrclt", img, "vrclt - VRChat Live Translator", menu=pystray.Menu(
            pystray.MenuItem("웹 UI 열기", self._open_web, default=True),
            pystray.MenuItem("번역 ON/OFF", self._toggle_trans,
                             checked=lambda _i: self._state.translation_on),
            pystray.MenuItem("자막 ON/OFF", self._toggle_sub,
                             checked=lambda _i: self._state.subtitles_on),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("종료", self._quit),
        ))
        try:
            self._icon.run_detached()
        except Exception:
            log.exception("tray failed to start")
            return False
        log.info("tray icon started")
        return True

    def _open_web(self, *_):
        webbrowser.open(f"http://127.0.0.1:{self._port}")

    def _toggle_trans(self, *_):
        self._state.translation_on = not self._state.translation_on

    def _toggle_sub(self, *_):
        self._state.subtitles_on = not self._state.subtitles_on

    def _quit(self, icon, _item):
        try:
            self._on_quit()
        finally:
            icon.stop()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
