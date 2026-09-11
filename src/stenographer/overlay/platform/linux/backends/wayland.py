# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import errno

from stenographer.overlay.platform.linux.backends.global_removal import GlobalRemoval
from stenographer.overlay.platform.linux.backends.scale_plan import ScalePlan
from stenographer.overlay.platform.linux.backends.wayland_constants import (
    _OUTPUT_INTERFACE,
    REQUIRED_GLOBALS,
)
from stenographer.overlay.rendering.constants import CANVAS_HEIGHT, CANVAS_WIDTH


def classify_global_removal(interface: str | None) -> GlobalRemoval:
    """Classify a ``global_remove`` by interface without touching the display.

    Losing a required global is unrecoverable; losing an output only matters
    when the surface had entered it. Anything else is a hotplug detail.
    """
    if interface is None:
        return GlobalRemoval.IGNORE
    if interface in REQUIRED_GLOBALS:
        return GlobalRemoval.LOST
    if interface == _OUTPUT_INTERFACE:
        return GlobalRemoval.OUTPUT
    return GlobalRemoval.IGNORE


def flush_wants_write(result: int, error_number: int) -> bool:
    """Classify one ``wl_display_flush`` result. PURE.

    A short flush on a full socket is normal back-pressure and asks the loop
    for write interest; any other failure is a lost connection.
    """
    if result >= 0:
        return False
    if error_number in {errno.EAGAIN, errno.EWOULDBLOCK}:
        return True
    raise RuntimeError("Wayland display flush failed")


def choose_scale_plan(*, integer_scale: int, preferred_scale_120: int | None = None) -> ScalePlan:
    """Select fractional scaling only when a valid preferred scale is present."""
    integer_scale = max(1, integer_scale)
    if preferred_scale_120 is not None and preferred_scale_120 > 0:
        return ScalePlan(
            render_scale=preferred_scale_120 / 120,
            buffer_scale=1,
            viewport_destination=(CANVAS_WIDTH, CANVAS_HEIGHT),
        )
    return ScalePlan(float(integer_scale), integer_scale, None)


def callback_is_current(callback_proxy: object, current_proxy: object | None) -> bool:
    """Accept an event only when it belongs to the current surface epoch."""
    return current_proxy is not None and callback_proxy is current_proxy
