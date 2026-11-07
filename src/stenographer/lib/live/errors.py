# SPDX-License-Identifier: GPL-3.0-or-later
"""Errors for live model files and the speech pass."""


class LiveDownloadError(RuntimeError):
    """A live model file could not be downloaded or verified."""


class InvalidVadModelError(ValueError):
    """The VAD model configuration is invalid."""


class SpeechPassError(RuntimeError):
    """The child process of the speech pass failed or died."""
