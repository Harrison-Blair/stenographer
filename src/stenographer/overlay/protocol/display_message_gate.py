# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.protocol.codec import _valid_generation
from stenographer.overlay.protocol.messages import (
    LoadingActivityMessage,
    SpectrumMessage,
    StateMessage,
)


@dataclass(slots=True)
class DisplayMessageGate:
    """Reject stale generated records without coupling loading to recording. PURE."""

    current: int = -1
    recording_generation: int | None = None
    sequence: int = -1
    loading_active: bool = False

    def accept(
        self,
        message: StateMessage | SpectrumMessage | LoadingActivityMessage,
    ) -> bool:
        if isinstance(message, LoadingActivityMessage):
            self.loading_active = message.active
            return True
        if isinstance(message, SpectrumMessage):
            if message.generation != self.recording_generation or message.sequence <= self.sequence:
                return False
            self.sequence = message.sequence
            return True
        if not isinstance(message, StateMessage):
            raise TypeError("display gate accepts only generated display messages")
        if not _valid_generation(message.generation):
            raise ValueError("generation must be a non-negative signed 64-bit integer")
        if message.generation <= self.current:
            return False
        self.current = message.generation
        self.recording_generation = (
            message.generation if message.state is OverlayState.RECORDING else None
        )
        self.sequence = -1
        return True
