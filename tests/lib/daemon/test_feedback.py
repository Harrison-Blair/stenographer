# SPDX-License-Identifier: GPL-3.0-or-later
"""Cue and status publication isolate their collaborators' failures."""

from __future__ import annotations

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.daemon.feedback import (
    _play_cue,
    _publish_loading_activity,
    _publish_status,
)


class _BrokenFeedback:
    """A cue player whose failure is host vocabulary (a device, an OS error)."""

    def __init__(self) -> None:
        self.attempts: list[str] = []

    def play(self, name: str) -> None:
        self.attempts.append(name)
        raise OSError("cue device busy")


class _BrokenStatus:
    def __init__(self) -> None:
        self.attempts: list[object] = []

    def publish(self, state: OverlayState) -> int:
        self.attempts.append(state)
        raise RuntimeError("overlay pipe closed")

    def loading_activity(self, active: bool) -> None:
        self.attempts.append(active)
        raise RuntimeError("overlay pipe closed")


def test_a_failing_cue_player_never_reaches_the_caller(daemon_logs):
    feedback = _BrokenFeedback()

    _play_cue(feedback, "record_start")

    assert feedback.attempts == ["record_start"]
    assert "feedback: cue_failed cue=record_start error=OSError" in daemon_logs.text
    assert 'detail="cue device busy"' in daemon_logs.text


def test_a_failing_overlay_publish_never_reaches_the_caller(daemon_logs):
    status = _BrokenStatus()

    _publish_status(status, OverlayState.RECORDING)

    assert status.attempts == [OverlayState.RECORDING]
    assert "overlay: publish_failed state=recording error=RuntimeError" in daemon_logs.text
    assert 'detail="overlay pipe closed"' in daemon_logs.text


def test_a_failing_loading_activity_never_reaches_the_caller(daemon_logs):
    status = _BrokenStatus()

    _publish_loading_activity(status, True)
    _publish_loading_activity(status, False)

    assert status.attempts == [True, False]
    assert "overlay: loading_activity_failed active=1 error=RuntimeError" in daemon_logs.text
    assert "overlay: loading_activity_failed active=0 error=RuntimeError" in daemon_logs.text
