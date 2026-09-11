# SPDX-License-Identifier: GPL-3.0-or-later
"""Clipboard confirmation, key-release, and injection measurements."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeliveryTimings:
    """What one delivery attempt cost, for the utterance summary line."""

    copy_ms: float
    release_wait_ms: float | None
    release_timeout: bool | None
    copied: bool = False
    chord_sent: bool = False
