# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from collections.abc import Callable

from stenographer.overlay.platform.linux.backends.closable_backend import _ClosableBackend
from stenographer.overlay.platform.linux.backends.errors import BackendUnavailableError
from stenographer.overlay.protocol.unavailablereason import UnavailableReason

INPUT_KEY = "input"


DISPLAY_KEY = "display"


_READ_SIZE = 4096


def next_timeout(*timeouts: float | None) -> float | None:
    """Fold optional selector waits into the earliest one, or None when idle."""
    pending = [timeout for timeout in timeouts if timeout is not None]
    return min(pending) if pending else None


def probe_backend(construct: Callable[[], _ClosableBackend]) -> UnavailableReason | None:
    """Read-only probe: construct, translate a fixed reason, always close."""
    try:
        backend = construct()
    except BackendUnavailableError as exc:
        return exc.reason
    backend.close()
    return None
