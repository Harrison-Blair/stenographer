# SPDX-License-Identifier: GPL-3.0-or-later
"""Errors of file jobs."""

from __future__ import annotations


class FileJobCancelledError(Exception):
    """A cancel seen between two decodes of one phrase."""
