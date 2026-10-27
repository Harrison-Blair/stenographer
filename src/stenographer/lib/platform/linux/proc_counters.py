# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
from pathlib import Path

from stenographer.lib.platform.linux.cpu import (
    PROC_ROOT,
    read_process_cpu_ticks,
    read_process_resident_bytes,
    read_system_cpu_times,
)


class LinuxProcessCounters:
    """``ProcessCounters`` from ``/proc``; the root is injectable for tests."""

    def __init__(
        self,
        proc_root: Path = PROC_ROOT,
        *,
        clock_ticks: int | None = None,
        page_size: int | None = None,
    ) -> None:
        self._proc_root = proc_root
        self.clock_ticks = os.sysconf("SC_CLK_TCK") if clock_ticks is None else clock_ticks
        self._page_size = os.sysconf("SC_PAGE_SIZE") if page_size is None else page_size

    def system_cpu_times(self) -> tuple[int, int] | None:
        return read_system_cpu_times(self._proc_root)

    def process_cpu_ticks(self, pid: int) -> int | None:
        return read_process_cpu_ticks(pid, self._proc_root)

    def process_resident_bytes(self, pid: int) -> int | None:
        return read_process_resident_bytes(pid, self._proc_root, page_size=self._page_size)
