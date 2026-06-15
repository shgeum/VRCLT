"""In-VR control via VRChat avatar parameters (OSC).

VRChat sends every avatar parameter change to UDP 127.0.0.1:9001 as
/avatar/parameters/<name>. Add these to your avatar's Expression Parameters
and Action Menu to control vrclt from the radial menu in VR:

  - VRCLT_Enabled (bool)  -> translation ON / OFF (passthrough)
  - VRCLT_Lang    (int)   -> index into control.languages from config.yaml

If another OSC app already occupies port 9001 the listener logs a warning
and in-VR control is disabled (everything else keeps working).
"""
import logging
import threading

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

from ..state import AppState

log = logging.getLogger(__name__)


class OscControl:
    def __init__(self, state: AppState, *, listen_port: int = 9001,
                 param_enabled: str = "VRCLT_Enabled", param_lang: str = "VRCLT_Lang",
                 languages: list[str] | None = None):
        self._state = state
        self._port = listen_port
        self._languages = languages or ["en"]
        self._server: ThreadingOSCUDPServer | None = None
        self._thread: threading.Thread | None = None

        self._dispatcher = Dispatcher()
        self._dispatcher.map(f"/avatar/parameters/{param_enabled}", self._on_enabled)
        self._dispatcher.map(f"/avatar/parameters/{param_lang}", self._on_lang)

    def _on_enabled(self, _addr, *args) -> None:
        if args:
            self._state.translation_on = bool(args[0])

    def _on_lang(self, _addr, *args) -> None:
        if not args:
            return
        try:
            idx = int(args[0])
        except (TypeError, ValueError):
            return
        if 0 <= idx < len(self._languages):
            self._state.target_language = self._languages[idx]
        else:
            log.warning("lang index %d out of range (languages: %s)", idx, self._languages)

    def start(self) -> bool:
        try:
            self._server = ThreadingOSCUDPServer(("127.0.0.1", self._port), self._dispatcher)
        except OSError as e:
            log.warning("OSC control disabled: cannot bind port %d (%s) - "
                        "another OSC app (VRCT etc.) may be using it", self._port, e)
            return False
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True, name="vrclt-osc-control")
        self._thread.start()
        log.info("OSC control listening on 127.0.0.1:%d (languages: %s)",
                 self._port, self._languages)
        return True

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
            self._server = None
