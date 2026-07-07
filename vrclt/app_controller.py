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
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import psutil

from . import config as config_mod
from . import i18n
from .audio.devices import device_names
from .control.osc_listener import OscControl
from .gemini.pipeline import InboundPipeline, OutboundPipeline
from .gemini.session import FatalSessionError
from .languages import language_code_from_text
from .resources import resolve_font_path
from .state import AppState
from .subtitles import SubtitleStore

log = logging.getLogger(__name__)


# polled from UI timers (desktop overlay: every 120 ms); scanning the whole
# process table that often stalls the GUI thread, so cache the answer briefly.
# The (result, expires) tuple is replaced atomically - benign if two threads
# race, both just rescan.
_STEAMVR_CACHE_TTL = 3.0
_steamvr_cache: tuple[bool, float] = (False, 0.0)


def steamvr_running() -> bool:
    global _steamvr_cache
    result, expires = _steamvr_cache
    now = time.monotonic()
    if now < expires:
        return result
    result = False
    for p in psutil.process_iter(["name"]):
        n = (p.info["name"] or "").lower()
        if n in ("vrmonitor.exe", "vrcompositor.exe", "vrserver.exe"):
            result = True
            break
    _steamvr_cache = (result, now + _STEAMVR_CACHE_TTL)
    return result


def resolve_ui_mode(cfg: dict) -> str:
    mode = cfg.get("ui", {}).get("mode", "auto")
    if mode == "auto":
        return "vr" if steamvr_running() else "desktop"
    return mode if mode in ("vr", "desktop") else "vr"


def vr_panels_enabled(cfg: dict) -> bool:
    if cfg.get("wrist_ui", {}).get("enabled", True):
        return True
    if cfg.get("steamvr", {}).get("dashboard_panel", True):
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
        font_size=o.get("font_size", 27),
        show_source=o.get("show_source", False),
        on_transform_changed=on_transform_changed,
        on_size_changed=on_size_changed,
    )


def make_dashboard_panel(cfg, state, get_status, on_text_only_toggle,
                         on_font_size, get_font_size,
                         get_auto_launch, set_auto_launch, on_restart,
                         get_devices, get_mic_device, get_tts_device,
                         set_audio_devices):
    from .vr.dashboard_panel import DashboardPanel
    w = cfg.get("wrist_ui", {})
    return DashboardPanel(
        state,
        languages=cfg.get("control", {}).get("languages", ["en"]),
        inbound_languages=cfg.get("inbound", {}).get("languages", ["ko", "en"]),
        font_path=resolve_font_path(w.get("font"), "NotoSansCJKkr-Bold.otf"),
        get_status=get_status,
        on_text_only_toggle=on_text_only_toggle,
        on_font_size=on_font_size,
        get_font_size=get_font_size,
        get_auto_launch=get_auto_launch,
        set_auto_launch=set_auto_launch,
        on_restart=on_restart,
        get_devices=get_devices,
        get_mic_device=get_mic_device,
        get_tts_device=get_tts_device,
        set_audio_devices=set_audio_devices,
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
        self._renderer_signature = None
        self._panels: list = []
        self._restarting = False
        # serializes restart()/stop(): they are called from Qt background
        # threads, the wrist-panel path, and app quit; overlapping runs used
        # to orphan the VR renderer/pipeline. RLock because restart -> stop.
        self._lifecycle_lock = threading.RLock()
        self._closed = False
        # config saves run off-thread (dashboard-panel clicks call _persist
        # from the 30 Hz VR render thread; disk I/O there stalls the overlay).
        # Single worker = submission order preserved.
        self._persist_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="vrclt-persist")

        from .vr import steamvr_apps
        self._steamvr_apps = steamvr_apps
        self._auto_launch_cache: tuple[float, bool | None] = (0.0, None)
        self._auto_launch_refreshing = False
        self._auto_launch_gen = 0
        self._app_registrar = steamvr_apps.SteamVrAppRegistrar(steamvr_running)
        self._app_registrar.start(
            lambda: bool(self.cfg.get("steamvr", {}).get("register", True)))

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

    def _sync_state_from_cfg(self, cfg: dict) -> None:
        """Update the persistent AppState in place from a (re)loaded config.
        The object is reused across restarts so VR panels and other
        subscribers keep a valid reference (no overlay blink on restart)."""
        dashboard = cfg.get("dashboard", {})
        st = self.state
        st.translation_on = dashboard.get(
            "translation_on", cfg.get("outbound", {}).get("enabled", True))
        st.target_language = language_code_from_text(
            cfg.get("outbound", {}).get("target_language", "en"))
        st.subtitles_on = dashboard.get(
            "subtitles_on", cfg.get("inbound", {}).get("enabled", True))
        st.inbound_language = language_code_from_text(
            cfg.get("inbound", {}).get("target_language", "ko"))
        st.ui_lang = i18n.detect(cfg.get("ui", {}).get("lang", ""))
        st.text_only = self._is_text_only(cfg)

    @staticmethod
    def _vr_config_signature(cfg: dict):
        """The config subset VR panels capture at construction; the renderer
        is rebuilt on restart only when this changes."""
        def freeze(v):
            if isinstance(v, dict):
                return tuple(sorted((k, freeze(x)) for k, x in v.items()))
            if isinstance(v, (list, tuple)):
                return tuple(freeze(x) for x in v)
            return v

        return freeze({
            "overlay": cfg.get("overlay", {}),
            "wrist_ui": cfg.get("wrist_ui", {}),
            "dashboard_panel": cfg.get("steamvr", {}).get("dashboard_panel", True),
            "out_langs": cfg.get("control", {}).get("languages", []),
            "in_langs": cfg.get("inbound", {}).get("languages", []),
            "inbound_enabled": cfg.get("inbound", {}).get("enabled", False),
            "ui_mode": cfg.get("ui", {}).get("mode", "auto"),
        })

    @staticmethod
    def _make_store(cfg: dict) -> SubtitleStore:
        o = cfg.get("overlay", {})
        return SubtitleStore(max_lines=o.get("lines", 3),
                             display_sec=o.get("display_sec", 7.0))

    def _persist(self, log_label: str, mutate) -> None:
        """Apply mutate() to the config under the lock, then save a snapshot
        on the persist worker (callers include the VR render thread, which
        must never block on disk I/O).

        mutate may return False to skip saving (nothing to persist).
        """
        with self._lock:
            if mutate() is False:
                return
            cfg = copy.deepcopy(self.raw_cfg)

        def save():
            try:
                config_mod.save(cfg)
                self._bump_config_revision()
            except Exception:
                log.debug("failed to persist %s", log_label, exc_info=True)

        try:
            self._persist_executor.submit(save)
        except RuntimeError:
            save()  # executor already shut down: save synchronously

    def _persist_runtime_state(self, field: str, value) -> None:
        def mutate():
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
                return False

        self._persist("runtime state", mutate)

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
        def mutate():
            self.raw_cfg.setdefault("control", {})["languages"] = languages
            self.cfg.setdefault("control", {})["languages"] = list(languages)

        self._persist("output languages", mutate)
        if self.state.target_language not in languages:
            self.state.target_language = languages[0]

    def set_inbound_languages(self, values) -> None:
        languages = _language_list(values)
        if not languages:
            return
        def mutate():
            self.raw_cfg.setdefault("inbound", {})["languages"] = languages
            self.cfg.setdefault("inbound", {})["languages"] = list(languages)

        self._persist("inbound languages", mutate)
        if self.state.inbound_language not in languages:
            self.state.inbound_language = languages[0]

    def set_ui_lang(self, value: str) -> None:
        self.state.ui_lang = value

    def close_action(self) -> str:
        return config_mod.normalize_close_action(
            self.cfg.get("ui", {}).get("close_action", "tray"))

    def set_close_action(self, value: str) -> None:
        value = config_mod.normalize_close_action(value)

        def mutate():
            self.raw_cfg.setdefault("ui", {})["close_action"] = value
            self.cfg.setdefault("ui", {})["close_action"] = value

        self._persist("close action", mutate)

    def set_overlay_font_size(self, value: int) -> None:
        value = max(18, min(72, int(value)))

        def mutate():
            self.raw_cfg.setdefault("overlay", {})["font_size"] = value
            self.cfg.setdefault("overlay", {})["font_size"] = value

        self._persist("overlay font size", mutate)
        # apply live to the running VR subtitle panel (it reads the size at
        # construction otherwise), then fold into the renderer signature
        for panel in list(self._panels):
            setter = getattr(panel, "set_font_size", None)
            if setter is not None:
                try:
                    setter(value)
                except Exception:
                    log.debug("live font-size apply failed", exc_info=True)
        self._refresh_renderer_signature()

    def last_config_version(self) -> str:
        try:
            return str(self.raw_cfg.get("meta", {}).get("last_version") or "")
        except Exception:
            return ""

    def mark_config_version_seen(self, version: str) -> None:
        def mutate():
            self.raw_cfg = config_mod.mark_version_seen(self.raw_cfg, version)
            self.cfg = config_mod.mark_version_seen(self.cfg, version)

        self._persist("config version marker", mutate)

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

    def _refresh_renderer_signature(self) -> None:
        """Panel-initiated config writes (move/resize in VR) are already live
        in the running panels; fold them into the renderer signature so the
        next restart does not rebuild the renderer for nothing."""
        with self._lock:
            if self._renderer is not None:
                self._renderer_signature = self._vr_config_signature(self.cfg)

    def set_overlay_size(self, width_m: float, height_m: float) -> None:
        try:
            width_m = float(width_m)
            height_m = float(height_m)
        except Exception:
            return
        width_m = round(max(0.45, min(1.6, width_m)), 2)
        height_m = round(max(0.10, min(0.60, height_m)), 2)

        def mutate():
            overlay = self.raw_cfg.setdefault("overlay", {})
            overlay["width_m"] = width_m
            overlay["height_m"] = height_m
            cfg_overlay = self.cfg.setdefault("overlay", {})
            cfg_overlay["width_m"] = width_m
            cfg_overlay["height_m"] = height_m

        self._persist("overlay size", mutate)
        self._refresh_renderer_signature()

    def set_wrist_transform(self, matrix, reset: bool = False) -> None:
        try:
            rows = [[float(matrix[r][c]) for c in range(4)] for r in range(3)]
            offset = [round(float(rows[r][3]), 4) for r in range(3)]
            tilt, roll = _wrist_angles_from_matrix(rows)
        except Exception:
            log.debug("invalid wrist transform", exc_info=True)
            return

        def mutate():
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

        self._persist("wrist transform", mutate)
        self._refresh_renderer_signature()

    def set_subtitle_transform(self, matrix, reset: bool = False) -> None:
        try:
            rows = [[float(matrix[r][c]) for c in range(4)] for r in range(3)]
            below = round(-float(rows[1][3]), 4)
            distance = round(-float(rows[2][3]), 4)
            tilt = round(_subtitle_tilt_from_matrix(rows), 3)
        except Exception:
            log.debug("invalid subtitle transform", exc_info=True)
            return

        def mutate():
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

        self._persist("subtitle transform", mutate)
        self._refresh_renderer_signature()

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

    def set_audio_devices(self, mic: str | None, tts: str | None,
                          on_done: Callable[[bool], None] = lambda ok: None) -> None:
        """Persist outbound.mic_device / outbound.tts_device (None = leave
        unchanged) and restart the runtime. Runs on a worker thread; safe to
        call from the VR render thread. on_done(ok) fires on the worker."""
        def apply():
            ok = False
            try:
                # snapshot/save/restart under the lifecycle lock so an
                # in-flight restart from another UI can't be clobbered
                with self._lifecycle_lock:
                    if self._closed:
                        return
                    with self._lock:
                        cfg = copy.deepcopy(self.raw_cfg)
                    ob = cfg.setdefault("outbound", {})
                    if mic is not None:
                        ob["mic_device"] = mic
                    if tts is not None:
                        ob["tts_device"] = tts
                    cfg = config_mod.apply_app_profile(cfg)
                    config_mod.save(cfg)
                    ok = self._restart_locked(cfg)
            except Exception as e:
                log.exception("failed to apply audio devices")
                self.last_error = str(e)
                self._notify()
            finally:
                try:
                    on_done(ok)
                except Exception:
                    log.debug("audio-device done callback failed", exc_info=True)

        threading.Thread(target=apply, daemon=True,
                         name="vrclt-audio-device-restart").start()

    def start(self) -> bool:
        return self.restart(self.raw_cfg)

    def restart(self, cfg: dict | None = None) -> bool:
        with self._lifecycle_lock:
            if self._closed:
                return False
            return self._restart_locked(cfg)

    def restart_async(self) -> None:
        """Fire-and-forget restart; safe to call from the Qt or VR threads."""
        threading.Thread(target=self.restart, daemon=True,
                         name="vrclt-restart").start()

    def _restart_locked(self, cfg: dict | None) -> bool:
        with self._lock:
            self._restarting = True
        try:
            # Keep the VR renderer alive across restarts (e.g. the text-only
            # toggle) unless VR-relevant config changed - tearing it down
            # makes the wrist menu / subtitles visibly blink off and on.
            # raw_cfg is mutated under self._lock by the VR/OSC/Qt threads,
            # so snapshot it under the lock before walking it.
            with self._lock:
                base_cfg = copy.deepcopy(cfg if cfg is not None else self.raw_cfg)
                renderer_sig = self._renderer_signature
            new_cfg = config_mod.apply_app_profile(base_cfg)
            keep_renderer = (
                self._renderer is not None
                and wants_vr_renderer(new_cfg)
                and self._vr_config_signature(new_cfg) == renderer_sig
            )
            self.stop(timeout=8.0, keep_renderer=keep_renderer)
            with self._lock:
                self.raw_cfg = base_cfg
                self.cfg = new_cfg
                self._sync_state_from_cfg(self.cfg)
                o = self.cfg.get("overlay", {})
                self.store.configure(max_lines=o.get("lines", 3),
                                     display_sec=o.get("display_sec", 7.0))
                self.last_error = ""
                self.status = "Starting"
                self._notify()

            # apply registration intent even if the key check below aborts
            self._app_registrar.reapply(
                bool(self.cfg.get("steamvr", {}).get("register", True)))

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

    def get_steamvr_auto_launch(self) -> bool | None:
        """Cached SteamVR auto-launch state (SteamVR owns the truth);
        None when unknown/unavailable. Refreshes in the background so the
        Qt refresh timer never blocks on OpenVR, and only while an OpenVR
        context is already alive - a cold poll would otherwise cycle a full
        openvr init/shutdown every TTL."""
        if not self._steamvr_apps.registration_supported() or not steamvr_running():
            return None
        from .vr import openvr_ctx
        with self._lock:
            ts, value = self._auto_launch_cache
            stale = (time.monotonic() - ts) > 10.0
            if not stale or self._auto_launch_refreshing or not openvr_ctx.active():
                return value
            self._auto_launch_refreshing = True
            gen = self._auto_launch_gen

        def refresh():
            new = self._steamvr_apps.get_auto_launch()
            changed = False
            with self._lock:
                self._auto_launch_refreshing = False
                # a set_steamvr_auto_launch() during the read wins
                if gen == self._auto_launch_gen:
                    changed = new != self._auto_launch_cache[1]
                    self._auto_launch_cache = (time.monotonic(), new)
            if changed:
                self._notify()

        threading.Thread(target=refresh, daemon=True,
                         name="vrclt-autolaunch-poll").start()
        return value

    def set_steamvr_auto_launch(self, value: bool) -> None:
        """Flip SteamVR auto-launch; runs on a worker thread (callable from
        the VR render thread and the Qt thread without blocking). The cache
        is updated optimistically so UIs reflect the click immediately."""
        value = bool(value)
        with self._lock:
            self._auto_launch_gen += 1
            gen = self._auto_launch_gen
            self._auto_launch_cache = (time.monotonic(), value)

        def apply():
            ok = self._steamvr_apps.set_auto_launch(value)
            with self._lock:
                if gen == self._auto_launch_gen:
                    if ok:
                        self._auto_launch_cache = (time.monotonic(), value)
                    else:
                        # roll back the optimistic value; re-read next poll
                        self._auto_launch_cache = (0.0, None)
            self._notify()

        threading.Thread(target=apply, daemon=True,
                         name="vrclt-steamvr-autolaunch").start()

    def shutdown(self, timeout: float = 8.0) -> None:
        """Stop for good: a queued restart() arriving after this is a no-op."""
        with self._lifecycle_lock:
            self._closed = True
            self._app_registrar.stop()
            self.stop(timeout=timeout)
        # flush queued config saves (late _persist calls fall back to sync)
        self._persist_executor.shutdown(wait=True)

    def stop(self, timeout: float = 8.0, keep_renderer: bool = False) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            loop = self._loop
            stop_event = self._stop_event
            renderer = self._renderer
            # the AppState outlives pipelines; stop their state reactions
            for p in (self._pipeline, self._inbound):
                if p is not None:
                    try:
                        p.detach()
                    except Exception:
                        pass
            if loop is not None and stop_event is not None:
                try:
                    loop.call_soon_threadsafe(stop_event.set)
                except Exception:
                    pass
            if renderer is not None and not keep_renderer:
                renderer.stop()
                self._renderer_signature = None
                # panels die with the renderer; drop their subscriptions on
                # the persistent state/store so they can be collected
                for p in self._panels:
                    try:
                        p.detach()
                    except Exception:
                        pass
                self._panels = []
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
            if not keep_renderer:
                self._renderer = None
            if not self._restarting:
                self._set_status("Stopped")

    def _start_runtime(self, key: str) -> bool:
        state = self.state
        store = self.store
        cfg = self.cfg

        pipeline = inbound = control = None
        panels: list = []
        try:
            pipeline = OutboundPipeline(cfg, key, state)
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

            # a renderer surviving from the previous run (unchanged VR config)
            # keeps its panels: they read the persistent state/store and query
            # status via self.connected, so no rebuild is needed
            renderer = self._renderer
            if renderer is None and wants_vr_renderer(cfg):
                o = cfg.get("overlay", {})
                if inbound and o.get("enabled", True):
                    panels.append(make_subtitle_panel(
                        cfg, store, state,
                        on_transform_changed=self.set_subtitle_transform,
                        on_size_changed=self.set_overlay_size))
                if cfg.get("wrist_ui", {}).get("enabled", True):
                    panels.insert(0, make_wrist_panel(
                        cfg, state,
                        get_status=self.connected,
                        on_text_only_toggle=self.set_text_only,
                        on_transform_changed=self.set_wrist_transform))
                if cfg.get("steamvr", {}).get("dashboard_panel", True):
                    panels.append(make_dashboard_panel(
                        cfg, state,
                        get_status=self.connected,
                        on_text_only_toggle=self.set_text_only,
                        on_font_size=self.set_overlay_font_size,
                        get_font_size=lambda: int(
                            self.cfg.get("overlay", {}).get("font_size", 27)),
                        get_auto_launch=self.get_steamvr_auto_launch,
                        set_auto_launch=self.set_steamvr_auto_launch,
                        on_restart=self.restart_async,
                        get_devices=device_names,
                        get_mic_device=lambda: str(
                            self.cfg.get("outbound", {}).get("mic_device", "") or ""),
                        get_tts_device=lambda: str(
                            self.cfg.get("outbound", {}).get("tts_device", "") or ""),
                        set_audio_devices=self.set_audio_devices))
                if panels:
                    from .vr.render import VrRenderer
                    renderer = VrRenderer(panels, can_start=steamvr_running)
                    renderer.start()
                    self._panels = panels
                    self._renderer_signature = self._vr_config_signature(cfg)
        except Exception:
            # unwind subscriptions on the persistent state/store, or every
            # failed start would leak (and duplicate) listeners forever
            for p in (pipeline, inbound, *panels):
                if p is not None:
                    try:
                        p.detach()
                    except Exception:
                        pass
            if control is not None:
                try:
                    control.stop()
                except Exception:
                    pass
            raise

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
