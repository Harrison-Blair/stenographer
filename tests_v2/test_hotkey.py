# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for hotkey.py: parse_binding, is_main_keyboard, chord_active,
edge. No mocks, no devices — the real read loop is covered by the uinput loopback
smoke in test_hotkey_smoke.py (§6).

Each test here was seen to FAIL against a deliberately broken stub before the real
implementation made it pass:
  - parse_binding not raising on an unknown token
  - is_main_keyboard ignoring the name-token / letter-count filters
  - chord_active dropping the non-empty / subset checks
  - edge returning None for every (was, is) pair
"""

from __future__ import annotations

import threading
import time

import evdev
import pytest
from stenographer_v2.hotkey import (
    BindingError,
    HotkeyListener,
    chord_active,
    edge,
    is_main_keyboard,
    parse_binding,
)

_KEY_A = evdev.ecodes.KEY_A
_KEY_Z = evdev.ecodes.KEY_Z


def test_parse_single_key():
    assert parse_binding("KEY_RIGHTALT") == frozenset({evdev.ecodes.KEY_RIGHTALT})


def test_parse_chord_is_order_independent():
    forward = parse_binding("KEY_LEFTCTRL+KEY_A")
    reversed_ = parse_binding("KEY_A+KEY_LEFTCTRL")
    assert forward == reversed_
    assert forward == frozenset({evdev.ecodes.KEY_LEFTCTRL, evdev.ecodes.KEY_A})


def test_parse_tolerates_whitespace():
    assert parse_binding("  KEY_A + KEY_LEFTCTRL ") == frozenset(
        {evdev.ecodes.KEY_A, evdev.ecodes.KEY_LEFTCTRL}
    )


def test_parse_empty_raises():
    with pytest.raises(BindingError):
        parse_binding("   ")


def test_parse_trailing_plus_raises():
    with pytest.raises(BindingError):
        parse_binding("KEY_A+")


def test_parse_unknown_token_names_it():
    with pytest.raises(BindingError, match="KEY_NOPE"):
        parse_binding("KEY_NOPE")


def test_main_keyboard_true_for_plain_named_full_keyboard():
    codes = range(_KEY_A, _KEY_Z + 1)  # >= 10 codes in the letter range
    assert is_main_keyboard("My Keyboard", codes) is True


def test_mouse_name_is_rejected_even_with_letter_keys():
    codes = range(_KEY_A, _KEY_Z + 1)
    assert is_main_keyboard("Logitech USB Mouse", codes) is False


def test_consumer_control_name_is_rejected():
    codes = range(_KEY_A, _KEY_Z + 1)
    assert is_main_keyboard("Keychron Q1 Consumer Control", codes) is False


def test_too_few_letter_keys_is_rejected():
    assert is_main_keyboard("Volume Dial", [_KEY_A, _KEY_A + 1, _KEY_A + 2]) is False


def test_chord_active_requires_full_subset():
    chord = frozenset({1, 2})
    assert chord_active({1, 2, 3}, chord) is True
    assert chord_active({1}, chord) is False


def test_chord_active_empty_chord_is_never_active():
    assert chord_active({1, 2, 3}, frozenset()) is False


def test_edge_maps_all_four_combinations():
    assert edge(False, True) == "start"
    assert edge(True, False) == "stop"
    assert edge(False, False) is None
    assert edge(True, True) is None


def test_unopenable_explicit_device_backs_off_instead_of_spinning():
    """An explicit hotkey.device that cannot be opened (unplugged, stale path, or
    a permissions gap) must back off between retries, not busy-loop the CPU.

    Regression guard: _resolve_paths returns the explicit path unconditionally,
    so the acquisition loop must sleep on a failed open rather than re-detecting
    instantly. A nonexistent path makes evdev.InputDevice raise a real OSError —
    no device is ever created, so this stays a control-flow test. The retry rate
    is observed by counting _resolve_paths calls; the busy-loop bug does
    thousands in 0.3s, the backoff does a handful.

    Seen to FAIL against the pre-fix listener (count in the thousands).
    """
    listener = HotkeyListener(
        chord=parse_binding("KEY_RIGHTALT"),
        device_path="/dev/input/stenographer-nonexistent",
        on_start=lambda: None,
        on_stop=lambda: None,
        lock=threading.RLock(),
    )
    calls = {"n": 0}
    real_resolve = listener._resolve_paths

    def counting_resolve():
        calls["n"] += 1
        return real_resolve()

    listener._resolve_paths = counting_resolve
    listener.start()
    try:
        time.sleep(0.3)
    finally:
        listener.stop()

    assert calls["n"] < 20, f"listener spun {calls['n']} times in 0.3s (expected backoff)"
