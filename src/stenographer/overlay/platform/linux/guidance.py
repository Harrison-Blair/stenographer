# SPDX-License-Identifier: GPL-3.0-or-later
from stenographer.overlay.platform.guidance import OverlayGuidance
from stenographer.overlay.protocol.unavailablereason import UnavailableReason


def guidance() -> OverlayGuidance:
    return OverlayGuidance(
        overlay_backend_labels={"layer-shell": "layer-shell", "xwayland": "XWayland fallback"},
        overlay_fix_hints={
            UnavailableReason.NO_X_DISPLAY: "no X display; set DISPLAY or enable XWayland",
            UnavailableReason.X_CONNECT_FAILED: (
                "cannot connect to XWayland; check DISPLAY and session access"
            ),
            UnavailableReason.X_ARGB_UNAVAILABLE: "XWayland has no usable 32-bit ARGB visual",
            UnavailableReason.X_EXTENSIONS_UNAVAILABLE: (
                "XWayland requires the Shape and RandR extensions"
            ),
            UnavailableReason.BACKEND_DEPENDENCY_MISSING: (
                "overlay backend imports failed; reinstall stenographer with its overlay extras"
            ),
        },
        overlay_fix_hint_default=(
            "no usable layer-shell or XWayland backend; check the graphical session"
        ),
    )
