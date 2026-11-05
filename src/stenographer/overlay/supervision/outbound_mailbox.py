# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import threading
import time
from collections import deque

from stenographer.lib.contracts.loading_model import LoadingModel
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.refine.profiles import RefineProfile
from stenographer.overlay.protocol.command import Command
from stenographer.overlay.protocol.messages import (
    CommandMessage,
    LoadingActivityMessage,
    ProtocolMessage,
    SpectrumMessage,
    StateMessage,
)
from stenographer.overlay.protocol.ordering import transient_display_seconds
from stenographer.overlay.supervision.constants import _MAILBOX_CAPACITY
from stenographer.overlay.supervision.models import _AudioBlock


class OutboundMailbox:
    """Bounded metadata queue plus latest-only audio and spectrum slots.

    Adjacent state updates coalesce to the newest generation. Loading-activity
    records form ordering barriers and take priority over spectrum frames.
    State transitions discard raw/spectrum slots from the prior recording.
    Shutdown clears everything and occupies the sole command slot.
    """

    def __init__(self, capacity: int = _MAILBOX_CAPACITY) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("mailbox capacity must be a positive integer")
        self._capacity = capacity
        self._pending: deque[StateMessage | LoadingActivityMessage] = deque()
        self._spectrum_pending: SpectrumMessage | None = None
        self._audio_pending: _AudioBlock | None = None
        self._next_generation = 0
        self._next_sequence = 0
        self._closed = False
        self._disabled = False
        self._shutdown_pending = False
        self._current_state = StateMessage(0, OverlayState.HIDDEN)
        self._loading_models: list[LoadingModel] = []
        self._recording_generation: int | None = None
        self._transient_deadline: float | None = None
        # Reentrant because expire_transient publishes while it holds the lock.
        self._lock = threading.RLock()

    @property
    def current_state(self) -> StateMessage:
        with self._lock:
            return self._current_state

    def _append(self, message: StateMessage | LoadingActivityMessage) -> None:
        if (
            isinstance(message, StateMessage)
            and self._pending
            and isinstance(self._pending[-1], StateMessage)
        ):
            self._pending[-1] = message
        else:
            if len(self._pending) == self._capacity:
                self._pending.popleft()
            self._pending.append(message)

    def _generation(self) -> int:
        generation = self._next_generation
        self._next_generation += 1
        return generation

    def publish(self, state: OverlayState, profile: RefineProfile | None = None) -> int:
        with self._lock:
            if self._closed or self._disabled:
                return self._current_state.generation
            message = StateMessage(self._generation(), state, profile)
            self._audio_pending = None
            self._spectrum_pending = None
            self._recording_generation = (
                message.generation if state is OverlayState.RECORDING else None
            )
            self._next_sequence = 0
            self._append(message)
            self._current_state = message
            display_seconds = transient_display_seconds(state)
            self._transient_deadline = (
                None if display_seconds is None else time.monotonic() + display_seconds
            )
            return message.generation

    def loading_activity(self, model: LoadingModel, active: bool) -> None:
        """Queue a boolean activity edge without disturbing recording slots."""
        with self._lock:
            present = model in self._loading_models
            if self._closed or self._disabled or active == present:
                return
            self._append(LoadingActivityMessage(model, active))
            if active:
                self._loading_models.append(model)
            else:
                self._loading_models.remove(model)

    def audio_block(self, samples: object, sample_rate: int, stream_epoch: int) -> None:
        """Replace the raw block slot without copying, locking, or performing I/O."""
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
            return
        if isinstance(stream_epoch, bool) or not isinstance(stream_epoch, int) or stream_epoch < 0:
            return
        generation = self._recording_generation
        if self._closed or self._disabled or generation is None:
            return
        # CPython reference assignment is atomic.  A racing transition may
        # leave one old tagged block, which the generation check discards.
        self._audio_pending = _AudioBlock(generation, samples, sample_rate, stream_epoch)

    def take_audio_nowait(self) -> _AudioBlock | None:
        with self._lock:
            block, self._audio_pending = self._audio_pending, None
            return block

    def publish_spectrum(self, generation: int, levels: tuple[int, ...]) -> int | None:
        """Replace the latest frame only when its recording is still current."""
        with self._lock:
            if (
                self._closed
                or self._disabled
                or generation != self._recording_generation
                or self._current_state.state is not OverlayState.RECORDING
            ):
                return None
            message = SpectrumMessage(generation, self._next_sequence, levels)
            self._next_sequence += 1
            self._spectrum_pending = message
            return message.sequence

    def expire_transient(self, now: float | None = None) -> int | None:
        """Queue a guarded hide when the current transient state expires."""
        if now is None:
            now = time.monotonic()
        with self._lock:
            deadline = self._transient_deadline
            if deadline is None or now < deadline:
                return None
            return self.publish(OverlayState.HIDDEN, self._current_state.profile)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._pending.clear()
            self._audio_pending = None
            self._spectrum_pending = None
            self._transient_deadline = None
            self._shutdown_pending = True

    def disable(self) -> None:
        """Discard optional work after the helper has permanently stopped."""
        with self._lock:
            self._disabled = True
            self._pending.clear()
            self._audio_pending = None
            self._spectrum_pending = None
            self._recording_generation = None
            self._loading_models = []

    def replay_for_helper(self) -> tuple[StateMessage | LoadingActivityMessage, ...]:
        """Return one atomic current snapshot and discard superseded metadata.

        A restarted helper has no useful history.  Clearing queued metadata in
        the same critical section prevents an ungenerated loading edge from
        replaying out of order after the current snapshot.
        """
        with self._lock:
            replay: list[StateMessage | LoadingActivityMessage] = [
                LoadingActivityMessage(model, True) for model in self._loading_models
            ]
            if self._current_state.state is not OverlayState.HIDDEN:
                replay.append(self._current_state)
            self._pending.clear()
            self._spectrum_pending = None
            return tuple(replay)

    def take_nowait(self) -> ProtocolMessage | None:
        with self._lock:
            if self._shutdown_pending:
                self._shutdown_pending = False
                return CommandMessage(Command.SHUTDOWN)
            if self._pending:
                return self._pending.popleft()
            if self._spectrum_pending is not None:
                message, self._spectrum_pending = self._spectrum_pending, None
                return message
            return None
