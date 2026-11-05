# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the uinput injector: chord_events() ordering.

The uinput device itself is covered by the integration smoke suite in
tests/delivery/test_deliver_smoke.py — nothing here mocks UInput.
"""

from __future__ import annotations

from stenographer.lib.platform.linux.uinput import _INSERT, _SHIFT, chord_events


def test_chord_events_exact_sequence():
    # The load-bearing invariant: Shift press wraps the Insert press+release.
    # A pressed code (value 1) that is never released (value 0) leaves a key
    # latched in the compositor's seat state.
    assert chord_events() == [(_SHIFT, 1), (_INSERT, 1), (_INSERT, 0), (_SHIFT, 0)]


def test_keyboard_opens_no_device_until_a_chord_is_sent():
    """The injector is lazy and its teardown is idempotent.

    ``/dev/uinput`` is opened on the first ``send_chord`` (the loopback smoke
    owns that path); constructing and closing must never touch it,
    so the daemon can build an injector on a host that has no uinput at all.
    Closing twice is a no-op, because daemon shutdown may unwind twice.
    """
    from stenographer.lib.platform.linux.uinput import UinputKeyboard

    keyboard = UinputKeyboard()
    keyboard.close()
    keyboard.close()
