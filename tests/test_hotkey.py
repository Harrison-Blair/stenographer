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
    assert sm.mode == "ptt"
    assert not sm.is_chord_active


def test_ptt_path_keydown_then_long_keyup() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    sm.mark_chord_active(True)
    t = sm.on_keydown(0.0)
    assert t.action == "start_recording"
    assert t.cue == "ptt_on"
    assert sm.state == "RECORDING"
    assert sm.mode == "ptt"
    sm.mark_chord_active(False)
    t = sm.on_keyup(0.6)
    assert t.action == "stop_recording_ptt"
    assert t.cue == "ptt_off"
    assert sm.state == "IDLE"


def test_toggle_path_short_keyup_then_second_keydown() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    sm.mark_chord_active(True)
    assert sm.on_keydown(0.0).action == "start_recording"
    sm.mark_chord_active(False)
    t = sm.on_keyup(0.2)
    assert t.action == "reclassify_toggle"
    assert t.cue == "toggle_on"
    assert sm.state == "RECORDING"
    assert sm.mode == "toggle"
    sm.mark_chord_active(True)
    t = sm.on_keydown(2.0)
    assert t.action == "stop_recording_toggle"
    assert t.cue == "toggle_off"
    assert sm.state == "IDLE"


def test_exactly_threshold_is_ptt() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    sm.mark_chord_active(True)
    sm.on_keydown(0.0)
    sm.mark_chord_active(False)
    t = sm.on_keyup(0.5)
    assert t.action == "stop_recording_ptt"


def test_anti_repeat_ignores_redundant_keydown() -> None:
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    sm.mark_chord_active(True)
    assert sm.on_keydown(0.0).action == "start_recording"
    sm.mark_chord_active(False)
    sm.on_keyup(0.6)
    sm.mark_chord_active(True)
    assert sm.on_keydown(0.7).action == "start_recording"
    sm.mark_chord_active(False)
    t = sm.on_keyup(1.3)
    assert t.action == "stop_recording_ptt"


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


def test_threshold_validation() -> None:
    with pytest.raises(ValueError):
        HotkeyStateMachine(threshold_seconds=0)
    with pytest.raises(ValueError):
        HotkeyStateMachine(threshold_seconds=6)


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


def _run_listener_with_events(
    events: list[_FakeEvent],
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    binding = HotkeyBinding.parse("KEY_LEFTCTRL+KEY_A")
    sm = HotkeyStateMachine(threshold_seconds=0.5)
    on_start = MagicMock()
    on_stop = MagicMock()
    on_toggle_off = MagicMock()
    feedback = MagicMock()
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
        )
        listener.start()
        _wait_for(lambda: on_stop.call_count >= 1 or on_toggle_off.call_count >= 1)
        time.sleep(0.05)
        listener.stop(timeout=2.0)
    return on_start, on_stop, on_toggle_off, feedback


def test_listener_ptt_path() -> None:
    events = [
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 0.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 0.1),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 0.7),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 0.8),
    ]
    on_start, on_stop, _on_toggle_off, feedback = _run_listener_with_events(events)
    assert on_start.call_count == 1
    assert on_stop.call_count == 1
    on_stop.assert_called_once_with("ptt")
    feedback.play.assert_any_call("ptt_on")
    feedback.play.assert_any_call("ptt_off")


def test_listener_toggle_path_two_presses() -> None:
    events = [
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 0.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 0.1),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 0.2),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 0.25),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1, 1.0),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1, 1.1),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0, 1.2),
        _FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0, 1.25),
    ]
    on_start, _on_stop, on_toggle_off, feedback = _run_listener_with_events(events)
    assert on_start.call_count == 1
    on_toggle_off.assert_called_once()
    feedback.play.assert_any_call("ptt_on")
    feedback.play.assert_any_call("toggle_on")
    feedback.play.assert_any_call("toggle_off")


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
