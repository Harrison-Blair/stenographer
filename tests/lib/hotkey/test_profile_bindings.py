# SPDX-License-Identifier: GPL-3.0-or-later
"""One tracker selects between both refinement profile bindings."""

from __future__ import annotations

import threading

from stenographer.lib.hotkey.chord_tracker import ChordTracker


def test_one_tracker_reports_the_profile_that_started_each_utterance():
    events = []
    tracker = ChordTracker(
        bindings={"agent": frozenset({97}), "general": frozenset({100})},
        on_binding_start=lambda profile: events.append(("start", profile)),
        on_binding_stop=lambda profile: events.append(("stop", profile)),
        lock=threading.RLock(),
    )
    tracker._held_by_device[1] = set()

    tracker._key_event(1, 100, 1)
    tracker._key_event(1, 100, 0)
    tracker._key_event(1, 97, 1)
    tracker._key_event(1, 97, 0)

    assert events == [
        ("start", "general"),
        ("stop", "general"),
        ("start", "agent"),
        ("stop", "agent"),
    ]


def test_release_wait_tracks_the_binding_that_started_the_utterance():
    tracker = ChordTracker(
        bindings={"agent": frozenset({97}), "general": frozenset({100, 30})},
        on_binding_start=lambda _profile: None,
        on_binding_stop=lambda _profile: None,
        lock=threading.RLock(),
    )
    tracker._held_by_device[1] = {30}
    tracker._held = {30}
    tracker._last_started_chord = frozenset({100, 30})
    assert tracker.wait_binding_released(timeout=0.0) is False


def test_a_rejected_busy_press_cannot_replace_the_release_wait_binding():
    accepted = True

    def start(_profile: str) -> bool:
        return accepted

    tracker = ChordTracker(
        bindings={"agent": frozenset({97}), "general": frozenset({100})},
        on_binding_start=start,
        on_binding_stop=lambda _profile: None,
        lock=threading.RLock(),
    )
    tracker._held_by_device[1] = set()
    tracker._key_event(1, 97, 1)
    tracker._key_event(1, 97, 0)
    accepted = False
    tracker._key_event(1, 100, 1)

    assert tracker._last_started_chord == frozenset({97})


def test_stopping_press_waits_for_its_binding_before_callback_returns():
    waits: list[bool] = []
    recording = False

    def start(_profile: str) -> bool:
        nonlocal recording
        if recording:
            recording = False
            waits.append(tracker.wait_binding_released(timeout=0.0))
            return True
        recording = True
        return True

    tracker = ChordTracker(
        bindings={"agent": frozenset({97}), "general": frozenset({100})},
        on_binding_start=start,
        on_binding_stop=lambda _profile: None,
        lock=threading.RLock(),
    )
    tracker._held_by_device[1] = set()
    tracker._key_event(1, 97, 1)
    tracker._key_event(1, 97, 0)
    tracker._key_event(1, 100, 1)

    assert waits == [False]
    assert tracker.wait_binding_released(timeout=0.0) is False
    tracker._key_event(1, 100, 0)
    assert tracker.wait_binding_released(timeout=0.0) is True
