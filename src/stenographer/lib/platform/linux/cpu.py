# SPDX-License-Identifier: GPL-3.0-or-later
"""CPU topology from sysfs and CPU and memory counters from ``/proc``.

``sched_getaffinity`` gives the CPUs this process may actually run on (cgroup
and taskset aware); ``/sys/devices/system/cpu/cpuN/topology`` collapses
hyperthread siblings onto their ``(package, core)`` pair. Anything unreadable
means "cannot tell" — the core owns the fallback, not this module.

The ``/proc`` readers read one small file each and start no process, so a UI
loop may call them. Each returns ``None`` when the file is missing or malformed.
"""

from __future__ import annotations

import os
from pathlib import Path

TOPOLOGY_ROOT = Path("/sys/devices/system/cpu")
PROC_ROOT = Path("/proc")
# utime and stime follow the command name at fields 14 and 15 of /proc/PID/stat.
_UTIME_AFTER_NAME = 11


def physical_core_count() -> int | None:
    """Distinct physical cores among the affinity-visible CPUs, or ``None``."""
    try:
        affinity = set(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return None
    return count_physical_cores(affinity, TOPOLOGY_ROOT)


def count_physical_cores(affinity: set[int], topology_root: Path) -> int | None:
    """Count unique ``(physical_package_id, core_id)`` pairs under *topology_root*.

    ``None`` when any topology file is missing or
    unreadable — a partial count would silently under-report the machine.
    """
    physical: set[tuple[str, str]] = set()
    try:
        for cpu in affinity:
            topology = topology_root / f"cpu{cpu}" / "topology"
            package = (topology / "physical_package_id").read_text(encoding="ascii").strip()
            core = (topology / "core_id").read_text(encoding="ascii").strip()
            physical.add((package, core))
    except (OSError, ValueError):
        return None
    return len(physical)


def read_process_cpu_ticks(pid: int, proc_root: Path = PROC_ROOT) -> int | None:
    """Return user plus system clock ticks of *pid* from ``/proc/PID/stat``."""
    try:
        text = (proc_root / str(pid) / "stat").read_text(encoding="ascii", errors="replace")
        fields = text[text.rindex(")") + 1 :].split()
        return int(fields[_UTIME_AFTER_NAME]) + int(fields[_UTIME_AFTER_NAME + 1])
    except (OSError, ValueError, IndexError):
        return None


def read_process_resident_bytes(
    pid: int, proc_root: Path = PROC_ROOT, *, page_size: int | None = None
) -> int | None:
    """Return the resident memory of *pid* from ``/proc/PID/statm``."""
    try:
        pages = int((proc_root / str(pid) / "statm").read_text(encoding="ascii").split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return pages * (page_size if page_size is not None else os.sysconf("SC_PAGE_SIZE"))


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

    def process_cpu_ticks(self, pid: int) -> int | None:
        return read_process_cpu_ticks(pid, self._proc_root)

    def process_resident_bytes(self, pid: int) -> int | None:
        return read_process_resident_bytes(pid, self._proc_root, page_size=self._page_size)
