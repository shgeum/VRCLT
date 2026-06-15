"""vrclt CLI.

  python -m vrclt devices              list WASAPI devices, check VB-Cable
  python -m vrclt sinetest [SUBSTR]    play a test tone (default: CABLE Input)
  python -m vrclt miccheck [SUBSTR]    capture 2s from the mic, report level
  python -m vrclt livetest             connect a Gemini Live session once
  python -m vrclt wristtest            wrist menu only (SteamVR; no API key needed)
  python -m vrclt run                  run the outbound pipeline (M1)
"""
import argparse
import asyncio
import logging
import signal
import sys
import time

from . import config as config_mod
from . import i18n
from . import logging_setup

log = logging.getLogger("vrclt")


def cmd_devices(_args) -> None:
    from .audio import devices
    print(devices.list_devices())


def cmd_sinetest(args) -> None:
    from .audio import devices
    target = args.device if args.device is not None else "CABLE Input"
    devices.sine_test(target)
    print("sine test done - check the target device (VRChat mic test, etc.)")


def cmd_miccheck(args) -> None:
    import numpy as np
    from .audio.mic_in import MicCapture
    print("Speak normally for ~4 seconds to measure your voice level...")
    # threshold 0 = capture everything (no gating) so we see the raw level
    mic = MicCapture(args.device or "", voice_rms_threshold=0.0)
    mic.start()
    time.sleep(4.0)
    mic.stop()
    chunks = mic.drain()
    if not chunks:
        print("NO AUDIO captured - check the input device")
        return
    arr = np.frombuffer(b"".join(chunks), dtype=np.int16).astype(np.float64)
    n = 512
    peaks = [float(np.sqrt(np.mean(arr[i:i + n] ** 2)))
             for i in range(0, len(arr) - n, n)]
    peak = max(peaks) if peaks else 0.0
    avg = float(np.sqrt(np.mean(arr ** 2)))
    suggested = max(40, int(peak * 0.4))
    print(f"captured {len(arr) / 16000.0:.1f}s: avg RMS={avg:.0f}, peak RMS={peak:.0f}")
    print(f"-> set audio.voice_rms_threshold to about {suggested} "
          f"(below your peak {peak:.0f}, above background noise)")


def cmd_livetest(args) -> None:
    cfg = config_mod.load()
    key = config_mod.api_key(cfg)
    if not key:
        print("no API key: set api_key in config.yaml or GEMINI_API_KEY env var")
        sys.exit(1)

    async def main():
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        live_cfg = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            translation_config=types.TranslationConfig(
                target_language_code=cfg["outbound"]["target_language"],
                echo_target_language=True,
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )
        print(f"connecting: {cfg['model']} (target={cfg['outbound']['target_language']})")
        t0 = time.time()
        async with client.aio.live.connect(model=cfg["model"], config=live_cfg) as session:
            print(f"CONNECTED in {time.time() - t0:.1f}s - sending 0.5s silence")
            await session.send_realtime_input(
                audio=types.Blob(data=b"\x00" * 16000, mime_type="audio/pcm;rate=16000"))
            await session.send_realtime_input(audio_stream_end=True)
            try:
                async with asyncio.timeout(6):
                    async for response in session.receive():
                        sc = response.server_content
                        if sc and (sc.input_transcription or sc.output_transcription):
                            print("transcription event received")
                            break
                        if sc and sc.turn_complete:
                            print("turn complete")
                            break
            except TimeoutError:
                pass  # silence in, silence out: no events is fine
        print("LIVE TEST OK - API key, model access and SDK wire format all work")

    asyncio.run(main())


def _make_wrist_panel(cfg, state, get_status):
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


def _make_subtitle_panel(cfg, store, state):
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


def cmd_overlaytest(_args) -> None:
    import itertools
    from .state import AppState
    from .subtitles import SubtitleStore
    from .vr.render import VrRenderer
    cfg = config_mod.load()
    o = cfg.get("overlay", {})
    store = SubtitleStore(max_lines=o.get("lines", 3), display_sec=o.get("display_sec", 7.0))
    state = AppState(subtitles_on=True, inbound_language=cfg["inbound"]["target_language"])
    renderer = VrRenderer([_make_subtitle_panel(cfg, store, state)])
    renderer.start()
    print("subtitle overlay running with demo lines - check the headset. Ctrl+C to quit.")
    samples = itertools.cycle([
        ("Hello, nice to meet you!", "안녕하세요, 만나서 반가워요!", "en"),
        ("今日はいい天気ですね", "오늘 날씨가 좋네요", "ja"),
        ("你好，最近怎么样？", "안녕, 요즘 어때?", "zh-Hans"),
    ])
    try:
        while True:
            src, dst, lang = next(samples)
            for i in range(1, len(dst) + 1, 4):
                store.set_partial(src, dst[:i])
                time.sleep(0.15)
            store.add_final(src, dst, lang)
            time.sleep(3.0)
    except KeyboardInterrupt:
        renderer.stop()
        print("stopped")


def cmd_wristtest(_args) -> None:
    from .state import AppState
    from .vr.render import VrRenderer
    cfg = config_mod.load()
    state = AppState(translation_on=True,
                     target_language=cfg["outbound"]["target_language"],
                     inbound_language=cfg["inbound"]["target_language"],
                     ui_lang=i18n.detect(cfg.get("ui", {}).get("lang", "")))
    state.subscribe(lambda f, v: print(f"  state changed: {f} = {v}"))
    renderer = VrRenderer([_make_wrist_panel(cfg, state, get_status=lambda: True)])
    renderer.start()
    print("wrist menu running - put on the headset and look at your wrist.")
    print("point with the other controller: TRIGGER = click, GRIP = move. Ctrl+C to quit.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        renderer.stop()
        print("stopped")


def cmd_resetpos(_args) -> None:
    """Delete saved overlay positions (works even when the app is not running)."""
    from .vr.subtitle_overlay import TRANSFORM_PATH as SUB_T
    from .vr.wrist_ui import TRANSFORM_PATH as WRIST_T
    for name, path in (("wrist panel", WRIST_T), ("subtitles", SUB_T)):
        try:
            path.unlink()
            print(f"reset {name}: deleted {path}")
        except FileNotFoundError:
            print(f"{name}: already at defaults")


def cmd_desktoptest(_args) -> None:
    import itertools
    import threading
    from .state import AppState
    from .subtitles import SubtitleStore
    from .desktop.ui import DesktopUI
    cfg = config_mod.load()
    state = AppState(target_language=cfg["outbound"]["target_language"],
                     inbound_language=cfg["inbound"]["target_language"],
                     ui_lang=i18n.detect(cfg.get("ui", {}).get("lang", "")))
    o = cfg.get("overlay", {})
    d = cfg.get("desktop", {})
    store = SubtitleStore(max_lines=o.get("lines", 3), display_sec=o.get("display_sec", 7.0))
    ui = DesktopUI(
        state, store,
        out_languages=cfg["control"]["languages"],
        sub_languages=cfg["inbound"]["languages"],
        get_status=lambda: True,
        font_size=d.get("subtitle_font_size", 30), opacity=d.get("opacity", 0.85),
        width=d.get("subtitle_width", 900), show_source=o.get("show_source", False),
        lines=o.get("lines", 3))

    def feeder():
        samples = itertools.cycle([
            ("Hello, nice to meet you!", "안녕하세요, 만나서 반가워요!", "en"),
            ("今日はいい天気ですね", "오늘 날씨가 좋네요", "ja"),
            ("你好，最近怎么样？", "안녕, 요즘 어때?", "zh-Hans"),
        ])
        while not ui._stopping:
            store.add_final(*next(samples))
            time.sleep(3.0)

    threading.Thread(target=feeder, daemon=True).start()
    print("desktop UI demo - drag both windows, click buttons, ✕ or Ctrl+C to quit.")
    ui.run_blocking()  # main thread
    ui.request_stop()
    print("stopped")


def _steamvr_running() -> bool:
    import psutil
    for p in psutil.process_iter(["name"]):
        n = (p.info["name"] or "").lower()
        if n in ("vrmonitor.exe", "vrserver.exe"):
            return True
    return False


def _resolve_ui_mode(cfg) -> str:
    mode = cfg.get("ui", {}).get("mode", "auto")
    if mode == "auto":
        return "vr" if _steamvr_running() else "desktop"
    return mode if mode in ("vr", "desktop") else "vr"


async def _gather_pipelines(stop, pipeline, inbound) -> None:
    """Run outbound (+ inbound) so one crashing doesn't kill the other."""
    async def safe(coro, name):
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s pipeline crashed (the rest keep running)", name)

    tasks = [safe(pipeline.run(stop), "outbound")]
    if inbound:
        tasks.append(safe(inbound.run(stop), "inbound"))
    await asyncio.gather(*tasks)


def _start_web(cfg, state, store, get_status):
    w = cfg.get("web", {})
    if not w.get("enabled", True):
        return None
    try:
        from .web.server import create_app, WebServer
        port = w.get("port", 8765)
        server = WebServer(create_app(state, store, cfg, get_status), port)
        server.start()
        url = f"http://127.0.0.1:{port}"
        log.info("web UI: %s", url)
        if w.get("auto_open", True):
            import threading
            import webbrowser
            # small delay so uvicorn is listening before the browser hits it
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        return server
    except Exception:
        log.exception("web UI failed to start")
        return None


def _persist_ui_lang(cfg, field, value):
    """Save the UI display language to config whenever any UI changes it."""
    if field != "ui_lang":
        return
    try:
        cfg.setdefault("ui", {})["lang"] = value
        config_mod.save(cfg)
    except Exception:
        log.debug("failed to persist ui.lang", exc_info=True)


def _build_core(cfg, key, state):
    """Build the audio pipelines + OSC control shared by both UI modes."""
    from .control.osc_listener import OscControl
    from .gemini.pipeline import InboundPipeline, OutboundPipeline
    from .subtitles import SubtitleStore

    state.subscribe(lambda f, v: _persist_ui_lang(cfg, f, v))
    pipeline = OutboundPipeline(cfg, key, state)
    o = cfg.get("overlay", {})
    store = SubtitleStore(max_lines=o.get("lines", 3), display_sec=o.get("display_sec", 7.0))
    inbound = None
    if cfg["inbound"].get("enabled", False):
        inbound = InboundPipeline(cfg, key, store, state)
        # echo guard: while game audio plays, others' voices bleed into the
        # mic - raise the outbound gate so they aren't translated as my speech
        mult = float(cfg["audio"].get("echo_guard_multiplier", 4.0))
        if mult > 1.0:
            ib = inbound
            pipeline.mic.set_threshold_boost(
                lambda: mult if (state.translation_on and ib.tap.active(1.0)) else 1.0)
    ctl = cfg.get("control", {})
    control = None
    if ctl.get("enabled", True):
        control = OscControl(
            state,
            listen_port=ctl.get("osc_listen_port", 9001),
            param_enabled=ctl.get("param_enabled", "VRCLT_Enabled"),
            param_lang=ctl.get("param_lang", "VRCLT_Lang"),
            languages=ctl.get("languages", ["en"]),
        )
        control.start()
    return pipeline, inbound, control, store


def cmd_run(_args) -> None:
    cfg = config_mod.load()
    key = config_mod.api_key(cfg)
    if not key:
        print("no API key: set api_key in config.yaml or GEMINI_API_KEY env var")
        sys.exit(1)
    ui_mode = _resolve_ui_mode(cfg)
    log.info("UI mode: %s", ui_mode)
    if ui_mode == "desktop":
        _run_desktop_mode(cfg, key)
    else:
        _run_vr_mode(cfg, key)


def _run_vr_mode(cfg, key) -> None:
    from .state import AppState

    async def main():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass  # Windows: rely on KeyboardInterrupt
        state = AppState(translation_on=True,
                         target_language=cfg["outbound"]["target_language"],
                         subtitles_on=True,
                         inbound_language=cfg["inbound"]["target_language"],
                         ui_lang=i18n.detect(cfg.get("ui", {}).get("lang", "")))
        pipeline, inbound, control, store = _build_core(cfg, key, state)
        panels = []
        o = cfg.get("overlay", {})
        if inbound and o.get("enabled", True):
            panels.append(_make_subtitle_panel(cfg, store, state))
        if cfg.get("wrist_ui", {}).get("enabled", True):
            panels.insert(0, _make_wrist_panel(
                cfg, state, get_status=lambda: pipeline.session.connected))
        renderer = None
        if panels:
            from .vr.render import VrRenderer
            renderer = VrRenderer(panels)
            renderer.start()
        web = _start_web(cfg, state, store, lambda: pipeline.session.connected)
        tray = None
        if cfg.get("web", {}).get("tray", True):
            from .tray import Tray
            tray = Tray(state, cfg.get("web", {}).get("port", 8765),
                        on_quit=lambda: loop.call_soon_threadsafe(stop.set))
            tray.start()
        log.info("pipelines starting: outbound%s (Ctrl+C to stop)",
                 " + inbound" if inbound else "")
        try:
            await _gather_pipelines(stop, pipeline, inbound)
        except asyncio.CancelledError:
            pass
        finally:
            if control:
                control.stop()
            if renderer:
                renderer.stop()
            if web:
                web.stop()
            if tray:
                tray.stop()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped")


def _run_desktop_mode(cfg, key) -> None:
    """tkinter on the MAIN thread; audio pipelines on a worker thread."""
    import threading
    from .state import AppState
    from .desktop.ui import DesktopUI

    state = AppState(translation_on=True,
                     target_language=cfg["outbound"]["target_language"],
                     subtitles_on=True,
                     inbound_language=cfg["inbound"]["target_language"],
                     ui_lang=i18n.detect(cfg.get("ui", {}).get("lang", "")))
    pipeline, inbound, control, store = _build_core(cfg, key, state)
    o = cfg.get("overlay", {})
    d = cfg.get("desktop", {})
    ctl = cfg.get("control", {})
    desktop = DesktopUI(
        state, store,
        out_languages=ctl.get("languages", ["en"]),
        sub_languages=cfg["inbound"].get("languages", ["ko"]),
        get_status=lambda: pipeline.session.connected,
        font_size=d.get("subtitle_font_size", 30),
        opacity=d.get("opacity", 0.85),
        width=d.get("subtitle_width", 900),
        show_source=o.get("show_source", False),
        lines=o.get("lines", 3),
    )

    holder = {}
    ready = threading.Event()

    def worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        astop = asyncio.Event()
        holder["loop"], holder["astop"] = loop, astop
        ready.set()

        try:
            loop.run_until_complete(_gather_pipelines(astop, pipeline, inbound))
        except Exception:
            log.exception("pipeline worker crashed")
        finally:
            try:
                loop.close()
            except Exception:
                pass

    t = threading.Thread(target=worker, daemon=True, name="vrclt-pipelines")
    t.start()
    ready.wait(2.0)
    web = _start_web(cfg, state, store, lambda: pipeline.session.connected)
    tray = None
    if cfg.get("web", {}).get("tray", True):
        from .tray import Tray
        tray = Tray(state, cfg.get("web", {}).get("port", 8765),
                    on_quit=desktop.request_stop)
        tray.start()
    log.info("pipelines starting: outbound%s (desktop mode; close the control "
             "window or Ctrl+C to stop)", " + inbound" if inbound else "")
    try:
        desktop.run_blocking()  # blocks on the main thread until closed
    finally:
        loop = holder.get("loop")
        astop = holder.get("astop")
        if loop is not None and astop is not None:
            loop.call_soon_threadsafe(astop.set)
        t.join(timeout=8)
        if control:
            control.stop()
        if web:
            web.stop()
        if tray:
            tray.stop()
        desktop.request_stop()
        print("\nstopped")


def main() -> None:
    parser = argparse.ArgumentParser(prog="vrclt", description="VRChat Live Translator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices")
    p = sub.add_parser("sinetest"); p.add_argument("device", nargs="?", default=None)
    p = sub.add_parser("miccheck"); p.add_argument("device", nargs="?", default=None)
    sub.add_parser("livetest")
    sub.add_parser("wristtest")
    sub.add_parser("overlaytest")
    sub.add_parser("desktoptest")
    sub.add_parser("resetpos")
    sub.add_parser("run")
    # no subcommand (e.g. double-clicked exe) -> run
    argv = sys.argv[1:] or ["run"]
    args = parser.parse_args(argv)

    cfg = config_mod.load()
    log_file = logging_setup.setup(cfg.get("log_level", "INFO"))
    log.debug("log file: %s", log_file)

    {"devices": cmd_devices, "sinetest": cmd_sinetest, "miccheck": cmd_miccheck,
     "livetest": cmd_livetest, "wristtest": cmd_wristtest,
     "overlaytest": cmd_overlaytest, "desktoptest": cmd_desktoptest,
     "resetpos": cmd_resetpos, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
