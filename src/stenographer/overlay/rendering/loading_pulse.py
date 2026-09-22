# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, field

from stenographer.lib.contracts.loading_model import LoadingModel
from stenographer.overlay.rendering.constants import LOADING_FRAME_INTERVAL, LOADING_PULSE_SECONDS


@dataclass(slots=True)
class LoadingPulse:
    """Pure loading-pulse activity, breath, and frame-deadline math. PURE.

    The class never reads a clock.  Backends stay the owners of deadline
    lifecycle policy: when to arm the frame cadence, and when destroying or
    recreating a surface clears (or deliberately preserves) the deadline.

    Activity (``loading``) and the breath being drawn (``breath_model``,
    ``breath_started_at``) are deliberately separate: a model can join or
    leave at any time, but the breath in progress never changes model or
    resets phase except at its own trough, so a loading border is never cut
    short mid-breath.
    """

    loading: list[LoadingModel] = field(default_factory=list)
    breath_model: LoadingModel | None = None
    breath_started_at: float | None = None
    next_frame_at: float | None = None

    @property
    def breathing(self) -> bool:
        return self.breath_started_at is not None

    def set_active(self, model: LoadingModel, active: bool) -> bool:
        """Apply one activity edge; return False for a duplicate edge."""
        present = model in self.loading
        if active == present:
            return False
        if active:
            self.loading.append(model)
        else:
            self.loading.remove(model)
        return True

    def start_breathing(self, now: float) -> bool:
        """Start a fresh breath at the trough with the earliest model."""
        if not self.loading or self.breathing:
            return False
        self.breath_model = self.loading[0]
        self.breath_started_at = now
        self.arm(now)
        return True

    def stop_breathing(self) -> None:
        """End the current breath immediately, keeping recorded activity."""
        self.breath_model = None
        self.breath_started_at = None
        self.next_frame_at = None

    def elapsed(self, now: float) -> float | None:
        """Return the animation-driving elapsed time, or None while idle."""
        if not self.breathing:
            return None
        return max(0.0, now - self.breath_started_at)

    def timeout(self, now: float, visible: bool) -> float | None:
        """Return the wait until the next armed frame, or None when idle."""
        if not self.breathing or not visible or self.next_frame_at is None:
            return None
        return max(0.0, self.next_frame_at - now)

    def frame_due(self, now: float, visible: bool) -> bool:
        """Return whether an armed frame deadline has been reached."""
        timeout = self.timeout(now, visible)
        return timeout is not None and timeout <= 0.0

    def advance(self, now: float) -> None:
        """Re-arm one fixed frame interval, rotating the breath at its trough."""
        if self.breathing and now - self.breath_started_at >= LOADING_PULSE_SECONDS:
            next_model = self._next_model()
            if next_model is None:
                self.stop_breathing()
                return
            self.breath_model = next_model
            self.breath_started_at += LOADING_PULSE_SECONDS
        self.next_frame_at = now + LOADING_FRAME_INTERVAL

    def arm(self, now: float) -> None:
        """Start (or restart) the frame cadence from ``now``."""
        self.next_frame_at = now + LOADING_FRAME_INTERVAL

    def disarm_frames(self) -> None:
        """Clear the frame deadline without touching activity or the breath."""
        self.next_frame_at = None

    def _next_model(self) -> LoadingModel | None:
        if not self.loading:
            return None
        if self.breath_model not in self.loading:
            return self.loading[0]
        index = self.loading.index(self.breath_model)
        return self.loading[(index + 1) % len(self.loading)]
