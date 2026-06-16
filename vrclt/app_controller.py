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
from .state import AppState
from .subtitles import SubtitleStore

log = logging.getLogger(__name__)


def steamvr_running() -> bool:
    for p in psutil.process_iter(["name"]):
        n = (p.info["name"] or "").lower()
        if n in ("vrmonitor.exe", "vrserver.exe"):
            return True
    return False


def resolve_ui_mode(cfg: dict) -> str:
    mode = cfg.get("ui", {}).get("mode", "auto")
    if mode == "auto":
        return "vr" if steamvr_running() else "desktop"
    return mode if mode in ("vr", "desktop") else "vr"


def make_wrist_panel(cfg, state, get_status):
    from .vr.wrist_ui import WristPanel
    w = cfg.get("wrist_ui", {})
    return WristPanel(
        state, cfg.get("control", {}).get("languages", ["en"]),
        inbound_languages=cfg.get("inbound", {}).get("languages", ["ko", "en"]),
        hand=w.get("hand", "left"),
        width_m=w.get("width_m", 0.12),
        offset=w.get("offset", [0.0, 0.02, 0.12]),
        tilt_deg=w.get("tilt_deg", 0.0),
        roll_deg=w.get("roll_deg", None),
        pointer_tilt_deg=w.get("pointer_tilt_deg", 50.0),
        font_path=w.get("font", "C:/Windows/Fonts/malgunbd.ttf"),
        get_status=get_status,
    )


def make_subtitle_panel(cfg, store, state):
    from .vr.subtitle_overlay import SubtitlePanel
    o = cfg.get("overlay", {})
    return SubtitlePanel(
        store, state,
        hand=cfg.get("wrist_ui", {}).get("hand", "left"),
        width_m=o.get("width_m", 0.9),
        distance_m=o.get("distance_m", 1.2),
        below_m=o.get("below_m", 0.35),
        tilt_deg=o.get("tilt_deg", -15.0),
        font_path=o.get("font", "C:/Windows/Fonts/malgun.ttf"),
        font_size=o.get("font_size", 36),
        show_source=o.get("show_source", False),
    )


class AppController:
    def __init__(self, cfg: dict):
        self._lock = threading.RLock()
        self._listeners: list[Callable[[], None]] = []
        self.raw_cfg = copy.deepcopy(cfg)
        self.cfg = config_mod.apply_app_profile(self.raw_cfg)
        self.state = self._make_state(self.cfg)
        self.store = self._make_store(self.cfg)
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
        st = AppState(
            translation_on=True,
            target_language=cfg.get("outbound", {}).get("target_language", "en"),
            subtitles_on=True,
            inbound_language=cfg.get("inbound", {}).get("target_language", "ko"),
            ui_lang=i18n.detect(cfg.get("ui", {}).get("lang", "")),
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
        if field == "ui_lang":
            self.raw_cfg.setdefault("ui", {})["lang"] = value
        elif field == "target_language":
            self.raw_cfg.setdefault("outbound", {})["target_language"] = value
        elif field == "inbound_language":
            self.raw_cfg.setdefault("inbound", {})["target_language"] = value
        else:
            return
        try:
            config_mod.save(self.raw_cfg)
        except Exception:
            log.debug("failed to persist runtime state", exc_info=True)

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
        self.state.target_language = value

    def set_inbound_language(self, value: str) -> None:
        self.state.inbound_language = value

    def set_ui_lang(self, value: str) -> None:
        self.state.ui_lang = value

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
        if loop is not None and stop_event is not None:
            try:
                loop.call_soon_threadsafe(stop_event.set)
            except Exception:
                pass
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
            mult = float(cfg.get("audio", {}).get("echo_guard_multiplier", 4.0))
            if mult > 1.0:
                ib = inbound
                pipeline.mic.set_threshold_boost(
                    lambda: mult if (state.translation_on and ib.tap.active(1.0)) else 1.0)

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
        if resolve_ui_mode(cfg) == "vr":
            panels = []
            o = cfg.get("overlay", {})
            if inbound and o.get("enabled", True):
                panels.append(make_subtitle_panel(cfg, store, state))
            if cfg.get("wrist_ui", {}).get("enabled", True):
                panels.insert(0, make_wrist_panel(
                    cfg, state, get_status=lambda: pipeline.session.connected))
            if panels:
                from .vr.render import VrRenderer
                renderer = VrRenderer(panels)
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
                    if renderer:
                        renderer.stop()
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
