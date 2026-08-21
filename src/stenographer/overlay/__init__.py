# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional isolated visual feedback: helper supervision, backends, rendering, spectrum."""

from stenographer.overlay.supervisor import (
    OverlaySupervisor,
    private_entry_requested,
    run_overlay_helper,
)

__all__ = [
    "OverlaySupervisor",
    "private_entry_requested",
    "run_overlay_helper",
]
