# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from stenographer.overlay.protocol.unavailablereason import UnavailableReason


class _NoBackendError(Exception):
    """Every registered backend refused; *reason* is what the parent is told."""

    def __init__(self, reason: UnavailableReason) -> None:
        super().__init__(reason.value)
        self.reason = reason
