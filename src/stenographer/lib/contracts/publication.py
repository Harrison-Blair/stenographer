# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from stenographer.lib.contracts.overlay_state import OverlayState


def should_publish_state(current: OverlayState, candidate: OverlayState) -> bool:
    """Return whether a daemon state update needs a new helper generation. PURE.

    Stable operational states are coalesced, but each error represents a new
    failure and therefore needs its own display deadline.
    """
    return candidate is OverlayState.ERROR or candidate is not current
