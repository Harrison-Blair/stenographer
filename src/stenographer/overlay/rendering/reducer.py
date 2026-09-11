# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, field

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.protocol.command import Command
from stenographer.overlay.protocol.errors import ProtocolError
from stenographer.overlay.protocol.messages import (
    CommandMessage,
    LoadingActivityMessage,
    SpectrumMessage,
    StateMessage,
)
from stenographer.overlay.rendering.display_intent import DisplayIntent
from stenographer.overlay.rendering.loading_pulse import LoadingPulse

DisplayRecord = StateMessage | SpectrumMessage | LoadingActivityMessage | CommandMessage


_SILENT_LEVELS = (0,) * SPECTRUM_BANDS


@dataclass(slots=True)
class OverlayReducer:
    """Fixed lifecycle state plus the intent policy both backends share. PURE."""

    state: OverlayState = OverlayState.HIDDEN
    levels: tuple[int, ...] = _SILENT_LEVELS
    pulse: LoadingPulse = field(default_factory=LoadingPulse)

    @property
    def visible(self) -> bool:
        """Whether a surface should exist at all for the current state."""
        return self.state is not OverlayState.HIDDEN

    def levels_for(self, state: OverlayState) -> tuple[int, ...] | None:
        """Return spectrum levels only for the one state that renders them."""
        return self.levels if state is OverlayState.RECORDING else None

    def apply(self, message: DisplayRecord, now: float) -> DisplayIntent:
        """Fold one accepted record into the state and return the backend's work."""
        if isinstance(message, CommandMessage):
            if message.command is not Command.SHUTDOWN:
                raise ProtocolError("unsupported helper command")
            return DisplayIntent.STOP
        if isinstance(message, LoadingActivityMessage):
            return self._loading_activity(message.active, now)
        if isinstance(message, SpectrumMessage):
            self.levels = message.levels
            if self.state is not OverlayState.RECORDING:
                return DisplayIntent.NONE
            return DisplayIntent.REPAINT
        if not isinstance(message, StateMessage):
            raise ProtocolError("unsupported helper message")
        return self._state_change(message.state, now)

    def _loading_activity(self, active: bool, now: float) -> DisplayIntent:
        if not self.pulse.set_active(active, now):
            # A duplicate edge must not restart the breathing phase.
            return DisplayIntent.NONE
        if not self.visible:
            return DisplayIntent.NONE
        if active:
            self.pulse.arm(now)
        return DisplayIntent.REPAINT

    def _state_change(self, state: OverlayState, now: float) -> DisplayIntent:
        self.state = state
        if state is OverlayState.RECORDING:
            # A new recording never inherits the previous utterance's bars.
            self.levels = _SILENT_LEVELS
        if state is OverlayState.HIDDEN:
            self.pulse.disarm_frames()
            return DisplayIntent.TEARDOWN
        if self.pulse.active:
            self.pulse.arm(now)
        return DisplayIntent.REDRAW
