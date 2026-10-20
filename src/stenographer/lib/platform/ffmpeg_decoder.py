# SPDX-License-Identifier: GPL-3.0-or-later
"""Contract for system FFmpeg decoding used by file transcription."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import numpy as np


class FfmpegDecoder(Protocol):
    """Inspect and decode audio through system FFmpeg tools."""

    def available(self) -> bool: ...

    def duration(self, path: Path) -> float | None: ...

    def decode(self, path: Path, *, block_frames: int = 65536) -> Iterator[np.ndarray]: ...
