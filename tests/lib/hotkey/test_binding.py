# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for hotkey.py: parse_binding, chord_active, edge, and the
platform-neutral ChordTracker state machine. No mocks, no devices — the key table
is a tiny dict-backed value (pure input, not a mock of evdev) and the tracker is
driven through ``_key_event`` exactly as a platform reader thread would. The real
read loop is covered by the uinput loopback smoke in test_hotkey_smoke.py.

Each test here was seen to FAIL against a deliberately broken stub before the real
implementation made it pass:
  - parse_binding not raising on an unknown token
  - chord_active dropping the non-empty / subset checks
  - edge returning None for every (was, is) pair
  - ChordTracker ignoring the stuck-key synthesis / cross-device release
"""

from __future__ import annotations

import threading
import time

import pytest

from stenographer.lib.hotkey.binding import chord_active, edge, parse_binding
from stenographer.lib.hotkey.chord_tracker import ChordTracker
from stenographer.lib.hotkey.errors import BindingError

_TABLE = {
    "KEY_A": 30,
    "KEY_ESC": 1,
    "KEY_LEFTCTRL": 29,
    "KEY_RIGHTALT": 100,
    "KEY_RIGHTCTRL": 97,
}


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


def test_tracker_reports_cancel_only_on_the_rising_edge():
    cancels: list[str] = []
    tracker = ChordTracker(
        chord=frozenset({100}),
        on_start=lambda: None,
        on_stop=lambda: None,
        lock=threading.RLock(),
        cancel=frozenset({1}),
        on_cancel=lambda: cancels.append("cancel"),
    )
    tracker._held_by_device = {1: set()}

    tracker._key_event(1, 1, 1)
    tracker._key_event(1, 1, 2)
    tracker._key_event(1, 1, 0)
    assert cancels == ["cancel"]

    tracker._key_event(1, 1, 1)
    assert cancels == ["cancel", "cancel"]


def test_tracker_keeps_cancel_and_main_chords_independent_while_held():
    events: list[str] = []
    tracker = ChordTracker(
        chord=frozenset({29, 30}),
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
        lock=threading.RLock(),
        cancel=frozenset({1}),
        on_cancel=lambda: events.append("cancel"),
    )
    tracker._held_by_device = {1: set()}

    tracker._key_event(1, 1, 1)
    tracker._key_event(1, 29, 1)
    tracker._key_event(1, 30, 1)
    tracker._key_event(1, 30, 0)
    tracker._key_event(1, 29, 0)
    tracker._key_event(1, 1, 0)

    assert events == ["cancel", "start", "stop"]


class _HandoffLock:
    """A real RLock with a rendezvous on the way in.

    The dispatch lock is injected by the daemon, so a lock that says when a
    caller has reached it — and holds that caller there until the test lets it
    through — makes the two-reader race deterministic without changing the
    tracker or patching anything inside it.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reached = threading.Event()
        self.proceed = threading.Event()

    def __enter__(self):
        self.reached.set()
        assert self.proceed.wait(10), "the handoff lock was never released"
        return self._lock.__enter__()

    def __exit__(self, *exc):
        return self._lock.__exit__(*exc)


def test_release_guard_stops_waiting_when_the_listener_stops():
    """A stopped listener will never report the key-up, so the guard must not
    sit out its whole timeout before the deliverer may paste."""
    tracker, _ = _tracker(frozenset({100}), 1)
    tracker._key_event(1, 100, 1)
    tracker._stop_event.set()

    started_at = time.monotonic()
    assert tracker.wait_binding_released(timeout=5.0) is True
    assert time.monotonic() - started_at < 1.0


class _ObservedHeldLock:
    """A real lock that reports when the guard has sampled the held keys."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.sampled = threading.Event()

    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, *exc):
        result = self._lock.__exit__(*exc)
        self.sampled.set()
        return result


def test_release_guard_polls_until_the_chord_key_actually_comes_up():
    """The guard must remain pending while the key is held, then observe release.

    Seen to FAIL against a guard that only sampled once (returns False while
    the key is still held, so the paste chord fires with a modifier down).
    """
    tracker, _ = _tracker(frozenset({100}), 1)
    tracker._key_event(1, 100, 1)
    held_lock = _ObservedHeldLock()
    tracker._held_lock = held_lock
    finished = threading.Event()
    results: list[bool] = []

    def wait_for_release():
        try:
            results.append(tracker.wait_binding_released(timeout=10.0, poll_interval=0.01))
        finally:
            finished.set()

    waiter = threading.Thread(target=wait_for_release)
    waiter.start()
    try:
        assert held_lock.sampled.wait(10), "the guard never sampled the held key"
        assert not finished.wait(0.05), "the guard returned while the key was still held"
        tracker._key_event(1, 100, 0)
        assert finished.wait(10), "the guard never observed the key release"
        assert results == [True]
        assert tracker._held == set()
    finally:
        tracker._stop_event.set()
        waiter.join(timeout=10)
    assert not waiter.is_alive()


def test_an_edge_that_arrives_during_shutdown_is_not_dispatched():
    # stop() sets the flag while readers may still be in flight; a callback
    # fired then would start a session the daemon is already tearing down.
    tracker, events = _tracker(frozenset({100}), 1)
    tracker._stop_event.set()

    tracker._update(True)
    tracker._update_cancel(True)

    assert events == []
    assert tracker._active is False
    assert tracker._cancel_active is False


def test_two_readers_seeing_the_same_press_dispatch_only_one_edge():
    """The was-active read and the callback happen under the dispatch lock.

    The losing reader is held at the lock until the winner's edge has landed,
    so it re-reads the settled state and finds no transition left to report.
    Seen to FAIL against a tracker that decided the edge before taking the
    lock (both readers fire on_start).
    """
    events: list[str] = []
    lock = _HandoffLock()
    tracker = ChordTracker(
        chord=frozenset({100}),
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
        lock=lock,
        cancel=frozenset({1}),
        on_cancel=lambda: events.append("cancel"),
    )

    dispatchers = (
        (tracker._update, "_active"),
        (tracker._update_cancel, "_cancel_active"),
    )
    for dispatch, settled in dispatchers:
        lock.reached.clear()
        lock.proceed.clear()
        loser = threading.Thread(target=dispatch, args=(True,), daemon=True)
        loser.start()
        assert lock.reached.wait(10)
        # The other reader's edge won the race while this one waited.
        setattr(tracker, settled, True)
        lock.proceed.set()
        loser.join(timeout=10)
        assert loser.is_alive() is False

    assert events == []
