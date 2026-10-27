# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Protocol


class ProcessCounters(Protocol):
    """Cheap CPU and memory counters of the host and of registered processes.

    Each read is a small file read with no child process, so a UI loop may
    call it. A read returns ``None`` when the host cannot tell.
    """

    clock_ticks: int
    """Counter ticks per second of ``process_cpu_ticks``."""

    def system_cpu_times(self) -> tuple[int, int] | None:
        """Return ``(total, idle)`` ticks of all CPUs since boot."""
        ...

    def process_cpu_ticks(self, pid: int) -> int | None:
        """Return the user plus system CPU ticks of *pid*."""
        ...

    def process_resident_bytes(self, pid: int) -> int | None:
        """Return the resident memory of *pid*."""
        ...
