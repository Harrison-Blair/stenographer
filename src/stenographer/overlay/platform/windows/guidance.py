# SPDX-License-Identifier: GPL-3.0-or-later
from stenographer.overlay.platform.guidance import OverlayGuidance


def guidance() -> OverlayGuidance:
    return OverlayGuidance(
        overlay_backend_labels={},
        overlay_fix_hints={},
        overlay_fix_hint_default="the overlay is not available on Windows yet",
    )
