# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from stenographer.lib.contracts.overlay_state import OverlayState

TRANSIENT_STATES = frozenset({OverlayState.CANCELLED, OverlayState.ERROR})
"""States that dismiss themselves after a fixed display window."""


def should_publish_state(current: OverlayState, candidate: OverlayState) -> bool:
    """Return whether a daemon state update needs a new helper generation. PURE.

    Stable operational states are coalesced, but a self-dismissing state always
    needs its own display deadline: the daemon never learns that the pill timed
    out (the helper's mailbox owns that clock), so a repeat of one would
    otherwise be coalesced away against a pill that is no longer on screen.
    """
    return candidate in TRANSIENT_STATES or candidate is not current
