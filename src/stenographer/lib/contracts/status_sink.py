# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from stenographer.lib.contracts.loading_model import LoadingModel
from stenographer.lib.contracts.overlay_state import OverlayState

if TYPE_CHECKING:
    from stenographer.lib.refine.profiles import RefineProfile


class StatusSink(Protocol):
    """Nonblocking daemon-side lifecycle destination.

    Concrete sinks may enqueue work, but these calls must not perform display or
    child-process I/O because hotkey callbacks invoke them under the daemon lock.
    """

    def publish(self, state: OverlayState, profile: RefineProfile | None = None) -> None: ...

    def loading_activity(self, model: LoadingModel, active: bool) -> None: ...

    def audio_block(self, samples: object, sample_rate: int, stream_epoch: int) -> None: ...

    def close(self) -> None: ...
