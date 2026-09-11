# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import dataclasses

from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.unavailablereason import UnavailableReason


@dataclasses.dataclass(frozen=True, slots=True)
class OverlayCapability:
    """Informational result of the optional display-backend probe."""

    enabled: bool
    backend: Backend | None = None
    reason: UnavailableReason | None = None

    @classmethod
    def disabled(cls) -> OverlayCapability:
        return cls(False)

    @classmethod
    def available(cls, backend: Backend) -> OverlayCapability:
        return cls(True, backend=backend)

    @classmethod
    def unavailable(cls, reason: UnavailableReason) -> OverlayCapability:
        return cls(True, reason=reason)
