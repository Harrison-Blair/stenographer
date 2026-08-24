# SPDX-License-Identifier: GPL-3.0-or-later
"""Scaffolding shared by the helper-side overlay backends.

Layer-shell and XWayland are structurally one program: connect to a display
server, own at most one click-through surface, and run a selector loop over the
parent's NDJSON stdin plus the display connection.  Everything that is not
display-server specific lives here -- the fixed-reason probe failure, the probe
shape, the event loop with its hooks, the loading-frame timer, the frame
request, and the idempotent close -- so a backend module contains only its own
drawing and window-management primitives.

The decision half of the loop is core: ``OverlayReducer`` turns one accepted
record into a redraw/teardown/stop intent, and the subclass hooks below are the
only translation into display primitives.  Error auto-hide is deliberately not
here: the supervisor is its single authority (see ``overlay/supervisor.py``).
"""

from __future__ import annotations

import os
import selectors
import time
from collections.abc import Callable
from typing import BinaryIO, ClassVar, Protocol

from stenographer.overlay.reducer import DisplayIntent, DisplayRecord, OverlayReducer
from stenographer.overlay.render import LoadingPulse, OverlayFrame, render_overlay
from stenographer.status import (
    Backend,
    DisplayMessageGate,
    LineReader,
    OverlayState,
    UnavailableReason,
    drain_display_stream,
)

INPUT_KEY = "input"
DISPLAY_KEY = "display"
_READ_SIZE = 4096


class BackendUnavailableError(RuntimeError):
    """Fixed-reason display-backend probe failure safe to report over IPC."""

    def __init__(self, reason: UnavailableReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def next_timeout(*timeouts: float | None) -> float | None:
    """Fold optional selector waits into the earliest one, or None when idle."""
    pending = [timeout for timeout in timeouts if timeout is not None]
    return min(pending) if pending else None


class _ClosableBackend(Protocol):
    def close(self) -> None: ...


def probe_backend(construct: Callable[[], _ClosableBackend]) -> UnavailableReason | None:
    """Read-only probe: construct, translate a fixed reason, always close."""
    try:
        backend = construct()
    except BackendUnavailableError as exc:
        return exc.reason
    backend.close()
    return None


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


__all__ = [
    "DISPLAY_KEY",
    "INPUT_KEY",
    "BackendUnavailableError",
    "HelperBackend",
    "next_timeout",
    "probe_backend",
]
