# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations


class UnsupportedPlatformError(RuntimeError):
    """The host has no platform implementation for the requested surface."""


class SingleInstanceLockError(OSError):
    """Lock I/O failed while acquiring the single-instance lock — not contention."""
