# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux hotkey backend: the evdev key table, main-keyboard detection, and the
acquisition back-off. No devices are opened — the real read loop is covered by
the uinput loopback smoke in tests/test_hotkey_smoke.py.
"""

from __future__ import annotations

import threading
import time

import evdev
import pytest

from stenographer.hotkey import parse_binding
from stenographer.platform.linux.hotkey import (
    EvdevHotkeyListener,
    EvdevKeyTable,
    is_main_keyboard,
)

_KEY_A = evdev.ecodes.KEY_A
_KEY_Z = evdev.ecodes.KEY_Z


def test_key_table_round_trips_canonical_names():
    keys = EvdevKeyTable()
    assert keys.code("KEY_RIGHTCTRL") == evdev.ecodes.KEY_RIGHTCTRL
    assert keys.name(evdev.ecodes.KEY_RIGHTCTRL) == "KEY_RIGHTCTRL"
    # Aliased codes resolve to the first (canonical) evdev name.
    assert keys.name(evdev.ecodes.KEY_MUTE) == "KEY_MIN_INTERESTING"
    assert keys.name(0x7FFF) is None
    with pytest.raises(KeyError):
        keys.code("KEY_NOPE")


def test_parse_binding_through_the_evdev_table():
    assert parse_binding("KEY_LEFTCTRL+KEY_A", EvdevKeyTable()) == frozenset(
        {evdev.ecodes.KEY_LEFTCTRL, evdev.ecodes.KEY_A}
    )


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
    listener = EvdevHotkeyListener(
        chord=parse_binding("KEY_RIGHTALT", EvdevKeyTable()),
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
