# SPDX-License-Identifier: GPL-3.0-or-later
"""Exception types and helpers for stenographer's error-handling policy.

Components MUST raise :class:`StenographerError` subclasses and call
:func:`notify_failure`, :func:`fatal`, and :func:`degrade_capability`
rather than invent their own error behaviour.
"""

import logging
import sys
from typing import NoReturn

log = logging.getLogger(__name__)


class StenographerError(Exception):
    """Base class for every exception raised inside the stenographer daemon."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConfigError(StenographerError):
    """Raised on invalid or missing configuration.

    Callers MUST map this to exit code 78 (``EX_CONFIG``, from
    ``sysexits.h``).
    """


class CapabilityError(StenographerError):
    """Raised when a required runtime capability is unavailable at startup.

    Callers MUST map this to exit code 78 (``EX_CONFIG``, from
    ``sysexits.h``).
    """


class AudioCaptureError(StenographerError):
    """Raised when audio capture from the default microphone fails."""


class TranscriptionError(StenographerError):
    """Raised when the ASR worker fails to produce a transcript."""


class UpdateError(StenographerError):
    """Raised by ``stenographer update`` on any non-recoverable failure.

    Callers SHOULD map this to exit code 1 (network / sha256 / install
    failure), not 78.
    """


def notify_failure(reason: str) -> None:
    """Log ``notify_failure: <reason>`` at ERROR level."""
    log.error("notify_failure: %s", reason)


def fatal(message: str, code: int = 78) -> NoReturn:
    """Log ``message`` at CRITICAL level and exit with ``code`` (default 78)."""
    log.critical("%s", message)
    sys.exit(code)


def degrade_capability(name: str) -> None:
    """Log that ``name`` is unavailable; the daemon continues without it."""
    log.warning("degrade: %s unavailable; continuing without it", name)
