# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from evdev import ecodes

_SHIFT = ecodes.KEY_LEFTSHIFT


_INSERT = ecodes.KEY_INSERT


_DEVICE_SETTLE_SECONDS = 0.2


def chord_events() -> list[tuple[int, int]]:
    """The Shift+Insert key event sequence as ``(code, value)`` press/release pairs.

    PURE. The modifier press wraps the key press+release: Insert is released
    BEFORE Shift, and Shift is never left latched. This ordering is the
    load-bearing correctness detail and the sole pure unit target.
    """
    return [(_SHIFT, 1), (_INSERT, 1), (_INSERT, 0), (_SHIFT, 0)]
