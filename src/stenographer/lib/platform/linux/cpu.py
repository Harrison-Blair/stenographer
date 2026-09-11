# SPDX-License-Identifier: GPL-3.0-or-later
"""CPU topology: affinity-visible physical cores from sysfs.

``sched_getaffinity`` gives the CPUs this process may actually run on (cgroup
and taskset aware); ``/sys/devices/system/cpu/cpuN/topology`` collapses
hyperthread siblings onto their ``(package, core)`` pair. Anything unreadable
means "cannot tell" — the core owns the fallback, not this module.
"""

from __future__ import annotations

import os
from pathlib import Path

TOPOLOGY_ROOT = Path("/sys/devices/system/cpu")


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
