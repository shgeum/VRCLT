"""Runtime controller for the Qt app.

Owns mutable app state, subtitles, audio pipelines, OSC control, and VR
overlays. The Qt UI calls this object from the main thread; pipeline work runs
on a private asyncio thread.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import threading
import time
from typing import Callable

import psutil

from . import config as config_mod
from . import i18n
from .control.osc_listener import OscControl
from .gemini.pipeline import InboundPipeline, OutboundPipeline
from .gemini.session import FatalSessionError
from .languages import language_code_from_text
from .resources import resolve_font_path
from .state import AppState
from .subtitles import SubtitleStore

log = logging.getLogger(__name__)


def steamvr_running() -> bool:
    for p in psutil.process_iter(["name"]):
        n = (p.info["name"] or "").lower()
        if n in ("vrmonitor.exe", "vrcompositor.exe", "vrserver.exe"):
            return True
    return False


def resolve_ui_mode(cfg: dict) -> str:
    mode = cfg.get("ui", {}).get("mode", "auto")
    if mode == "auto":
        return "vr" if steamvr_running() else "desktop"
    return mode if mode in ("vr", "desktop") else "vr"


def vr_panels_enabled(cfg: dict) -> bool:
    if cfg.get("wrist_ui", {}).get("enabled", True):
        return True
    return bool(
        cfg.get("inbound", {}).get("enabled", False)
        and cfg.get("overlay", {}).get("enabled", True)
    )


def wants_vr_renderer(cfg: dict) -> bool:
    mode = cfg.get("ui", {}).get("mode", "auto")
    if mode == "desktop":
        return False
    return vr_panels_enabled(cfg)


def make_wrist_panel(cfg, state, get_status, on_text_only_toggle=lambda enabled: None,
                     on_transform_changed=lambda matrix, reset=False: None):
    from .vr.wrist_ui import WristPanel
    w = cfg.get("wrist_ui", {})
    try:
        width_m = max(0.16, float(w.get("width_m", 0.16) or 0.16))
    except Exception:
        width_m = 0.16
    return WristPanel(
        state, cfg.get("control", {}).get("languages", ["en"]),
        inbound_languages=cfg.get("inbound", {}).get("languages", ["ko", "en"]),
        hand=w.get("hand", "left"),
        width_m=width_m,
        offset=w.get("offset", [0.0, 0.02, 0.12]),
        tilt_deg=w.get("tilt_deg", 0.0),
        roll_deg=w.get("roll_deg", None),
        transform=w.get("transform"),
        pointer_tilt_deg=w.get("pointer_tilt_deg", 50.0),
        font_path=resolve_font_path(w.get("font"), "NotoSansCJKkr-Bold.otf"),
        on_text_only_toggle=on_text_only_toggle,
        on_transform_changed=on_transform_changed,
        get_status=get_status,
    )


def make_subtitle_panel(cfg, store, state, on_transform_changed=lambda matrix, reset=False: None,
                        on_size_changed=lambda width_m, height_m: None):
    from .vr.subtitle_overlay import SubtitlePanel
    o = cfg.get("overlay", {})
    w = cfg.get("wrist_ui", {})
    return SubtitlePanel(
        store, state,
        hand=w.get("hand", "left"),
        width_m=o.get("width_m", 0.9),
        height_m=o.get("height_m"),
        distance_m=o.get("distance_m", 1.2),
        below_m=o.get("below_m", 0.35),
        tilt_deg=o.get("tilt_deg", -15.0),
        transform=o.get("transform"),
        pointer_tilt_deg=w.get("pointer_tilt_deg", 50.0),
        font_path=resolve_font_path(o.get("font"), "NotoSansCJKkr-Regular.otf"),
        font_size=o.get("font_size", 36),
        show_source=o.get("show_source", False),
        on_transform_changed=on_transform_changed,
        on_size_changed=on_size_changed,
    )


def _wrist_angles_from_matrix(rows) -> tuple[float, float]:
    """Approximate wrist tilt/roll from the stored 3x4 OpenVR transform."""
    import math

    r00 = float(rows[0][0])
    r01 = float(rows[0][1])
    r12 = float(rows[1][2])
    r22 = float(rows[2][2])
    roll = math.degrees(math.atan2(-r01, r00))
    tilt = math.degrees(math.atan2(-r12, r22)) + 90.0
    return tilt, roll


def _subtitle_tilt_from_matrix(rows) -> float:
    import math

    return math.degrees(math.atan2(float(rows[2][1]), float(rows[1][1])))


def _language_list(values) -> list[str]:
    if isinstance(values, str):
        values = values.split(",")
    seen = set()
    out: list[str] = []
    for value in values or []:
        code = language_code_from_text(str(value).strip())
        if not code:
            continue
        key = code.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(code)
    return out


class AppController:
    def __init__(self, cfg: dict):
        self._lock = threading.RLock()
        self._listeners: list[Callable[[], None]] = []
        self.raw_cfg = copy.deepcopy(cfg)
        force_profile = config_mod.profile_runtime_looks_stale(self.raw_cfg)
        self.cfg = config_mod.apply_app_profile(self.raw_cfg, force=force_profile)
        if force_profile:
            self.raw_cfg = copy.deepcopy(self.cfg)
            try:
                config_mod.save(self.raw_cfg)
                log.info("repaired stale app profile runtime settings")
            except Exception:
                log.debug("failed to persist repaired app profile settings", exc_info=True)
        self.state = self._make_state(self.cfg)
        self.store = self._make_store(self.cfg)
        self.config_revision = 0
        self.status = "Stopped"
        self.last_error = ""
        self.started_at = 0.0

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._pipeline = None
        self._inbound = None
        self._control = None
        self._renderer = None
        self._restarting = False

    def subscribe(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                log.exception("controller listener failed")

    def _make_state(self, cfg: dict) -> AppState:
        dashboard = cfg.get("dashboard", {})
        st = AppState(
            translation_on=dashboard.get(
                "translation_on", cfg.get("outbound", {}).get("enabled", True)),
            target_language=language_code_from_text(
                cfg.get("outbound", {}).get("target_language", "en")),
            subtitles_on=dashboard.get(
                "subtitles_on", cfg.get("inbound", {}).get("enabled", True)),
            inbound_language=language_code_from_text(
                cfg.get("inbound", {}).get("target_language", "ko")),
            ui_lang=i18n.detect(cfg.get("ui", {}).get("lang", "")),
            text_only=self._is_text_only(cfg),
        )
        st.subscribe(self._persist_runtime_state)
        st.subscribe(lambda *_: self._notify())
        return st

    @staticmethod
    def _make_store(cfg: dict) -> SubtitleStore:
        o = cfg.get("overlay", {})
        return SubtitleStore(max_lines=o.get("lines", 3),
                             display_sec=o.get("display_sec", 7.0))

    def _persist_runtime_state(self, field: str, value) -> None:
        with self._lock:
            if field == "ui_lang":
                self.raw_cfg.setdefault("ui", {})["lang"] = value
            elif field == "target_language":
                self.raw_cfg.setdefault("outbound", {})["target_language"] = value
            elif field == "inbound_language":
                self.raw_cfg.setdefault("inbound", {})["target_language"] = value
            elif field == "translation_on":
                self.raw_cfg.setdefault("dashboard", {})["translation_on"] = bool(value)
            elif field == "subtitles_on":
                self.raw_cfg.setdefault("dashboard", {})["subtitles_on"] = bool(value)
            else:
                return
            cfg = copy.deepcopy(self.raw_cfg)
        try:
            config_mod.save(cfg)
            self._bump_config_revision()
        except Exception:
            log.debug("failed to persist runtime state", exc_info=True)

    def _bump_config_revision(self) -> None:
        with self._lock:
            self.config_revision += 1
        self._notify()

    def connected(self) -> bool:
        pipeline = self._pipeline
        try:
            return bool(pipeline and pipeline.session.connected)
        except Exception:
            return False

    def subtitles_snapshot(self):
        return self.store.snapshot()

    def set_translation_on(self, value: bool) -> None:
        self.state.translation_on = value

    def set_subtitles_on(self, value: bool) -> None:
        self.state.subtitles_on = value

    def set_target_language(self, value: str) -> None:
        self.state.target_language = language_code_from_text(value)

    def set_inbound_language(self, value: str) -> None:
        self.state.inbound_language = language_code_from_text(value)

    def add_output_language(self, value: str) -> None:
        code = language_code_from_text(str(value or "").strip())
        if not code:
            return
        languages = _language_list(self.cfg.get("control", {}).get("languages", []))
        if code.lower() not in {lang.lower() for lang in languages}:
            languages.append(code)
            self.set_output_languages(languages)
        self.set_target_language(code)

    def add_inbound_language(self, value: str) -> None:
        code = language_code_from_text(str(value or "").strip())
        if not code:
            return
        languages = _language_list(self.cfg.get("inbound", {}).get("languages", []))
        if code.lower() not in {lang.lower() for lang in languages}:
            languages.append(code)
            self.set_inbound_languages(languages)
        self.set_inbound_language(code)

    def set_output_languages(self, values) -> None:
        languages = _language_list(values)
        if not languages:
            return
        with self._lock:
            self.raw_cfg.setdefault("control", {})["languages"] = languages
            self.cfg.setdefault("control", {})["languages"] = list(languages)
            cfg = copy.deepcopy(self.raw_cfg)
        try:
            config_mod.save(cfg)
            self._bump_config_revision()
        except Exception:
            log.debug("failed to persist output languages", exc_info=True)
        if self.state.target_language not in languages:
            self.state.target_language = languages[0]

    def set_inbound_languages(self, values) -> None:
        languages = _language_list(values)
        if not languages:
            return
        with self._lock:
            self.raw_cfg.setdefault("inbound", {})["languages"] = languages
            self.cfg.setdefault("inbound", {})["languages"] = list(languages)
            cfg = copy.deepcopy(self.raw_cfg)
        try:
            config_mod.save(cfg)
            self._bump_config_revision()
        except Exception:
            log.debug("failed to persist inbound languages", exc_info=True)
        if self.state.inbound_language not in languages:
            self.state.inbound_language = languages[0]

    def set_ui_lang(self, value: str) -> None:
        self.state.ui_lang = value

    def close_action(self) -> str:
        return config_mod.normalize_close_action(
            self.cfg.get("ui", {}).get("close_action", "tray"))

    def set_close_action(self, value: str) -> None:
        value = config_mod.normalize_close_action(value)
        with self._lock:
            self.raw_cfg.setdefault("ui", {})["close_action"] = value
            self.cfg.setdefault("ui", {})["close_action"] = value
            cfg = copy.deepcopy(self.raw_cfg)
        try:
            config_mod.save(cfg)
            self._bump_config_revision()
        except Exception:
            log.debug("failed to persist close action", exc_info=True)

    def set_overlay_font_size(self, value: int) -> None:
        value = max(18, min(72, int(value)))
        with self._lock:
            self.raw_cfg.setdefault("overlay", {})["font_size"] = value
            self.cfg.setdefault("overlay", {})["font_size"] = value
        try:
            config_mod.save(self.raw_cfg)
            self._bump_config_revision()
        except Exception:
            log.debug("failed to persist overlay font size", exc_info=True)

    def last_config_version(self) -> str:
        try:
            return str(self.raw_cfg.get("meta", {}).get("last_version") or "")
        except Exception:
            return ""

    def mark_config_version_seen(self, version: str) -> None:
        with self._lock:
            self.raw_cfg = config_mod.mark_version_seen(self.raw_cfg, version)
            self.cfg = config_mod.mark_version_seen(self.cfg, version)
            cfg = copy.deepcopy(self.raw_cfg)
        try:
            config_mod.save(cfg)
            self._bump_config_revision()
        except Exception:
            log.debug("failed to persist config version marker", exc_info=True)

    def reset_config_preserving_language_lists(self, version: str = "") -> bool:
        try:
            with self._lock:
                cfg = config_mod.reset_preserving_language_lists(self.raw_cfg, version)
            config_mod.save(cfg)
        except Exception as e:
            log.exception("failed to reset config")
            self.last_error = str(e)
            self._notify()
            return False
        return self.restart(cfg)

    def set_overlay_width(self, value: float) -> None:
        try:
            value = float(value)
        except Exception:
            return
        value = round(max(0.45, min(1.6, value)), 2)
        with self._lock:
            self.raw_cfg.setdefault("overlay", {})["width_m"] = value
            self.cfg.setdefault("overlay", {})["width_m"] = value
            cfg = copy.deepcopy(self.raw_cfg)
        try:
            config_mod.save(cfg)
            self._bump_config_revision()
        except Exception:
            log.debug("failed to persist overlay width", exc_info=True)

    def set_overlay_size(self, width_m: float, height_m: float) -> None:
        try:
            width_m = float(width_m)
            height_m = float(height_m)
        except Exception:
            return
        width_m = round(max(0.45, min(1.6, width_m)), 2)
        height_m = round(max(0.10, min(0.60, height_m)), 2)
        with self._lock:
            overlay = self.raw_cfg.setdefault("overlay", {})
            overlay["width_m"] = width_m
            overlay["height_m"] = height_m
            cfg_overlay = self.cfg.setdefault("overlay", {})
            cfg_overlay["width_m"] = width_m
            cfg_overlay["height_m"] = height_m
            cfg = copy.deepcopy(self.raw_cfg)
        try:
            config_mod.save(cfg)
            self._bump_config_revision()
        except Exception:
            log.debug("failed to persist overlay size", exc_info=True)

    def set_wrist_transform(self, matrix, reset: bool = False) -> None:
        try:
            rows = [[float(matrix[r][c]) for c in range(4)] for r in range(3)]
            offset = [round(float(rows[r][3]), 4) for r in range(3)]
            tilt, roll = _wrist_angles_from_matrix(rows)
        except Exception:
            log.debug("invalid wrist transform", exc_info=True)
            return

        with self._lock:
            w = self.raw_cfg.setdefault("wrist_ui", {})
            if reset:
                defaults = config_mod.DEFAULTS["wrist_ui"]
                w["offset"] = list(defaults["offset"])
                w["tilt_deg"] = defaults["tilt_deg"]
                w["roll_deg"] = defaults["roll_deg"]
                if defaults.get("transform") is not None:
                    w["transform"] = copy.deepcopy(defaults["transform"])
                else:
                    w.pop("transform", None)
            else:
                w["offset"] = offset
                w["tilt_deg"] = round(tilt, 3)
                w["roll_deg"] = round(roll, 3)
                w["transform"] = rows
            self.cfg = config_mod.apply_app_profile(self.raw_cfg)
            cfg = copy.deepcopy(self.raw_cfg)
        try:
            config_mod.save(cfg)
            self._bump_config_revision()
        except Exception:
            log.debug("failed to persist wrist transform", exc_info=True)

    def set_subtitle_transform(self, matrix, reset: bool = False) -> None:
        try:
            rows = [[float(matrix[r][c]) for c in range(4)] for r in range(3)]
            below = round(-float(rows[1][3]), 4)
            distance = round(-float(rows[2][3]), 4)
            tilt = round(_subtitle_tilt_from_matrix(rows), 3)
        except Exception:
            log.debug("invalid subtitle transform", exc_info=True)
            return

        with self._lock:
            o = self.raw_cfg.setdefault("overlay", {})
            if reset:
                defaults = config_mod.DEFAULTS["overlay"]
                o["distance_m"] = defaults["distance_m"]
                o["below_m"] = defaults["below_m"]
                o["tilt_deg"] = defaults["tilt_deg"]
                o.pop("transform", None)
            else:
                o["distance_m"] = distance
                o["below_m"] = below
                o["tilt_deg"] = tilt
                o["transform"] = rows
            self.cfg = config_mod.apply_app_profile(self.raw_cfg)
            cfg = copy.deepcopy(self.raw_cfg)
        try:
            config_mod.save(cfg)
            self._bump_config_revision()
        except Exception:
            log.debug("failed to persist subtitle transform", exc_info=True)

    def set_text_only(self, value: bool) -> None:
        value = bool(value)
        self.state.text_only = value

        def apply():
            with self._lock:
                if self._restarting:
                    return
            try:
                cfg = copy.deepcopy(self.raw_cfg)
                if value:
                    cfg.setdefault("app", {})["mode"] = "vrchat"
                cfg.setdefault("outbound", {})["text_only"] = value
                cfg = config_mod.apply_app_profile(cfg, force=True)
                config_mod.save(cfg)
            except Exception as e:
                log.exception("failed to apply text-only mode")
                self.state.text_only = not value
                self.last_error = str(e)
                self._notify()
                return
            self.restart(cfg)

        threading.Thread(target=apply, daemon=True, name="vrclt-text-only-restart").start()

    def start(self) -> bool:
        return self.restart(self.raw_cfg)

    def restart(self, cfg: dict | None = None) -> bool:
        with self._lock:
            self._restarting = True
        try:
            self.stop(timeout=8.0)
            with self._lock:
                if cfg is not None:
                    self.raw_cfg = copy.deepcopy(cfg)
                self.cfg = config_mod.apply_app_profile(self.raw_cfg)
                self.state = self._make_state(self.cfg)
                self.store = self._make_store(self.cfg)
                self.last_error = ""
                self.status = "Starting"
                self._notify()

            key = config_mod.api_key(self.cfg)
            if not key:
                self._set_status("API key required", "API key is empty.")
                return False
            key_error = config_mod.api_key_validation_error(key)
            if key_error:
                self._set_status("API key invalid", key_error)
                return False

            return self._start_runtime(key)
        except Exception as e:
            log.exception("runtime restart failed")
            self._set_status("Failed", str(e))
            return False
        finally:
            with self._lock:
                self._restarting = False

    def stop(self, timeout: float = 8.0) -> None:
        thread = self._thread
        loop = self._loop
        stop_event = self._stop_event
        renderer = self._renderer
        if loop is not None and stop_event is not None:
            try:
                loop.call_soon_threadsafe(stop_event.set)
            except Exception:
                pass
        if renderer is not None:
            renderer.stop()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                log.warning("runtime thread did not stop within %.1fs", timeout)
        self._thread = None
        self._loop = None
        self._stop_event = None
        self._pipeline = None
        self._inbound = None
        self._control = None
        self._renderer = None
        if not self._restarting:
            self._set_status("Stopped")

    def _start_runtime(self, key: str) -> bool:
        state = self.state
        store = self.store
        cfg = self.cfg

        pipeline = OutboundPipeline(cfg, key, state)
        inbound = None
        if cfg.get("inbound", {}).get("enabled", False):
            inbound = InboundPipeline(cfg, key, store, state)
            audio_cfg = cfg.get("audio", {})
            mult = float(audio_cfg.get("echo_guard_multiplier", 4.0))
            hold_sec = float(audio_cfg.get("echo_guard_hold_sec", 1.2))
            barge_mult = float(audio_cfg.get("echo_guard_barge_in_multiplier", 3.0))
            ib = inbound
            if mult > 1.0:
                pipeline.mic.set_threshold_boost(
                    lambda: mult if (state.translation_on and ib.tap.active(hold_sec)) else 1.0)
            if hold_sec > 0.0:
                pipeline.mic.set_suppressed(
                    lambda: ib.tap.active(hold_sec),
                    barge_in_multiplier=barge_mult)

        control = None
        ctl = cfg.get("control", {})
        if ctl.get("enabled", True):
            control = OscControl(
                state,
                listen_port=ctl.get("osc_listen_port", 9001),
                param_enabled=ctl.get("param_enabled", "VRCLT_Enabled"),
                param_lang=ctl.get("param_lang", "VRCLT_Lang"),
                languages=ctl.get("languages", ["en"]),
            )
            control.start()

        renderer = None
        if wants_vr_renderer(cfg):
            panels = []
            o = cfg.get("overlay", {})
            if inbound and o.get("enabled", True):
                panels.append(make_subtitle_panel(
                    cfg, store, state,
                    on_transform_changed=self.set_subtitle_transform,
                    on_size_changed=self.set_overlay_size))
            if cfg.get("wrist_ui", {}).get("enabled", True):
                panels.insert(0, make_wrist_panel(
                    cfg, state,
                    get_status=lambda: pipeline.session.connected,
                    on_text_only_toggle=self.set_text_only,
                    on_transform_changed=self.set_wrist_transform))
            if panels:
                from .vr.render import VrRenderer
                renderer = VrRenderer(panels, can_start=steamvr_running)
                renderer.start()

        self._pipeline = pipeline
        self._inbound = inbound
        self._control = control
        self._renderer = renderer

        ready = threading.Event()

        def worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            stop_event = asyncio.Event()
            self._loop = loop
            self._stop_event = stop_event
            ready.set()
            self.started_at = time.time()
            self._set_status("Running")
            try:
                loop.run_until_complete(self._gather_pipelines(stop_event, pipeline, inbound))
            except Exception as e:
                log.exception("runtime worker crashed")
                self._set_status("Failed", str(e))
            finally:
                try:
                    if control:
                        control.stop()
                finally:
                    try:
                        loop.close()
                    except Exception:
                        pass
                if not self._restarting:
                    self._set_status("Stopped")

        self._thread = threading.Thread(target=worker, daemon=True, name="vrclt-runtime")
        self._thread.start()
        ready.wait(2.0)
        return True

    async def _gather_pipelines(self, stop, pipeline, inbound) -> None:
        async def safe(coro, name):
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except FatalSessionError as e:
                log.error("%s pipeline stopped: %s", name, e)
                self._set_status("API key invalid", str(e))
                stop.set()
            except Exception as e:
                log.exception("%s pipeline crashed", name)
                self._set_status("Degraded", f"{name}: {e}")

        tasks = [safe(pipeline.run(stop), "outbound")]
        if inbound:
            tasks.append(safe(inbound.run(stop), "inbound"))
        await asyncio.gather(*tasks)

    def _set_status(self, status: str, error: str = "") -> None:
        with self._lock:
            self.status = status
            self.last_error = error
        self._notify()

    @staticmethod
    def _is_text_only(cfg: dict) -> bool:
        ob = cfg.get("outbound", {})
        return bool(
            ob.get("text_only", False)
            or (not ob.get("voice_output", True)
                and ob.get("passthrough_while_translating", False)
                and ob.get("chatbox", False))
        )
