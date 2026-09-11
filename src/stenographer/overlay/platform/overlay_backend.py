# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import BinaryIO, Protocol

from stenographer.overlay.protocol.backend import Backend


class OverlayBackend(Protocol):
    """Helper-side display backend (see ``overlay.helper.execution.run_overlay_helper``)."""

    backend: Backend

    def run(self, input_stream: BinaryIO) -> None: ...

    def close(self) -> None: ...
