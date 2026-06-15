"""Localhost web UI: runtime control + live subtitles + settings editor.

Runs uvicorn on its own thread (signal handlers disabled - not main thread).
AppState/SubtitleStore are thread-safe, so handlers touch them directly.
"""
import asyncio
import json
import logging
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .. import config as config_mod
from .. import i18n

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


def _state_dict(state, get_status) -> dict:
    return {
        "translation_on": state.translation_on,
        "subtitles_on": state.subtitles_on,
        "target_language": state.target_language,
        "inbound_language": state.inbound_language,
        "ui_lang": state.ui_lang,
        "connected": bool(get_status()),
    }


def create_app(state, store, cfg, get_status):
    app = FastAPI(title="vrclt")

    @app.get("/")
    async def index():
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/meta")
    async def meta():
        return {
            "out_languages": cfg.get("control", {}).get("languages", ["en"]),
            "sub_languages": cfg.get("inbound", {}).get("languages", ["ko"]),
        }

    @app.get("/api/i18n")
    async def get_i18n():
        return {
            "langs": i18n.LANGS,
            "labels": i18n.UI_LANG_LABELS,
            "strings": i18n.STRINGS,
            "lang": state.ui_lang,
        }

    @app.get("/api/devices")
    async def list_devices():
        import sounddevice as sd
        from ..audio.devices import wasapi_index
        try:
            wi = wasapi_index()
        except Exception:
            wi = None
        ins, outs, seen_i, seen_o = [], [], set(), set()
        try:
            for d in sd.query_devices():
                if wi is not None and d["hostapi"] != wi:
                    continue
                n = d["name"]
                if d["max_input_channels"] > 0 and n not in seen_i:
                    seen_i.add(n); ins.append(n)
                if d["max_output_channels"] > 0 and n not in seen_o:
                    seen_o.add(n); outs.append(n)
        except Exception:
            log.exception("device enumeration failed")
        return {"inputs": ins, "outputs": outs}

    @app.get("/api/state")
    async def get_state():
        return _state_dict(state, get_status)

    @app.post("/api/state")
    async def set_state(body: dict):
        if "translation_on" in body:
            state.translation_on = bool(body["translation_on"])
        if "subtitles_on" in body:
            state.subtitles_on = bool(body["subtitles_on"])
        if body.get("target_language"):
            state.target_language = body["target_language"]
        if body.get("inbound_language"):
            state.inbound_language = body["inbound_language"]
        if body.get("ui_lang"):
            state.ui_lang = body["ui_lang"]  # listener persists ui.lang to config
        return _state_dict(state, get_status)

    @app.get("/api/config")
    async def get_config():
        return config_mod.load()

    @app.post("/api/config")
    async def save_config(body: dict):
        config_mod.save(body)
        return {"ok": True,
                "note": "Saved. Restart vrclt to apply device / API key / audio changes."}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        last = None
        try:
            while True:
                finals, partial = store.snapshot()
                snap = {
                    "state": _state_dict(state, get_status),
                    "subs": [{"src": s, "dst": d, "lang": lg} for s, d, lg in finals],
                    "partial": {"src": partial[0], "dst": partial[1]},
                }
                payload = json.dumps(snap, ensure_ascii=False)
                if payload != last:
                    last = payload
                    await websocket.send_text(payload)
                await asyncio.sleep(0.25)
        except (WebSocketDisconnect, Exception):
            return

    return app


class WebServer:
    def __init__(self, app, port: int):
        cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self._server = uvicorn.Server(cfg)
        self._server.install_signal_handlers = lambda: None  # not the main thread
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.run, daemon=True, name="vrclt-web")
        self._thread.start()

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
