"""Periodic memory diagnostics for leak hunting.

Logs one compact line per minute to the normal log file:

    diag: rss=412.3MB vms=980.1MB threads=34 gc_objects=182034
          state_ls=5 store_ls=2 panels=3

Reading it: if gc_objects stays flat while rss climbs, the growth is
native/allocator-side; if gc_objects climbs with rss, set the environment
variable VRCLT_TRACEMALLOC=1 before launch - the top allocation-growth call
sites are then logged every 5 minutes and name the leaking line directly.
"""
from __future__ import annotations

import gc
import logging
import os
import threading

import psutil

log = logging.getLogger(__name__)

INTERVAL_SEC = 60.0
TRACE_EVERY_TICKS = 5   # tracemalloc diff every 5 minutes
TRACE_TOP = 5
TRACE_ENV = "VRCLT_TRACEMALLOC"


class MemoryDiagnostics:
    """Daemon thread owned by AppController; survives runtime restarts so
    growth across restarts (the interesting case) stays visible."""

    def __init__(self, controller):
        self._controller = controller
        self._proc = psutil.Process()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._trace = bool(os.environ.get(TRACE_ENV, "").strip())
        self._ticks = 0
        self._last_snapshot = None
        self._last_rss: float | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        if self._trace:
            import tracemalloc
            tracemalloc.start(10)
            log.info("diag: tracemalloc enabled (%s=1)", TRACE_ENV)
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="vrclt-memdiag")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(INTERVAL_SEC):
            try:
                self._tick()
            except Exception:
                log.debug("diag tick failed", exc_info=True)

    def _tick(self) -> None:
        mem = self._proc.memory_info()
        c = self._controller
        # delta and handle count: the growth episodes are intermittent and
        # leave no other trace in the log, so each line has to say on its own
        # whether memory moved and whether OS handles moved with it. Handles
        # climbing alongside rss means a handle/GDI leak (device, context or
        # overlay churn); rss alone means a plain native heap leak.
        rss_mb = mem.rss / 1e6
        delta = rss_mb - self._last_rss if self._last_rss is not None else 0.0
        self._last_rss = rss_mb
        try:
            handles = self._proc.num_handles()
        except Exception:
            handles = -1
        renderer = getattr(c, "_renderer", None)
        log.info(
            "diag: rss=%.1fMB (%+.1f) vms=%.1fMB threads=%d handles=%d "
            "gc_objects=%d state_ls=%d store_ls=%d panels=%d vr=%s",
            rss_mb, delta, mem.vms / 1e6, threading.active_count(), handles,
            len(gc.get_objects()),
            len(getattr(c.state, "_listeners", ())),
            len(getattr(c.store, "_listeners", ())),
            len(getattr(c, "_panels", ())),
            "on" if getattr(renderer, "_thread", None) is not None else "off")
        self._ticks += 1
        if self._trace and self._ticks % TRACE_EVERY_TICKS == 0:
            self._log_tracemalloc()

    def _log_tracemalloc(self) -> None:
        import tracemalloc
        snap = tracemalloc.take_snapshot()
        snap = snap.filter_traces((
            tracemalloc.Filter(False, tracemalloc.__file__),
            tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        ))
        if self._last_snapshot is not None:
            for stat in snap.compare_to(self._last_snapshot, "lineno")[:TRACE_TOP]:
                log.info("diag/trace: %s", stat)
        else:
            for stat in snap.statistics("lineno")[:TRACE_TOP]:
                log.info("diag/trace: %s", stat)
        self._last_snapshot = snap
