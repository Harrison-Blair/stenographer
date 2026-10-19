# SPDX-License-Identifier: GPL-3.0-or-later
"""Contract for 16 kHz mono system audio capture."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

import numpy as np

from stenographer.lib.platform.errors import SystemAudioCaptureError

SystemAudioBlockCallback = Callable[[np.ndarray | SystemAudioCaptureError], None]


@runtime_checkable
class SystemAudioCapture(Protocol):
    """A platform service that streams system audio to a callback."""

    def start(self, on_block: SystemAudioBlockCallback) -> None: ...

    def stop(self) -> None: ...

    def available(self) -> tuple[bool, str | None]: ...
