# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the uinput injector: chord_events() ordering.

The uinput device itself is covered by the integration smoke suite in
tests/delivery/test_deliver_smoke.py — nothing here mocks UInput (§6).
"""

from __future__ import annotations

from stenographer.platform.linux.uinput import _INSERT, _SHIFT, chord_events


def test_chord_events_exact_sequence():
    # The load-bearing invariant: Shift press wraps the Insert press+release.
    assert chord_events() == [(_SHIFT, 1), (_INSERT, 1), (_INSERT, 0), (_SHIFT, 0)]


def test_every_press_has_a_matching_release():
    # A pressed code (value 1) that is never released (value 0) leaves a key
    # latched in the compositor's seat state.
    events = chord_events()
    pressed = [code for code, value in events if value == 1]
    released = [code for code, value in events if value == 0]
    assert sorted(pressed) == sorted(released)


def test_insert_released_before_shift():
    events = chord_events()
    insert_release = events.index((_INSERT, 0))
    shift_release = events.index((_SHIFT, 0))
    assert insert_release < shift_release


def test_shift_is_the_outer_wrapper():
    events = chord_events()
    # Shift down is first and Shift up is last: it wraps everything between.
    assert events[0] == (_SHIFT, 1)
    assert events[-1] == (_SHIFT, 0)
