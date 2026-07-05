# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure state machine for the hybrid push-to-talk / double-tap-toggle trigger."""

from __future__ import annotations

from typing import Literal, NamedTuple

State = Literal["IDLE", "RECORDING_PTT", "PENDING_TAP", "TOGGLE_LATCHED", "TOGGLE_STOPPING"]
Action = Literal[
    "start_recording",
    "stop_recording_ptt",
    "stop_recording_toggle",
    "latch_toggle",
    "await_double_tap",
    "discard_recording",
    "cancel",
    "noop",
]


class Transition(NamedTuple):
    action: Action
    cue: str | None


class HotkeyStateMachine:
    """Decides what a hotkey press means based on its duration.

    Press duration >= ``threshold_seconds`` => push-to-talk (PTT).
    A short tap enters PENDING_TAP: recording continues while waiting
    for a second tap within ``double_tap_window_seconds``. A second tap
    latches toggle mode; if the window expires (the listener delivers
    ``on_timeout``), the recording is discarded.

    The state machine is pure: it does not call the audio feedback
    player, the recorder, any timer, or any I/O. The caller observes
    the returned :class:`Transition` and dispatches accordingly. The
    double-tap window timer is owned by the listener, which arms it on
    the ``await_double_tap`` action and calls :meth:`on_timeout` with
    the generation captured at arming time; stale generations are
    ignored, so a lost race with a second keydown is harmless.
    """

    def __init__(
        self,
        threshold_seconds: float = 0.5,
        double_tap_window_seconds: float = 0.35,
    ) -> None:
        if threshold_seconds <= 0 or threshold_seconds > 5:
            raise ValueError(f"threshold_seconds must be in (0, 5], got {threshold_seconds}")
        if double_tap_window_seconds <= 0 or double_tap_window_seconds > 2:
            raise ValueError(
                f"double_tap_window_seconds must be in (0, 2], got {double_tap_window_seconds}"
            )
        self._threshold = threshold_seconds
        self._double_tap_window = double_tap_window_seconds
        self._state: State = "IDLE"
        self._press_start: float | None = None
        self._chord_active: bool = False
        self._consumed: bool = False
        self._pending_generation: int = 0

    @property
    def state(self) -> State:
        return self._state

    @property
    def is_chord_active(self) -> bool:
        return self._chord_active

    @property
    def threshold_seconds(self) -> float:
        return self._threshold

    @property
    def double_tap_window_seconds(self) -> float:
        return self._double_tap_window

    @property
    def pending_generation(self) -> int:
        return self._pending_generation

    def mark_chord_active(self, active: bool) -> None:
        if active and self._chord_active:
            return
        if not active and not self._chord_active:
            return
        self._chord_active = active

    def on_keydown(self, timestamp: float) -> Transition:
        if not self._chord_active:
            return Transition("noop", None)
        if self._state == "IDLE":
            self._press_start = timestamp
            self._state = "RECORDING_PTT"
            return Transition("start_recording", "ptt_on")
        if self._state == "PENDING_TAP":
            self._pending_generation += 1
            self._press_start = None
            self._state = "TOGGLE_LATCHED"
            return Transition("latch_toggle", "toggle_on")
        if self._state == "TOGGLE_LATCHED":
            self._state = "TOGGLE_STOPPING"
            return Transition("noop", None)
        return Transition("noop", None)

    def on_keyup(self, timestamp: float) -> Transition:
        if self._consumed:
            self._consumed = False
            return Transition("noop", None)
        if self._state == "RECORDING_PTT":
            if self._press_start is None:
                return Transition("noop", None)
            duration = timestamp - self._press_start
            self._press_start = None
            if duration >= self._threshold:
                self._state = "IDLE"
                return Transition("stop_recording_ptt", "ptt_off")
            self._state = "PENDING_TAP"
            self._pending_generation += 1
            return Transition("await_double_tap", None)
        if self._state == "TOGGLE_STOPPING":
            self._state = "IDLE"
            return Transition("stop_recording_toggle", "toggle_off")
        return Transition("noop", None)

    def on_timeout(self, generation: int) -> Transition:
        if self._state != "PENDING_TAP" or generation != self._pending_generation:
            return Transition("noop", None)
        self._state = "IDLE"
        return Transition("discard_recording", "discard")

    def on_cancel(self) -> Transition:
        """Cancel chord fired (main chord held + cancel key pressed).

        The current chord press is consumed so its keyup does not stop,
        reclassify, or start anything. Idempotent while the chord stays
        held: repeated cancel keydowns re-emit ``cancel``.
        """
        if not self._chord_active:
            return Transition("noop", None)
        self._pending_generation += 1
        self._press_start = None
        self._state = "IDLE"
        self._consumed = True
        return Transition("cancel", "cancel")

    def force_discard(self) -> Transition:
        """Discard a pending-tap recording (used on device loss)."""
        if self._state != "PENDING_TAP":
            return Transition("noop", None)
        self._pending_generation += 1
        self._state = "IDLE"
        return Transition("discard_recording", "discard")

    def reset(self) -> None:
        self._state = "IDLE"
        self._press_start = None
        self._chord_active = False
        self._consumed = False
        self._pending_generation += 1
