# SPDX-License-Identifier: GPL-3.0-or-later
"""Errors for live model files and the speech pass."""


class InvalidVadModelError(ValueError):
    """The VAD model configuration is invalid."""


class SpeechPassError(RuntimeError):
    """The child process of the speech pass failed or died."""
