# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable key events and immutable binding-capture state."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class CaptureState:
    """State accumulated while capturing one key or chord."""

    held: frozenset[tuple[str, int]] = frozenset()
    codes: tuple[int, ...] = ()
    complete: bool = False
    timed_out: bool = False


@dataclasses.dataclass(frozen=True)
class KeyEvent:
    """One device-scoped key transition; ``None`` represents timeout."""

    device: str
    code: int
    value: int
