# SPDX-License-Identifier: GPL-3.0-or-later
"""Sample the engine card from hub services and ``/proc``."""

from __future__ import annotations

import math
import os
import time
from collections import deque
from typing import TYPE_CHECKING

from stenographer.cli.hub.engine_status import EngineStatus
from stenographer.lib.platform import current_platform
from stenographer.lib.transcribe.bark_download import MODEL_DIRNAME

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.platform.process_counters import ProcessCounters

_HISTORY_SECONDS = 60


class EngineSampler:
    """Read the engine state on demand and the gauges once per ``sample`` call.

    The hub calls ``sample`` once per second on its event loop: each call reads
    a few small counter files (``/proc`` on Linux) and starts no process. App CPU counts the hub
    process and the ASR workers of the services, as a share of all CPUs.

    The services give ``session`` (the recording ``LiveSession``),
    ``stopping_sessions`` (stopping sessions in stop order) and
    ``files_engine``; each one is optional.
    """

    def __init__(
        self,
        services,
        *,
        counters: ProcessCounters | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        pid: int | None = None,
        cpu_count: int | None = None,
    ) -> None:
        self._services = services
        self._counters = counters if counters is not None else current_platform().process_counters()
        self._monotonic = monotonic
        self._pid = os.getpid() if pid is None else pid
        self._cpu_count = len(os.sched_getaffinity(0)) if cpu_count is None else cpu_count
        self._sampled_at: float | None = None
        self._process_ticks: dict[int, int] = {}
        self._system_times: tuple[int, int] | None = None
        self._cpu_app: float | None = None
        self._cpu_all: float | None = None
        self._ram_app: int | None = None
        self._history: deque[float] = deque(maxlen=_HISTORY_SECONDS)

    def sample(self) -> None:
        """Read the gauges once; CPU needs a previous sample, RAM does not."""
        now = self._monotonic()
        elapsed = None if self._sampled_at is None else now - self._sampled_at
        self._sampled_at = now

        ticks: dict[int, int] = {}
        ram = 0
        for pid in (self._pid, *self._worker_pids()):
            process_ticks = self._counters.process_cpu_ticks(pid)
            resident = self._counters.process_resident_bytes(pid)
            if process_ticks is None or resident is None:
                continue
            ticks[pid] = process_ticks
            ram += resident
        hub_read = self._pid in ticks
        self._ram_app = ram if hub_read else None
        if hub_read and elapsed and self._process_ticks:
            # A worker that started since the last sample counts from zero ticks.
            delta = sum(
                max(0, value - self._process_ticks.get(pid, 0)) for pid, value in ticks.items()
            )
            seconds = delta / self._counters.clock_ticks
            self._cpu_app = min(100.0, 100.0 * seconds / elapsed / self._cpu_count)
            self._history.append(self._cpu_app)
        else:
            self._cpu_app = None
        self._process_ticks = ticks if hub_read else {}

        system = self._counters.system_cpu_times()
        previous, self._system_times = self._system_times, system
        self._cpu_all = None
        if system is not None and previous is not None:
            total = system[0] - previous[0]
            idle = system[1] - previous[1]
            if total > 0:
                self._cpu_all = max(0.0, min(100.0, 100.0 * (1 - idle / total)))

    @property
    def cpu_all_percent(self) -> float | None:
        """Return the system CPU gauge alone, without reading the services."""
        return self._cpu_all

    def snapshot(self) -> EngineStatus:
        """Return the card data; the state line reads the services now."""
        return EngineStatus(
            model=MODEL_DIRNAME,
            state=self._state(),
            cpu_app_percent=self._cpu_app,
            cpu_all_percent=self._cpu_all,
            ram_app_bytes=self._ram_app,
            cpu_history=tuple(self._history),
        )

    def _sessions(self) -> tuple:
        services = self._services
        session = getattr(services, "session", None)
        stopping = tuple(getattr(services, "stopping_sessions", ()))
        return stopping + ((session,) if session is not None else ())

    def _workers(self) -> tuple:
        engine = getattr(self._services, "files_engine", None)
        return self._sessions() + ((engine,) if engine is not None else ())

    def _worker_pids(self) -> tuple[int, ...]:
        return tuple(pid for owner in self._workers() for pid in getattr(owner, "process_ids", ()))

    def _state(self) -> str:
        for session in self._sessions():
            progress = session.relabel_progress
            if progress is not None:
                return f"relabeling {progress[0]} of {progress[1]}"
        engine = getattr(self._services, "files_engine", None)
        job = None if engine is None else engine.active_job
        if job is not None and job.state == "running":
            return f"transcribing {job.progress.percent}%"
        session = getattr(self._services, "session", None)
        if session is not None:
            queued = session.queue_depth
            return f"ready · {queued} queued" if queued else "ready"
        deadlines = [
            deadline
            for owner in self._workers()
            if (deadline := owner.idle_unload_deadline) is not None
        ]
        if deadlines:
            seconds = max(0, math.ceil(min(deadlines) - self._monotonic()))
            return f"idle · unloads in {seconds} s"
        return "idle · unloaded"
