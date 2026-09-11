# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Protocol


class KeyTable(Protocol):
    """The binding key-name vocabulary (evdev ``KEY_*`` names on every platform).

    ``hotkey.binding`` is written with these names regardless of OS; a backend
    maps them onto its own key codes.
    """

    def code(self, name: str) -> int:
        """Key code for *name*; raises ``KeyError`` for an unknown name."""
        ...

    def name(self, code: int) -> str | None:
        """Canonical name for *code*, or ``None`` when it has no name."""
        ...
