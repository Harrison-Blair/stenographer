# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations


class UnsupportedPlatformError(RuntimeError):
    """The host has no platform implementation for the requested surface."""


class SingleInstanceLockError(OSError):
    """Lock I/O failed while acquiring the single-instance lock — not contention."""


class SystemAudioCaptureError(RuntimeError):
    """System audio capture could not start or stopped unexpectedly."""


class SpeakerDiarizerError(RuntimeError):
    """Speaker separation is unavailable, or its helper process failed."""


class NemoSpeechError(RuntimeError):
    """A NeMo-Speech C API call returned a status other than OK."""
