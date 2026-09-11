# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from stenographer.overlay.capabilities.models import OverlayCapability
from stenographer.overlay.platform import current_platform
from stenographer.overlay.protocol.ordering import selected_unavailable_reason
from stenographer.overlay.protocol.unavailablereason import UnavailableReason


def probe_overlay(enabled: bool) -> OverlayCapability:
    """Probe optional backends in runtime preference order without creating a surface."""
    if not enabled:
        return OverlayCapability.disabled()

    reasons: list[UnavailableReason | None] = []
    for spec in current_platform().overlay_backends():
        reason = spec.probe()
        if reason is None:
            return OverlayCapability.available(spec.backend)
        reasons.append(reason)
    # The same fold the helper applies to its construct failures, so what
    # ``doctor`` reports and what the helper logs cannot disagree.
    return OverlayCapability.unavailable(selected_unavailable_reason(reasons))
