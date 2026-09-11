# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from enum import StrEnum


class UnavailableReason(StrEnum):
    """Fixed diagnostics safe to expose to the parent and ``doctor``."""

    NO_WAYLAND_DISPLAY = "no_wayland_display"
    WAYLAND_CONNECT_FAILED = "wayland_connect_failed"
    REQUIRED_GLOBALS_MISSING = "required_wayland_globals_missing"
    NO_X_DISPLAY = "no_x_display"
    X_CONNECT_FAILED = "x_connect_failed"
    X_ARGB_UNAVAILABLE = "x_argb_unavailable"
    X_EXTENSIONS_UNAVAILABLE = "x_extensions_unavailable"
    # A v4-compatible vocabulary extension: the reason set is fixed data, not a
    # framing change, so adding one value bumps no protocol version.
    BACKEND_DEPENDENCY_MISSING = "backend_dependency_missing"
    BACKENDS_UNAVAILABLE = "backends_unavailable"
    BACKEND_LOST = "backend_lost"
    HELPER_CRASHED = "helper_crashed"
    PROTOCOL_ERROR = "protocol_error"
    INTERNAL_ERROR = "internal_error"
