# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure state machine for the hybrid push-to-talk / toggle trigger."""

from __future__ import annotations

from typing import Literal, NamedTuple

Mode = Literal["ptt", "toggle"]
State = Literal["IDLE", "RECORDING"]
Action = Literal[
    "start_recording",
    "stop_recording_ptt",
    "stop_recording_toggle",
    "reclassify_toggle",
    "noop",
]


class Transition(NamedTuple):
    action: Action
    cue: str | None


class HotkeyStateMachine:
    """Decides what a hotkey press means based on its duration.

    Press duration >= ``threshold_seconds`` => push-to-talk (PTT).
    Press duration < ``threshold_seconds`` => toggle.

    The state machine is pure: it does not call the audio feedback
    player, the recorder, or any I/O. The caller observes the returned
    :class:`Transition` and dispatches accordingly.
    """

    def __init__(self, threshold_seconds: float = 0.5) -> None:
        if threshold_seconds <= 0 or threshold_seconds > 5:
            raise ValueError(f"threshold_seconds must be in (0, 5], got {threshold_seconds}")
        self._threshold = threshold_seconds
        self._state: State = "IDLE"
        self._mode: Mode = "ptt"
        self._press_start: float | None = None
        self._chord_active: bool = False

    @property
    def state(self) -> State:
        return self._state

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def is_chord_active(self) -> bool:
        return self._chord_active

    @property
    def threshold_seconds(self) -> float:
        return self._threshold

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
            self._state = "RECORDING"
            self._mode = "ptt"
            return Transition("start_recording", "ptt_on")
        if self._state == "RECORDING":
            self._state = "IDLE"
            self._press_start = None
            self._mode = "ptt"
            return Transition("stop_recording_toggle", "toggle_off")
        return Transition("noop", None)

    def on_keyup(self, timestamp: float) -> Transition:
        if self._state != "RECORDING":
            return Transition("noop", None)
        if self._press_start is None:
            return Transition("noop", None)
        duration = timestamp - self._press_start
        if duration >= self._threshold:
            self._state = "IDLE"
            self._press_start = None
            return Transition("stop_recording_ptt", "ptt_off")
        self._mode = "toggle"
        self._press_start = None
        return Transition("reclassify_toggle", "toggle_on")

    def reset(self) -> None:
        self._state = "IDLE"
        self._mode = "ptt"
        self._press_start = None
        self._chord_active = False
