# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations


class NullProcessCounters:
    """``ProcessCounters`` of a host that reports no data; every read is ``None``."""

    clock_ticks = 100

    def system_cpu_times(self) -> tuple[int, int] | None:
        return None

    def process_cpu_ticks(self, pid: int) -> int | None:
        return None

    def process_resident_bytes(self, pid: int) -> int | None:
        return None
