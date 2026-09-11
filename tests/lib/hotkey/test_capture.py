# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for the core binding-capture vocabulary: the reducer and the
serializer. The key table is a real value, never a mock of a device."""

from __future__ import annotations

import pytest

from stenographer.lib.hotkey.capture import reduce_capture, serialize_capture
from stenographer.lib.hotkey.capture_records import CaptureState, KeyEvent
from stenographer.lib.hotkey.errors import BindingCaptureError
from stenographer.lib.hotkey.static_key_table import StaticKeyTable

_KEY_LEFTCTRL = 29
_KEY_A = 30


class _OneWayKeyTable:
    """A key table that can name a code but cannot parse the name back.

    Not a stub of a device: a real (if inconsistent) table, which is exactly
    what the serializer's parse round trip exists to catch.
    """

    def code(self, name: str) -> int:
        raise KeyError(name)

    def name(self, code: int) -> str | None:
        return "KEY_GHOST"


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


def test_binding_capture_ignores_a_keydown_for_a_key_already_held():
    # A repeat reported as a fresh keydown (value 1) must not push the code
    # into the chord twice or re-arm a release that never happened.
    state = _capture(KeyEvent("kbd", 29, 1), KeyEvent("kbd", 29, 1))
    assert state.codes == (29,)
    assert state.held == frozenset({("kbd", 29)})
    assert state.complete is False


def test_binding_capture_ignores_a_keyup_for_a_key_it_never_saw_pressed():
    # The capture window can open mid-press (the Enter that started setup, a
    # key held from before); a stray key-up must not complete an empty capture.
    state = _capture(KeyEvent("kbd", 29, 0))
    assert state == CaptureState()
    assert state.complete is False


def test_serialize_capture_renders_canonical_names_in_press_order():
    state = _capture(
        KeyEvent("kbd", _KEY_LEFTCTRL, 1),
        KeyEvent("kbd", _KEY_A, 1),
        KeyEvent("kbd", _KEY_A, 0),
        KeyEvent("kbd", _KEY_LEFTCTRL, 0),
    )
    assert state.complete is True
    assert serialize_capture(state, StaticKeyTable()) == "KEY_LEFTCTRL+KEY_A"


def test_serialize_capture_refuses_an_unfinished_capture():
    state = _capture(KeyEvent("kbd", _KEY_A, 1))
    with pytest.raises(BindingCaptureError, match="did not complete"):
        serialize_capture(state, StaticKeyTable())


def test_serialize_capture_names_a_code_the_key_table_does_not_know():
    # An exotic HID can report a code with no canonical name; writing it into
    # config would produce a binding the daemon then refuses to parse.
    state = _capture(KeyEvent("kbd", 0x7FFF, 1), KeyEvent("kbd", 0x7FFF, 0))
    with pytest.raises(BindingCaptureError, match="unknown evdev key code 32767"):
        serialize_capture(state, StaticKeyTable())


def test_serialize_capture_reports_a_name_that_will_not_parse_back():
    """The serialized spec is validated by parsing it, in capture's vocabulary.

    A name the table cannot resolve again would be written into config and only
    fail at the next daemon start, so it must fail here — as a
    BindingCaptureError, not as the BindingError the parser raises.
    """
    state = _capture(KeyEvent("kbd", _KEY_A, 1), KeyEvent("kbd", _KEY_A, 0))
    with pytest.raises(BindingCaptureError, match="unknown key 'KEY_GHOST'"):
        serialize_capture(state, _OneWayKeyTable())
