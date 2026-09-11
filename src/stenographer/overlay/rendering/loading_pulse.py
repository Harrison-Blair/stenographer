# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass

from stenographer.overlay.rendering.constants import LOADING_FRAME_INTERVAL


@dataclass(slots=True)
class LoadingPulse:
    """Pure loading-pulse edge, elapsed, and frame-deadline math. PURE.

    The class never reads a clock.  Backends stay the owners of deadline
    lifecycle policy: when to arm the frame cadence, and when destroying or
    recreating a surface clears (or deliberately preserves) the deadline.
    """

    active: bool = False
    started_at: float | None = None
    next_frame_at: float | None = None

    def set_active(self, active: bool, now: float) -> bool:
        """Apply one activity edge; return False for a duplicate edge."""
        if active == self.active:
            return False
        self.active = active
        self.started_at = now if active else None
        self.next_frame_at = None
        return True

    def elapsed(self, now: float) -> float | None:
        """Return the animation-driving elapsed time, or None while inactive."""
        if not self.active or self.started_at is None:
            return None
        return max(0.0, now - self.started_at)

    def timeout(self, now: float, visible: bool) -> float | None:
        """Return the wait until the next armed frame, or None when idle."""
        if not self.active or not visible or self.next_frame_at is None:
            return None
        return max(0.0, self.next_frame_at - now)

    def frame_due(self, now: float, visible: bool) -> bool:
        """Return whether an armed frame deadline has been reached."""
        timeout = self.timeout(now, visible)
        return timeout is not None and timeout <= 0.0

    def advance(self, now: float) -> None:
        """Re-arm one fixed frame interval after a due frame was drawn."""
        self.next_frame_at = now + LOADING_FRAME_INTERVAL

    def arm(self, now: float) -> None:
        """Start (or restart) the frame cadence from ``now``."""
        self.advance(now)

    def disarm_frames(self) -> None:
        """Clear the frame deadline without touching activity or start time."""
        self.next_frame_at = None
