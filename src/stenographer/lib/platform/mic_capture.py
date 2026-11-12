# SPDX-License-Identifier: GPL-3.0-or-later
"""Contract for 16 kHz mono microphone capture and the list of input sources."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np

from stenographer.lib.platform.errors import MicCaptureError

MicBlockCallback = Callable[["np.ndarray | MicCaptureError"], None]


@dataclass(frozen=True, slots=True)
class InputSource:
    """One microphone: ``name`` is the saved setting value, ``description`` its label."""

    name: str
    description: str


@dataclass(frozen=True, slots=True)
class InputSources:
    """The microphones of the host, the name of the default one, or why there is no list."""

    sources: tuple[InputSource, ...] = ()
    default: str | None = None
    error: str | None = None


@runtime_checkable
class MicCapture(Protocol):
    """A platform service that streams one microphone to a callback.

    ``start`` returns as soon as the capture runs; blocks and a later failure
    arrive on *on_block* from a reader thread. *target* ``None`` is the
    default source. After a failure, ``stop`` must be called before a new
    ``start``.
    """

    def start(self, target: str | None, on_block: MicBlockCallback) -> None: ...

    def stop(self) -> None: ...
