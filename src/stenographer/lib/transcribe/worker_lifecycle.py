# SPDX-License-Identifier: GPL-3.0-or-later
"""Observable model-loading and transcription lifecycle signals."""

from __future__ import annotations

from enum import Enum, auto


class WorkerLifecycle(Enum):
    """Fixed observer signals emitted around model load and transcription."""

    MODEL_LOADING = auto()
    MODEL_READY = auto()
    MODEL_LOADING_FINISHED = auto()
    TRANSCRIBING = auto()
