# SPDX-License-Identifier: GPL-3.0-or-later
"""Paste injection: a persistent uinput virtual keyboard emitting Shift+Insert.

One injection path per session, zero per-utterance fallback: no wtype, no
per-character typing, no max_chars. ``chord_events`` is the pure unit target; the
device itself is covered by the integration smoke suite, never by mocks (the
testing policy in AGENTS.md).
"""

from __future__ import annotations

import time

from evdev import UInput, ecodes

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


class UinputKeyboard:
    """A persistent uinput virtual keyboard that emits the paste chord.

    Exactly one device is held for the daemon's lifetime (avoids a per-utterance
    device-enumeration race and its latency). The device is opened lazily on the
    first ``send_chord`` and settled once before its first event, or the
    compositor may drop the chord. PermissionError/FileNotFoundError on
    ``/dev/uinput`` propagate — doctor owns the message, so it must not
    silently no-op.
    """

    def __init__(self) -> None:
        self._ui: UInput | None = None

    def _ensure_device(self) -> UInput:
        if self._ui is None:
            self._ui = UInput(events={ecodes.EV_KEY: [_SHIFT, _INSERT]}, name="stenographer")
            time.sleep(_DEVICE_SETTLE_SECONDS)
        return self._ui

    def send_chord(self) -> None:
        ui = self._ensure_device()
        for code, value in chord_events():
            ui.write(ecodes.EV_KEY, code, value)
        ui.syn()

    def close(self) -> None:
        if self._ui is not None:
            self._ui.close()
            self._ui = None

    def __enter__(self) -> UinputKeyboard:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
