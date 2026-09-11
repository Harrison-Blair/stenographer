# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import selectors
import time
from typing import BinaryIO, ClassVar

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.platform.linux.backends.base import (
    _READ_SIZE,
    DISPLAY_KEY,
    INPUT_KEY,
    next_timeout,
)
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.display_message_gate import DisplayMessageGate
from stenographer.overlay.protocol.line_reader import LineReader
from stenographer.overlay.protocol.ordering import drain_display_stream
from stenographer.overlay.rendering.display_intent import DisplayIntent
from stenographer.overlay.rendering.frame import OverlayFrame
from stenographer.overlay.rendering.loading_pulse import LoadingPulse
from stenographer.overlay.rendering.reducer import DisplayRecord, OverlayReducer
from stenographer.overlay.rendering.render import render_overlay


class HelperBackend:
    """One display connection and at most one surface, driven by the reducer."""

    backend: ClassVar[Backend]

    def __init__(self) -> None:
        self._reducer = OverlayReducer()
        self._closed = False

    @property
    def _state(self) -> OverlayState:
        return self._reducer.state

    @property
    def _pulse(self) -> LoadingPulse:
        return self._reducer.pulse

    @property
    def _visible(self) -> bool:
        return self._reducer.visible

    def _frame(self, state: OverlayState, *, scale: float = 1.0) -> OverlayFrame:
        """Build the one frame request shape every backend draws from."""
        return render_overlay(
            state,
            scale=scale,
            levels=self._reducer.levels_for(state),
            loading_elapsed=self._pulse.elapsed(time.monotonic()),
        )

    def run(self, input_stream: BinaryIO) -> None:
        """Serve the parent's display stream until EOF, shutdown, or failure."""
        reader = LineReader()
        gate = DisplayMessageGate()
        input_fd = input_stream.fileno()
        selector = selectors.DefaultSelector()
        selector.register(input_fd, selectors.EVENT_READ, INPUT_KEY)
        selector.register(self._display_fd(), selectors.EVENT_READ, DISPLAY_KEY)
        try:
            while True:
                self._before_select(selector)
                events = selector.select(self._select_timeout())
                self._on_timers()
                for key, mask in events:
                    if key.data == DISPLAY_KEY:
                        self._on_display_readable(mask)
                        continue
                    chunk = os.read(input_fd, _READ_SIZE)
                    if not chunk:
                        reader.finish()
                        return
                    for message in drain_display_stream(chunk, reader, gate):
                        if not self._dispatch(message):
                            return
                self._after_events()
        finally:
            selector.close()

    def _dispatch(self, message: DisplayRecord) -> bool:
        """Apply one record; return False once the helper must stop serving."""
        intent = self._reducer.apply(message, time.monotonic())
        if intent is DisplayIntent.STOP:
            return False
        if intent is DisplayIntent.TEARDOWN:
            self._teardown()
        elif intent is DisplayIntent.REDRAW:
            self._draw()
        elif intent is DisplayIntent.REPAINT:
            self._repaint()
        return True

    def _select_timeout(self) -> float | None:
        now = time.monotonic()
        return next_timeout(self._pulse.timeout(now, self._visible), *self._extra_timeouts(now))

    def _on_timers(self) -> None:
        self._on_extra_timers()
        now = time.monotonic()
        if not self._pulse.frame_due(now, self._visible):
            return
        self._pulse.advance(now)
        self._repaint()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close()

    # --- Display-server specific hooks -------------------------------------

    def _display_fd(self) -> int:
        """Return the display connection descriptor to select on."""
        raise NotImplementedError

    def _draw(self) -> None:
        """Ensure a surface exists for the current state and paint it."""
        raise NotImplementedError

    def _repaint(self) -> None:
        """Paint the surface only if one already exists; never create one."""
        raise NotImplementedError

    def _teardown(self) -> None:
        """Destroy the current surface, leaving the connection usable."""
        raise NotImplementedError

    def _on_display_readable(self, mask: int) -> None:
        """Service the display connection for one selector event."""
        raise NotImplementedError

    def _close(self) -> None:
        """Release the surface and the display connection exactly once."""
        raise NotImplementedError

    def _before_select(self, selector: selectors.BaseSelector) -> None:
        """Adjust registrations (write interest) right before each wait."""
        return

    def _extra_timeouts(self, now: float) -> tuple[float | None, ...]:
        """Backend-local deadlines folded into the selector wait."""
        return ()

    def _on_extra_timers(self) -> None:
        """Run backend-local deadlines that came due during the wait."""
        return

    def _after_events(self) -> None:
        """React once every event of one loop turn has been handled.

        A backend that discovers a lost connection inside a dispatcher raises
        from here, so the whole turn is still processed first.
        """
        return
