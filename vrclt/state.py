"""Runtime app state, mutable from the OSC control listener / UI threads."""
import logging
import threading

log = logging.getLogger(__name__)


class AppState:
    def __init__(self, translation_on: bool = True, target_language: str = "en",
                 subtitles_on: bool = True, inbound_language: str = "ko",
                 ui_lang: str = "en", text_only: bool = False):
        self._lock = threading.Lock()
        self._translation_on = translation_on
        self._target_language = target_language
        self._subtitles_on = subtitles_on
        self._inbound_language = inbound_language
        self._ui_lang = ui_lang
        self._text_only = text_only
        self._edit_mode = False
        self._wrist_edit_mode = False
        self._listeners = []

    def subscribe(self, fn) -> None:
        """fn(field_name, new_value) - called from the mutating thread."""
        self._listeners.append(fn)

    def _notify(self, field: str, value) -> None:
        for fn in self._listeners:
            try:
                fn(field, value)
            except Exception:
                log.exception("state listener failed")

    @property
    def translation_on(self) -> bool:
        with self._lock:
            return self._translation_on

    @translation_on.setter
    def translation_on(self, value: bool) -> None:
        value = bool(value)
        with self._lock:
            changed = value != self._translation_on
            self._translation_on = value
        if changed:
            log.info("state: translation %s", "ON" if value else "OFF (passthrough)")
            self._notify("translation_on", value)

    @property
    def target_language(self) -> str:
        with self._lock:
            return self._target_language

    @target_language.setter
    def target_language(self, value: str) -> None:
        with self._lock:
            changed = value != self._target_language
            self._target_language = value
        if changed:
            log.info("state: target language -> %s", value)
            self._notify("target_language", value)

    @property
    def subtitles_on(self) -> bool:
        with self._lock:
            return self._subtitles_on

    @subtitles_on.setter
    def subtitles_on(self, value: bool) -> None:
        value = bool(value)
        with self._lock:
            changed = value != self._subtitles_on
            self._subtitles_on = value
        if changed:
            log.info("state: subtitles %s", "ON" if value else "OFF")
            self._notify("subtitles_on", value)

    @property
    def edit_mode(self) -> bool:
        with self._lock:
            return self._edit_mode

    @edit_mode.setter
    def edit_mode(self, value: bool) -> None:
        value = bool(value)
        notify_wrist = False
        with self._lock:
            changed = value != getattr(self, "_edit_mode", False)
            self._edit_mode = value
            if value and self._wrist_edit_mode:
                self._wrist_edit_mode = False
                notify_wrist = True
        if changed:
            log.info("state: subtitle edit mode %s", "ON" if value else "OFF")
            self._notify("edit_mode", value)
        if notify_wrist:
            log.info("state: wrist edit (move) mode OFF")
            self._notify("wrist_edit_mode", False)

    @property
    def wrist_edit_mode(self) -> bool:
        with self._lock:
            return self._wrist_edit_mode

    @wrist_edit_mode.setter
    def wrist_edit_mode(self, value: bool) -> None:
        value = bool(value)
        notify_subtitle = False
        with self._lock:
            changed = value != getattr(self, "_wrist_edit_mode", False)
            self._wrist_edit_mode = value
            if value and self._edit_mode:
                self._edit_mode = False
                notify_subtitle = True
        if changed:
            log.info("state: wrist edit (move) mode %s", "ON" if value else "OFF")
            self._notify("wrist_edit_mode", value)
        if notify_subtitle:
            log.info("state: subtitle edit mode OFF")
            self._notify("edit_mode", False)

    def request_position_reset(self) -> None:
        """Reset subtitle overlay positions to defaults."""
        log.info("state: subtitle position reset requested")
        self._notify("reset_positions", True)

    @property
    def inbound_language(self) -> str:
        with self._lock:
            return self._inbound_language

    @inbound_language.setter
    def inbound_language(self, value: str) -> None:
        with self._lock:
            changed = value != self._inbound_language
            self._inbound_language = value
        if changed:
            log.info("state: inbound (subtitle) language -> %s", value)
            self._notify("inbound_language", value)

    @property
    def ui_lang(self) -> str:
        with self._lock:
            return self._ui_lang

    @ui_lang.setter
    def ui_lang(self, value: str) -> None:
        with self._lock:
            changed = value != self._ui_lang
            self._ui_lang = value
        if changed:
            log.info("state: UI display language -> %s", value)
            self._notify("ui_lang", value)

    @property
    def text_only(self) -> bool:
        with self._lock:
            return self._text_only

    @text_only.setter
    def text_only(self, value: bool) -> None:
        value = bool(value)
        with self._lock:
            changed = value != self._text_only
            self._text_only = value
        if changed:
            log.info("state: text-only mode %s", "ON" if value else "OFF")
            self._notify("text_only", value)
