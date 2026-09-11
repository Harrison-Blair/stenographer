# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Mapping
from dataclasses import dataclass

from stenographer.overlay.protocol.unavailablereason import UnavailableReason


@dataclass(frozen=True, slots=True)
class OverlayGuidance:
    overlay_backend_labels: Mapping[str, str]
    overlay_fix_hints: Mapping[UnavailableReason, str]
    overlay_fix_hint_default: str
