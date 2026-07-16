# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`stenographer.hotkey`."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import evdev
import pytest

from stenographer.errors import ConfigError
from stenographer.hotkey.binding import HotkeyBinding
from stenographer.hotkey.listener import HotkeyListener, auto_detect_path
from stenographer.hotkey.state_machine import HotkeyStateMachine

# --- Binding parser ---


def test_parse_single_key() -> None:
    b = HotkeyBinding.parse("KEY_RIGHTCTRL")
    assert b.keys == ("KEY_RIGHTCTRL",)
    assert str(b) == "KEY_RIGHTCTRL"


def test_parse_chord_canonicalises_order() -> None:
    a = HotkeyBinding.parse("KEY_LEFTCTRL+KEY_A")
    b = HotkeyBinding.parse("KEY_A+KEY_LEFTCTRL")
    assert a == b
    assert a.keys == ("KEY_A", "KEY_LEFTCTRL")


def test_parse_strips_whitespace() -> None:
    b = HotkeyBinding.parse("  KEY_A  +  KEY_B  ")
    assert b.keys == ("KEY_A", "KEY_B")


def test_parse_rejects_empty_string() -> None:
    with pytest.raises(ConfigError):
        HotkeyBinding.parse("")


def test_parse_rejects_empty_piece() -> None:
    with pytest.raises(ConfigError):
        HotkeyBinding.parse("KEY_A+")
    with pytest.raises(ConfigError):
        HotkeyBinding.parse("+KEY_B")
    with pytest.raises(ConfigError):
        HotkeyBinding.parse("KEY_A++KEY_B")


def test_parse_rejects_unknown_key() -> None:
    with pytest.raises(ConfigError):
        HotkeyBinding.parse("NOT_A_KEY")


def test_parse_rejects_mouse_button() -> None:
    with pytest.raises(ConfigError):
        HotkeyBinding.parse("BTN_LEFT")


def test_to_evdev_codes_returns_ints() -> None:
    b = HotkeyBinding.parse("KEY_LEFTCTRL+KEY_A")
    codes = b.to_evdev_codes()
    assert all(isinstance(c, int) for c in codes)
    assert set(codes) == {evdev.ecodes.KEY_LEFTCTRL, evdev.ecodes.KEY_A}


def test_matches_set_equality() -> None:
    b = HotkeyBinding.parse("KEY_LEFTCTRL+KEY_A")
    assert b.matches({evdev.ecodes.KEY_LEFTCTRL, evdev.ecodes.KEY_A})
    assert not b.matches({evdev.ecodes.KEY_LEFTCTRL})
    assert not b.matches({evdev.ecodes.KEY_LEFTCTRL, evdev.ecodes.KEY_A, evdev.ecodes.KEY_B})


# --- State machine ---


def test_state_machine_starts_idle() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    assert sm.state == "IDLE"
    assert not sm.is_chord_active


def test_ptt_path_keydown_then_long_keyup() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    sm.mark_chord_active(True)
    t = sm.on_keydown(0.0)
    assert t.action == "start_recording"
    assert t.cue == "ptt_on"
    assert sm.state == "RECORDING_PTT"
    sm.mark_chord_active(False)
    t = sm.on_keyup(0.6)
    assert t.action == "stop_recording_ptt"
    assert t.cue == "ptt_off"
    assert sm.state == "IDLE"


def test_short_tap_enters_pending_then_timeout_discards() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    sm.mark_chord_active(True)
    assert sm.on_keydown(0.0).action == "start_recording"
    sm.mark_chord_active(False)
    t = sm.on_keyup(0.2)
    assert t.action == "await_double_tap"
    assert t.cue is None
    assert sm.state == "PENDING_TAP"
    t = sm.on_timeout(sm.pending_generation)
    assert t.action == "discard_recording"
    assert t.cue == "discard"
    assert sm.state == "IDLE"


def test_stale_timeout_after_second_tap_is_noop() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    sm.mark_chord_active(True)
    sm.on_keydown(0.0)
    sm.mark_chord_active(False)
    sm.on_keyup(0.2)
    stale_gen = sm.pending_generation
    sm.mark_chord_active(True)
    t = sm.on_keydown(0.4)
    assert t.action == "latch_toggle"
    assert t.cue == "toggle_on"
    assert sm.state == "TOGGLE_LATCHED"
    assert sm.on_timeout(stale_gen).action == "noop"
    assert sm.state == "TOGGLE_LATCHED"


def test_timeout_after_reset_is_noop() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    sm.mark_chord_active(True)
    sm.on_keydown(0.0)
    sm.mark_chord_active(False)
    sm.on_keyup(0.2)
    gen = sm.pending_generation
    sm.reset()
    assert sm.on_timeout(gen).action == "noop"


def test_double_tap_toggle_full_cycle() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    # tap 1
    sm.mark_chord_active(True)
    assert sm.on_keydown(0.0).action == "start_recording"
    sm.mark_chord_active(False)
    assert sm.on_keyup(0.2).action == "await_double_tap"
    # tap 2: latch
    sm.mark_chord_active(True)
    assert sm.on_keydown(0.4).action == "latch_toggle"
    sm.mark_chord_active(False)
    assert sm.on_keyup(0.5).action == "noop"  # release of latching tap
    assert sm.state == "TOGGLE_LATCHED"
    # third press: stop fires on release, not keydown
    sm.mark_chord_active(True)
    assert sm.on_keydown(3.0).action == "noop"
    assert sm.state == "TOGGLE_STOPPING"
    sm.mark_chord_active(False)
    t = sm.on_keyup(3.1)
    assert t.action == "stop_recording_toggle"
    assert t.cue == "toggle_off"
    assert sm.state == "IDLE"


def test_second_tap_held_long_stays_latched() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    sm.mark_chord_active(True)
    sm.on_keydown(0.0)
    sm.mark_chord_active(False)
    sm.on_keyup(0.2)
    sm.mark_chord_active(True)
    sm.on_keydown(0.4)
    sm.mark_chord_active(False)
    # 2nd tap held past the PTT threshold: latch already committed.
    assert sm.on_keyup(2.0).action == "noop"
    assert sm.state == "TOGGLE_LATCHED"


def test_exactly_threshold_is_ptt() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    sm.mark_chord_active(True)
    sm.on_keydown(0.0)
    sm.mark_chord_active(False)
    t = sm.on_keyup(0.5)
    assert t.action == "stop_recording_ptt"


def test_cancel_during_ptt_consumes_keyup() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    sm.mark_chord_active(True)
    sm.on_keydown(0.0)
    t = sm.on_cancel()
    assert t.action == "cancel"
    assert t.cue == "cancel"
    assert sm.state == "IDLE"
    sm.mark_chord_active(False)
    assert sm.on_keyup(1.0).action == "noop"  # consumed
    # Next press starts fresh.
    sm.mark_chord_active(True)
    assert sm.on_keydown(2.0).action == "start_recording"


def test_cancel_during_toggle_stopping() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    sm.mark_chord_active(True)
    sm.on_keydown(0.0)
    sm.mark_chord_active(False)
    sm.on_keyup(0.2)
    sm.mark_chord_active(True)
    sm.on_keydown(0.4)
    sm.mark_chord_active(False)
    sm.on_keyup(0.5)
    # Latched; press chord again and cancel instead of releasing.
    sm.mark_chord_active(True)
    sm.on_keydown(3.0)
    assert sm.state == "TOGGLE_STOPPING"
    t = sm.on_cancel()
    assert t.action == "cancel"
    assert sm.state == "IDLE"
    sm.mark_chord_active(False)
    assert sm.on_keyup(3.2).action == "noop"


def test_cancel_with_chord_inactive_is_noop() -> None:
    sm = HotkeyStateMachine()
    assert sm.on_cancel().action == "noop"


def test_cancel_repeated_while_chord_held_is_idempotent() -> None:
    sm = HotkeyStateMachine()
    sm.mark_chord_active(True)
    sm.on_keydown(0.0)
    assert sm.on_cancel().action == "cancel"
    assert sm.on_cancel().action == "cancel"
    assert sm.state == "IDLE"


def test_force_discard_only_from_pending() -> None:
    sm = HotkeyStateMachine()
    assert sm.force_discard().action == "noop"
    sm.mark_chord_active(True)
    sm.on_keydown(0.0)
    assert sm.force_discard().action == "noop"
    sm.mark_chord_active(False)
    sm.on_keyup(0.2)
    t = sm.force_discard()
    assert t.action == "discard_recording"
    assert sm.state == "IDLE"


def test_keydown_outside_chord_is_noop() -> None:
    sm = HotkeyStateMachine()
    sm.mark_chord_active(False)
    assert sm.on_keydown(0.0).action == "noop"


def test_reset_returns_to_idle() -> None:
    sm = HotkeyStateMachine()
    sm.mark_chord_active(True)
    sm.on_keydown(0.0)
    sm.reset()
    assert sm.state == "IDLE"
    assert not sm.is_chord_active


def test_toggle_mode_single_press_latches() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5, mode="toggle")
    sm.mark_chord_active(True)
    t = sm.on_keydown(0.0)
    assert t.action == "start_recording"
    assert t.cue == "toggle_on"
    assert sm.state == "TOGGLE_LATCHED"
    sm.mark_chord_active(False)
    # Releasing the key does not stop or reclassify the recording.
    assert sm.on_keyup(0.2).action == "noop"
    assert sm.state == "TOGGLE_LATCHED"
    # A second press stops, regardless of how long either press was held.
    sm.mark_chord_active(True)
    assert sm.on_keydown(5.0).action == "noop"
    assert sm.state == "TOGGLE_STOPPING"
    sm.mark_chord_active(False)
    t = sm.on_keyup(5.1)
    assert t.action == "stop_recording_toggle"
    assert t.cue == "toggle_off"
    assert sm.state == "IDLE"


def test_toggle_mode_long_hold_is_not_ptt() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5, mode="toggle")
    sm.mark_chord_active(True)
    assert sm.on_keydown(0.0).action == "start_recording"
    sm.mark_chord_active(False)
    assert sm.on_keyup(2.0).action == "noop"
    assert sm.state == "TOGGLE_LATCHED"


def test_toggle_mode_cancel_consumes_keyup() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5, mode="toggle")
    sm.mark_chord_active(True)
    sm.on_keydown(0.0)
    t = sm.on_cancel()
    assert t.action == "cancel"
    assert sm.state == "IDLE"
    sm.mark_chord_active(False)
    assert sm.on_keyup(0.3).action == "noop"


def test_state_machine_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        HotkeyStateMachine(mode="ptt")


def test_threshold_validation() -> None:
    with pytest.raises(ValueError):
        HotkeyStateMachine(threshold_seconds=0)
    with pytest.raises(ValueError):
        HotkeyStateMachine(threshold_seconds=6)
    with pytest.raises(ValueError):
        HotkeyStateMachine(double_tap_window_seconds=0)
    with pytest.raises(ValueError):
        HotkeyStateMachine(double_tap_window_seconds=3)


# --- Listener loop (with fake evdev device) ---


class _FakeEvent:
    __slots__ = ("_ts", "code", "type", "value")

    def __init__(self, type_: int, code: int, value: int, timestamp: float) -> None:
        self.type = type_
        self.code = code
        self.value = value
        self._ts = timestamp

    def timestamp(self) -> float:
        return self._ts


class _FakeDevice:
    def __init__(
        self,
        events: list[_FakeEvent],
        raise_after: bool = True,
        path: str = "/dev/input/event0",
    ) -> None:
        self._events = list(events)
        self._raise_after = raise_after
        self.closed = False
        self.path = path

    def read_loop(self):
        yield from self._events
        if self._raise_after:
            raise OSError("simulated end of device events")

    def close(self) -> None:
        self.closed = True


def _wait_for(predicate, timeout: float = 2.0, step: float = 0.01) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(step)


class _ListenerCallbacks:
    def __init__(self) -> None:
        self.on_start = MagicMock()
        self.on_stop = MagicMock()
        self.on_toggle_off = MagicMock()
        self.on_discard = MagicMock()
        self.on_cancel = MagicMock()
        self.feedback = MagicMock()


def _run_listener_with_events(
    events: list[_FakeEvent],
    *,
    double_tap_window_seconds: float = 0.35,
    cancel_binding: HotkeyBinding | None = None,
    binding_str: str = "KEY_LEFTCTRL+KEY_A",
    done=None,
) -> _ListenerCallbacks:
    binding = HotkeyBinding.parse(binding_str)
    sm = HotkeyStateMachine(
        threshold_seconds=0.5, double_tap_window_seconds=double_tap_window_seconds
    )
    cb = _ListenerCallbacks()
    fake_device = _FakeDevice(events)
    with (
        patch("stenographer.hotkey.listener.evdev.InputDevice", return_value=fake_device),
        patch("stenographer.hotkey.listener.auto_detect_path", return_value=None),
        patch("stenographer.hotkey.listener._RETRY_INTERVAL_SECONDS", 0.0),
        patch("stenographer.hotkey.listener._RETRY_TIMEOUT_SECONDS", 0.01),
        patch("stenographer.hotkey.listener.sys") as mock_sys,
    ):
        mock_sys.exit = MagicMock(side_effect=SystemExit(1))
        listener = HotkeyListener(
            binding=binding,
            device_path="/dev/input/event0",
            state_machine=sm,
            on_start=cb.on_start,
            on_stop=cb.on_stop,
            on_toggle_off=cb.on_toggle_off,
            feedback=cb.feedback,
            cancel_binding=cancel_binding,
            on_discard=cb.on_discard,
            on_cancel=cb.on_cancel,
        )
        listener.start()
        if done is None:

            def done(c: _ListenerCallbacks) -> bool:
                return bool(
                    c.on_stop.call_count
                    or c.on_toggle_off.call_count
                    or c.on_discard.call_count
                    or c.on_cancel.call_count
                )

        _wait_for(lambda: done(cb))
        time.sleep(0.05)
        listener.stop(timeout=2.0)
    return cb


def test_listener_ptt_path() -> None:
    events = [
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 0.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 0.1),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 0.7),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 0.8),
    ]
    cb = _run_listener_with_events(events)
    assert cb.on_start.call_count == 1
    assert cb.on_stop.call_count == 1
    cb.on_stop.assert_called_once_with("ptt")
    cb.feedback.play.assert_any_call("ptt_on")
    cb.feedback.play.assert_any_call("ptt_off")


def test_listener_double_tap_toggle_path() -> None:
    events = [
        # tap 1 (short)
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 0.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 0.1),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 0.2),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 0.25),
        # tap 2 within the window: latch toggle
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 0.4),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 0.45),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 0.5),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 0.55),
        # third press: toggle off on its release
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 3.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 3.1),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 3.2),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 3.25),
    ]
    cb = _run_listener_with_events(events)
    assert cb.on_start.call_count == 1
    cb.on_toggle_off.assert_called_once()
    cb.on_discard.assert_not_called()
    cb.feedback.play.assert_any_call("ptt_on")
    cb.feedback.play.assert_any_call("toggle_on")
    cb.feedback.play.assert_any_call("toggle_off")


def test_listener_single_tap_discards_after_window() -> None:
    events = [
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 0.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 0.1),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 0.2),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 0.25),
    ]
    cb = _run_listener_with_events(events, double_tap_window_seconds=0.05)
    assert cb.on_start.call_count == 1
    cb.on_discard.assert_called_once()
    cb.on_stop.assert_not_called()
    cb.on_toggle_off.assert_not_called()
    cb.feedback.play.assert_any_call("discard")


def test_listener_cancel_chord_during_ptt() -> None:
    esc = HotkeyBinding.parse("KEY_ESC")
    events = [
        # chord held, then Esc pressed while held
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 0.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 0.1),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_ESC, 1, 0.3),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_ESC, 0, 0.35),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 0.9),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 0.95),
    ]
    cb = _run_listener_with_events(events, cancel_binding=esc)
    assert cb.on_start.call_count == 1
    cb.on_cancel.assert_called_once()
    cb.on_stop.assert_not_called()  # keyup was consumed
    cb.on_toggle_off.assert_not_called()
    cb.feedback.play.assert_any_call("cancel")


def test_listener_cancel_during_latched_toggle() -> None:
    esc = HotkeyBinding.parse("KEY_ESC")
    events = [
        # double-tap to latch
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 0.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 0.1),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 0.2),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 0.25),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 0.4),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 0.45),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 0.5),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 0.55),
        # hold chord + Esc: cancel instead of toggle-off
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 3.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 3.1),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_ESC, 1, 3.2),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_ESC, 0, 3.25),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 3.3),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 3.35),
    ]
    cb = _run_listener_with_events(events, cancel_binding=esc)
    assert cb.on_start.call_count == 1
    cb.on_cancel.assert_called_once()
    cb.on_toggle_off.assert_not_called()
    cb.on_stop.assert_not_called()


def test_listener_esc_alone_is_inert() -> None:
    esc = HotkeyBinding.parse("KEY_ESC")
    events = [
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_ESC, 1, 0.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_ESC, 0, 0.05),
        # normal PTT afterwards still works
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 1.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 1.1),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 1.7),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 1.75),
    ]
    cb = _run_listener_with_events(events, cancel_binding=esc)
    cb.on_cancel.assert_not_called()
    cb.on_stop.assert_called_once_with("ptt")


def test_listener_stuck_key_recovers() -> None:
    """A keydown for a key already held means we missed its release; the
    listener synthesizes a release+press so the chord can fire again."""
    events = [
        # press, but the release is never delivered (multi-HID dropped it)
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_RIGHTCTRL, 1, 0.0),
        # next press of the same key arrives while still marked held:
        # synthetic keyup (long hold => PTT stop) + fresh keydown
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_RIGHTCTRL, 1, 2.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_RIGHTCTRL, 0, 2.8),
    ]
    cb = _run_listener_with_events(
        events,
        binding_str="KEY_RIGHTCTRL",
        done=lambda c: c.on_stop.call_count >= 2,
    )
    assert cb.on_start.call_count == 2
    assert cb.on_stop.call_count == 2


def test_listener_reentrant_lock_callback() -> None:
    """Regression: a non-reentrant Lock would deadlock the reader."""
    binding = HotkeyBinding.parse("KEY_RIGHTCTRL")
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    lock = threading.RLock()
    feedback = MagicMock()

    start_calls: list[float] = []
    stop_calls: list[tuple[str, float]] = []
    toggle_off_calls: list[float] = []

    def on_start() -> None:
        with lock:
            start_calls.append(time.monotonic())

    def on_stop(mode: str) -> None:
        with lock:
            stop_calls.append((mode, time.monotonic()))

    def on_toggle_off() -> None:
        with lock:
            toggle_off_calls.append(time.monotonic())

    events = [
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_RIGHTCTRL, 1, 0.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_RIGHTCTRL, 0, 0.7),
    ]
    fake_device = _FakeDevice(events)
    with (
        patch("stenographer.hotkey.listener.evdev.InputDevice", return_value=fake_device),
        patch("stenographer.hotkey.listener.auto_detect_path", return_value=None),
        patch("stenographer.hotkey.listener._RETRY_INTERVAL_SECONDS", 0.0),
        patch("stenographer.hotkey.listener._RETRY_TIMEOUT_SECONDS", 0.01),
        patch("stenographer.hotkey.listener.sys") as mock_sys,
    ):
        mock_sys.exit = MagicMock(side_effect=SystemExit(1))
        listener = HotkeyListener(
            binding=binding,
            device_path="/dev/input/event0",
            state_machine=sm,
            on_start=on_start,
            on_stop=on_stop,
            on_toggle_off=on_toggle_off,
            feedback=feedback,
            lock=lock,
        )
        listener.start()
        _wait_for(lambda: len(stop_calls) >= 1, timeout=2.0)
        listener.stop(timeout=2.0)
    assert len(start_calls) == 1
    assert len(stop_calls) == 1
    assert stop_calls[0][0] == "ptt"
    assert feedback.play.call_count == 2


def test_auto_detect_path_returns_none_when_no_input() -> None:
    with patch("pathlib.Path.glob", return_value=[]):
        assert auto_detect_path() is None
