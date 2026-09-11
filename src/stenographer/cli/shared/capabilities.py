# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose independent required and optional capability reports for terminal workflows."""

from dataclasses import dataclass, field

from stenographer.lib.diagnostics.capability_result import Capabilities as CoreCapabilities
from stenographer.overlay.capabilities.models import OverlayCapability


@dataclass(frozen=True)
class Capabilities(CoreCapabilities):
    overlay: OverlayCapability = field(default_factory=OverlayCapability.disabled)
