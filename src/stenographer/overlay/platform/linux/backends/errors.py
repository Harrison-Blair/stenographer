# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from stenographer.overlay.protocol.unavailablereason import UnavailableReason


class BackendUnavailableError(RuntimeError):
    """Fixed-reason display-backend probe failure safe to report over IPC."""

    def __init__(self, reason: UnavailableReason) -> None:
        super().__init__(reason.value)
        self.reason = reason
