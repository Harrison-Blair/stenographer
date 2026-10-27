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
# user nice system idle iowait irq softirq steal; guest time is already in user.
_SYSTEM_CPU_FIELDS = 8
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

    ``None`` when the affinity set is empty or any topology file is missing or
    unreadable — a partial count would silently under-report the machine.
    """
    if not affinity:
        return None
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


def read_system_cpu_times(proc_root: Path = PROC_ROOT) -> tuple[int, int] | None:
    """Return ``(total, idle)`` jiffies of all CPUs from ``/proc/stat``; idle counts iowait."""
    try:
        with (proc_root / "stat").open(encoding="ascii") as stat:
            first = stat.readline().split()
        if not first or first[0] != "cpu":
            return None
        values = [int(value) for value in first[1 : 1 + _SYSTEM_CPU_FIELDS]]
    except (OSError, ValueError):
        return None
    if len(values) < 5:
        return None
    return sum(values), values[3] + values[4]


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
