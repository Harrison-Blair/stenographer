# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for hotkey.py: parse_binding, chord_active, edge, and the
platform-neutral ChordTracker state machine. No mocks, no devices — the key table
is a tiny dict-backed value (pure input, not a mock of evdev) and the tracker is
driven through ``_key_event`` exactly as a platform reader thread would. The real
read loop is covered by the uinput loopback smoke in test_hotkey_smoke.py (§6).

Each test here was seen to FAIL against a deliberately broken stub before the real
implementation made it pass:
  - parse_binding not raising on an unknown token
  - chord_active dropping the non-empty / subset checks
  - edge returning None for every (was, is) pair
  - ChordTracker ignoring the stuck-key synthesis / cross-device release
"""

from __future__ import annotations

import threading

import pytest

from stenographer.hotkey import (
    BindingError,
    ChordTracker,
    chord_active,
    edge,
    parse_binding,
)

_TABLE = {"KEY_A": 30, "KEY_LEFTCTRL": 29, "KEY_RIGHTALT": 100, "KEY_RIGHTCTRL": 97}


class _Keys:
    """Dict-backed KeyTable: the same acceptance contract, no evdev."""

    def code(self, name: str) -> int:
        return _TABLE[name]

    def name(self, code: int) -> str | None:
        for key, value in _TABLE.items():
            if value == code:
                return key
        return None


KEYS = _Keys()


def test_parse_single_key():
    assert parse_binding("KEY_RIGHTALT", KEYS) == frozenset({100})


def test_parse_chord_is_order_independent():
    forward = parse_binding("KEY_LEFTCTRL+KEY_A", KEYS)
    reversed_ = parse_binding("KEY_A+KEY_LEFTCTRL", KEYS)
    assert forward == reversed_
    assert forward == frozenset({29, 30})


def test_parse_tolerates_whitespace():
    assert parse_binding("  KEY_A + KEY_LEFTCTRL ", KEYS) == frozenset({30, 29})


def test_parse_empty_raises():
    with pytest.raises(BindingError):
        parse_binding("   ", KEYS)


def test_parse_trailing_plus_raises():
    with pytest.raises(BindingError):
        parse_binding("KEY_A+", KEYS)


def test_parse_unknown_token_names_it():
    with pytest.raises(BindingError, match="KEY_NOPE"):
        parse_binding("KEY_NOPE", KEYS)


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


def _tracker(chord: frozenset[int], *devices: int) -> tuple[ChordTracker, list[str]]:
    events: list[str] = []
    tracker = ChordTracker(
        chord=chord,
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
        lock=threading.RLock(),
    )
    tracker._held_by_device = {device: set() for device in devices}
    return tracker, events


def test_tracker_reports_one_edge_per_chord_transition():
    tracker, events = _tracker(frozenset({29, 30}), 1)
    assert tracker._key_event(1, 29, 1) is True
    assert events == []
    tracker._key_event(1, 30, 1)
    assert events == ["start"]
    tracker._key_event(1, 30, 2)  # autorepeat never re-fires
    tracker._key_event(1, 29, 0)
    assert events == ["start", "stop"]
    assert tracker.wait_binding_released(timeout=0.0) is False  # 30 still held
    tracker._key_event(1, 30, 0)
    assert tracker.wait_binding_released(timeout=0.0) is True


def test_tracker_synthesizes_missed_release_on_repeated_keydown():
    # A second keydown with no keyup in between means a release was lost:
    # the tracker reports stop then start, not a silent continuation.
    tracker, events = _tracker(frozenset({100}), 1)
    tracker._key_event(1, 100, 1)
    tracker._key_event(1, 100, 1)
    assert events == ["start", "stop", "start"]


def test_tracker_unions_devices_and_releases_across_them():
    # Press on HID 1, release routed through HID 2 (multi-interface keyboards).
    tracker, events = _tracker(frozenset({100}), 1, 2)
    tracker._key_event(1, 100, 1)
    assert events == ["start"]
    tracker._key_event(2, 100, 0)
    assert events == ["start", "stop"]
    assert tracker._held == set()


def test_tracker_rejects_unregistered_device():
    tracker, events = _tracker(frozenset({100}), 1)
    assert tracker._key_event(7, 100, 1) is False
    assert events == []
