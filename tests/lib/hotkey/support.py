# SPDX-License-Identifier: GPL-3.0-or-later
"""A ChordTracker with its devices registered, ready for ``_key_event``."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from stenographer.lib.hotkey.chord_tracker import ChordTracker

if TYPE_CHECKING:
    from collections.abc import Callable


def _ignore(_name: str) -> None:
    pass


def make_tracker(
    bindings: dict[str, frozenset[int]],
    *,
    on_start: Callable[[str], None] = _ignore,
    on_stop: Callable[[str], None] = _ignore,
    cancel: frozenset[int] = frozenset(),
    on_cancel: Callable[[], None] | None = None,
    devices: tuple[int, ...] = (1,),
) -> ChordTracker:
    tracker = ChordTracker(
        bindings=bindings,
        on_binding_start=on_start,
        on_binding_stop=on_stop,
        lock=threading.RLock(),
        cancel=cancel,
        on_cancel=on_cancel,
    )
    tracker._held_by_device = {device: set() for device in devices}
    return tracker
