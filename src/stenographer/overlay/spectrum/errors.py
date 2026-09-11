# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations


class CalibrationError(ValueError):
    """The recorded room-noise sample cannot produce a safe display floor."""


class CalibrationCancelledError(CalibrationError):
    """The caller cancelled an in-progress calibration."""
