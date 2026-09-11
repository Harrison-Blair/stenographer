# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Protocol


class KeyInjector(Protocol):
    """Emits the paste chord at the cursor (``Deliverer``'s keyboard)."""

    def send_chord(self) -> None: ...

    def close(self) -> None: ...
