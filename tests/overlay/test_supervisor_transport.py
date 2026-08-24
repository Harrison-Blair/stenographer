# SPDX-License-Identifier: GPL-3.0-or-later
"""The supervisor's shutdown policy over the platform helper transport.

Pure: a stand-in ``HelperProcess`` records the call sequence, so no child
process, pipe, or signal is involved. What is asserted is the *policy* the
core owns — who gets a grace period — not the escalation itself, which is
host semantics inside ``platform/linux/helper.py``.
"""

from __future__ import annotations

from stenographer.overlay.supervisor import _SHUTDOWN_GRACE_SECONDS, OverlaySupervisor


class _HelperSpy:
    """Stands in for a HelperProcess: ``_reap`` only sequences three methods."""

    def __init__(self, *, running: bool, exits_while_waiting: bool = False) -> None:
        self._running = running
        self._exits_while_waiting = exits_while_waiting
        self.calls: list[tuple[str, float]] = []

    def is_running(self) -> bool:
        return self._running

    def wait(self, timeout: float) -> None:
        self.calls.append(("wait", timeout))
        if self._exits_while_waiting:
            self._running = False

    def terminate(self, grace_seconds: float) -> None:
        self.calls.append(("terminate", grace_seconds))
        self._running = False


def test_expected_exit_gets_its_grace_period_before_the_host_escalates():
    # A helper that was told to shut down is given the full grace period to
    # leave on its own; terminate() then only reaps the exited child.
    helper = _HelperSpy(running=True, exits_while_waiting=True)

    OverlaySupervisor._reap(helper, expected=True)

    assert helper.calls == [
        ("wait", _SHUTDOWN_GRACE_SECONDS),
        ("terminate", _SHUTDOWN_GRACE_SECONDS),
    ]


def test_unexpected_exit_escalates_immediately_without_dead_time():
    # Seen to FAIL against a _reap that waits unconditionally: the crashed or
    # wedged helper would hold the supervisor thread for the grace period with
    # nothing to wait for.
    helper = _HelperSpy(running=True)

    OverlaySupervisor._reap(helper, expected=False)

    assert helper.calls == [("terminate", _SHUTDOWN_GRACE_SECONDS)]


def test_an_already_exited_helper_is_never_waited_on():
    helper = _HelperSpy(running=False)

    OverlaySupervisor._reap(helper, expected=True)

    assert helper.calls == [("terminate", _SHUTDOWN_GRACE_SECONDS)]
