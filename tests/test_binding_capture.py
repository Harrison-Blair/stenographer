# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure reducer tests for the core binding-capture vocabulary."""

from __future__ import annotations

from stenographer.binding_capture import CaptureState, KeyEvent, reduce_capture


def _capture(*events: KeyEvent | None) -> CaptureState:
    state = CaptureState()
    for event in events:
        state = reduce_capture(state, event)
    return state


def test_binding_capture_completes_a_single_key_after_release():
    pressed = _capture(KeyEvent("kbd", 97, 1))
    assert pressed.codes == (97,)
    assert pressed.complete is False

    released = reduce_capture(pressed, KeyEvent("kbd", 97, 0))
    assert released.complete is True
    assert released.held == frozenset()


def test_binding_capture_keeps_press_order_and_ignores_repeats():
    state = _capture(
        KeyEvent("kbd", 29, 1),
        KeyEvent("kbd", 29, 2),
        KeyEvent("kbd", 30, 1),
    )

    assert state.codes == (29, 30)
    assert state.held == frozenset({("kbd", 29), ("kbd", 30)})


def test_binding_capture_completes_after_reverse_release_order():
    state = _capture(
        KeyEvent("kbd", 29, 1),
        KeyEvent("kbd", 30, 1),
        KeyEvent("kbd", 30, 0),
    )
    assert state.complete is False

    state = reduce_capture(state, KeyEvent("kbd", 29, 0))
    assert state.complete is True


def test_binding_capture_unions_held_keys_across_devices():
    state = _capture(
        KeyEvent("left", 29, 1),
        KeyEvent("right", 30, 1),
        KeyEvent("left", 29, 0),
    )
    assert state.codes == (29, 30)
    assert state.complete is False

    state = reduce_capture(state, KeyEvent("right", 30, 0))
    assert state.complete is True


def test_binding_capture_waits_for_same_code_held_on_another_device():
    state = _capture(
        KeyEvent("left", 97, 1),
        KeyEvent("right", 97, 1),
        KeyEvent("left", 97, 0),
    )
    assert state.codes == (97,)
    assert state.complete is False

    state = reduce_capture(state, KeyEvent("right", 97, 0))
    assert state.complete is True


def test_binding_capture_timeout_is_terminal():
    state = _capture(KeyEvent("kbd", 29, 1), None)
    assert state.timed_out is True
    assert state.complete is False

    assert reduce_capture(state, KeyEvent("kbd", 29, 0)) == state
