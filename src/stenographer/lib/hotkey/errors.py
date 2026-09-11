# SPDX-License-Identifier: GPL-3.0-or-later
"""Binding parsing and capture failures."""

from __future__ import annotations


class BindingError(ValueError):
    """Raised by parse_binding on an empty or unknown key token."""


class BindingCaptureError(Exception):
    """A live binding could not be captured or serialized."""
