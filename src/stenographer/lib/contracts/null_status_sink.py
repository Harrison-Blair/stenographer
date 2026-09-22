# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from stenographer.lib.contracts.loading_model import LoadingModel
from stenographer.lib.contracts.overlay_state import OverlayState


class NullStatusSink:
    """No-op sink used when the overlay is disabled or unavailable."""

    def publish(self, state: OverlayState) -> None:
        pass

    def loading_activity(self, model: LoadingModel, active: bool) -> None:
        pass

    def audio_block(self, samples: object, sample_rate: int, stream_epoch: int) -> None:
        pass

    def close(self) -> None:
        pass
