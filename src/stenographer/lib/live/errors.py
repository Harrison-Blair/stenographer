# SPDX-License-Identifier: GPL-3.0-or-later
"""Errors for live model files."""


class LiveDownloadError(RuntimeError):
    """A live model file could not be downloaded or verified."""
