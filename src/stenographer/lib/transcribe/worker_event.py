# SPDX-License-Identifier: GPL-3.0-or-later
"""Metadata-only inference-worker protocol events."""

from __future__ import annotations

from enum import Enum, auto


class WorkerEvent(Enum):
    """Metadata-only control events sent before a cold child's first decode."""

    MODEL_READY = auto()
