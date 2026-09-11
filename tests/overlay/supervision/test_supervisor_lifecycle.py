# SPDX-License-Identifier: GPL-3.0-or-later
"""The supervisor's own thread, driven through real NDJSON socket pairs.

``OverlaySupervisor`` is the daemon-side sink: it owns the helper's lifetime,
the readiness deadline, the restart budget, and the framing in both directions.
None of that is visible from a pure call, so each test here runs the real
worker thread against a ``HelperProcess`` made of two real ``socket.socketpair`` pairs
and asserts on the bytes that reached the helper's stdin. Sockets support
selector waits on Windows as well as POSIX hosts.

The one injected seam is ``current_platform``: the host is where a child
process would come from, and this suite deliberately spawns none.
"""

from __future__ import annotations

import functools
import logging
import selectors
import socket
import threading
import time
from collections import deque

import numpy as np
import pytest

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.codec import decode_message, encode_message
from stenographer.overlay.protocol.command import Command
from stenographer.overlay.protocol.line_reader import LineReader
from stenographer.overlay.protocol.messages import (
    CommandMessage,
    LoadingActivityMessage,
    ReadyMessage,
    SpectrumMessage,
    StateMessage,
    UnavailableMessage,
)
from stenographer.overlay.protocol.unavailablereason import UnavailableReason
from stenographer.overlay.supervision import overlay_supervisor as supervision
from stenographer.overlay.supervision.overlay_supervisor import OverlaySupervisor
from stenographer.overlay.supervision.policy import helper_ready_timed_out

# Generous upper bounds on a failure; a passing test wakes as soon as the
# supervisor thread has actually done the thing being asserted.
_DEADLINE = 10.0

_JOIN_SECONDS = 5.0

_LOG = "stenographer.overlay.supervision.constants"


class _SocketHelper:
    """A ``HelperProcess`` made of two real socket pairs instead of a child process.

    The supervisor writes protocol records into one and reads the helper's
    replies from the other, exactly as it would with a spawned helper; the test
    holds the opposite end of both.
    """

    def __init__(self) -> None:
        self._stdin_read, self._stdin_write = socket.socketpair()
        self._stdout_read, self._stdout_write = socket.socketpair()
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._stdout_read, selectors.EVENT_READ)
        self._reader = LineReader()
        self._records: deque[object] = deque()
        self._running = True
        self._stdin_open = True
        self._stdout_open = True
        self.terminated = 0
        self.closed = 0

    # --- the protocol the supervisor drives --------------------------------

    def write(self, data: bytes) -> None:
        self._stdin_write.sendall(data)

    def close_input(self) -> None:
        if self._stdin_open:
            self._stdin_open = False
            self._stdin_write.shutdown(socket.SHUT_WR)

    def wait_readable(self, timeout: float) -> bool:
        return bool(self._selector.select(timeout))

    def read(self, size: int) -> bytes:
        try:
            return self._stdout_read.recv(size)
        except OSError:
            return b""

    def is_running(self) -> bool:
        return self._running

    def wait(self, timeout: float) -> None:
        self._running = False

    def terminate(self, grace_seconds: float) -> None:
        self.terminated += 1
        self._running = False

    def close(self) -> None:
        self.closed += 1
        self._selector.close()

    # --- the end of the wire the test holds --------------------------------

    def reply(self, message) -> None:
        self._stdout_write.sendall(encode_message(message).encode("ascii"))

    def send_raw(self, payload: bytes) -> None:
        self._stdout_write.sendall(payload)

    def close_output(self) -> None:
        """End the helper's stdout the way a dying child would."""
        if self._stdout_open:
            self._stdout_open = False
            self._stdout_write.shutdown(socket.SHUT_WR)

    def records(self, count: int, *, deadline: float = _DEADLINE) -> list[object]:
        """Return the next *count* records the supervisor wrote, in order."""
        collected: list[object] = []
        selector = selectors.DefaultSelector()
        selector.register(self._stdin_read, selectors.EVENT_READ)
        end = time.monotonic() + deadline
        try:
            while len(collected) < count and time.monotonic() < end:
                if self._records:
                    collected.append(self._records.popleft())
                    continue
                if not selector.select(0.05):
                    continue
                chunk = self._stdin_read.recv(4096)
                if not chunk:
                    break
                self._records.extend(decode_message(record) for record in self._reader.feed(chunk))
        finally:
            selector.close()
        assert len(collected) >= count, collected
        return collected[:count]

    def next_matching(self, kind, *, deadline: float = _DEADLINE):
        """Return the first record of type *kind*, skipping any frames before it."""
        end = time.monotonic() + deadline
        while True:
            remaining = end - time.monotonic()
            assert remaining > 0, f"the supervisor never wrote a {kind.__name__}"
            (message,) = self.records(1, deadline=remaining)
            if isinstance(message, kind):
                return message

    def dispose(self) -> None:
        self.close_input()
        self.close_output()
        self._selector.close()
        for endpoint in (
            self._stdin_read,
            self._stdin_write,
            self._stdout_read,
            self._stdout_write,
        ):
            endpoint.close()


class _Transport:
    """Hands out prepared helpers, or refuses, and counts every attempt."""

    def __init__(self, helpers=(), error: BaseException | None = None) -> None:
        self._helpers = list(helpers)
        self._error = error
        self.spawns = 0
        self.commands: list[tuple[str, ...]] = []
        self.stderr_paths: list[object] = []
        self.attempted = threading.Semaphore(0)

    def spawn(self, command, *, stderr_path=None):
        self.spawns += 1
        self.commands.append(tuple(command))
        self.stderr_paths.append(stderr_path)
        try:
            if self._error is not None:
                raise self._error
            if not self._helpers:
                raise OSError("no helper left for this test")
            return self._helpers.pop(0)
        finally:
            self.attempted.release()


class _Platform:
    """The one method the supervisor asks its host for."""

    def __init__(self, transport=None, error: BaseException | None = None) -> None:
        self._transport = transport
        self._error = error

    def helper_transport(self):
        if self._error is not None:
            raise self._error
        return self._transport

    def overlay_backends(self):  # pragma: no cover - parent never constructs one
        raise AssertionError("the supervisor never constructs a backend")

    def guidance(self):  # pragma: no cover - guidance is a doctor concern
        raise AssertionError("the supervisor never renders guidance")


@pytest.fixture
def host(monkeypatch, tmp_path):
    """Install a fake host and keep the helper log out of the real state dir."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(logging.getLogger("stenographer"), "propagate", True)
    helpers: list[_SocketHelper] = []

    def install(*, transport=None, error=None):
        monkeypatch.setattr(supervision, "current_platform", lambda: _Platform(transport, error))

    try:
        yield install, helpers
    finally:
        for helper in helpers:
            helper.dispose()


@pytest.fixture
def supervisor():
    """Start real supervisors and make sure none outlives its test."""
    started: list[OverlaySupervisor] = []

    def start(*args, **kwargs) -> OverlaySupervisor:
        instance = OverlaySupervisor(*args, **kwargs)
        started.append(instance)
        return instance

    try:
        yield start
    finally:
        for instance in started:
            instance.close()


def _short_ready_deadline(monkeypatch) -> None:
    """Use the real readiness policy with a deadline a test can afford.

    Three seconds of real waiting would be testing the clock; the policy itself
    is pinned separately in ``test_supervisor``.
    """
    monkeypatch.setattr(
        supervision,
        "helper_ready_timed_out",
        functools.partial(helper_ready_timed_out, timeout=0.05),
    )


def _finished(instance: OverlaySupervisor) -> bool:
    instance._thread.join(_JOIN_SECONDS)
    return not instance._thread.is_alive()


def test_a_ready_helper_is_fed_state_then_spectrum_then_shutdown(host, supervisor) -> None:
    """The whole outbound contract in one session: metadata is ordered, frames
    carry the generation of the recording they belong to, and closing sends
    exactly one command before stdin is closed.
    """
    install, helpers = host
    helper = _SocketHelper()
    helpers.append(helper)
    transport = _Transport([helper])
    install(transport=transport)

    instance = supervisor()
    assert transport.attempted.acquire(timeout=_DEADLINE)
    helper.reply(ReadyMessage(Backend.XWAYLAND))

    instance.publish(OverlayState.RECORDING)
    state = helper.next_matching(StateMessage)
    assert state.state is OverlayState.RECORDING

    # Frames are produced on a cadence, so a handful of blocks guarantees the
    # supervisor's loop finds one pending without pacing the assertion below.
    tone = np.sin(np.linspace(0.0, 200.0, 1024)).astype(np.float32)
    for _ in range(6):
        instance.audio_block(tone, 16000, 0)
        time.sleep(0.02)
    spectrum = helper.next_matching(SpectrumMessage)
    assert spectrum.generation == state.generation
    assert len(spectrum.levels) == SPECTRUM_BANDS

    # Leaving the recording runs one cleanup pass, so no frame from the old
    # generation can reach the helper after the state it belonged to.
    instance.publish(OverlayState.HIDDEN)
    hidden = helper.next_matching(StateMessage)
    assert hidden.state is OverlayState.HIDDEN

    instance.close()
    assert helper.next_matching(CommandMessage) == CommandMessage(Command.SHUTDOWN)
    assert _finished(instance)
    assert helper.terminated == 1
    assert helper.closed >= 1


def test_the_spawned_helper_command_is_the_private_re_exec_with_a_log_file(
    host, supervisor
) -> None:
    install, helpers = host
    helper = _SocketHelper()
    helpers.append(helper)
    transport = _Transport([helper])
    install(transport=transport)

    instance = supervisor()
    assert transport.attempted.acquire(timeout=_DEADLINE)
    instance.close()
    assert _finished(instance)

    assert transport.commands[0][-1] == "_overlay"
    assert transport.stderr_paths[0] is not None
    assert transport.stderr_paths[0].name == "overlay-helper.log"


def test_a_helper_that_never_announces_readiness_is_replaced_then_abandoned(
    host, supervisor, monkeypatch, caplog
) -> None:
    """A helper that dies without a record tells the parent nothing, so the
    readiness deadline is the only thing that can end the session.
    """
    _short_ready_deadline(monkeypatch)
    install, helpers = host
    first, second = _SocketHelper(), _SocketHelper()
    helpers.extend((first, second))
    transport = _Transport([first, second])
    install(transport=transport)

    with caplog.at_level(logging.WARNING, logger=_LOG):
        instance = supervisor()
        assert _finished(instance)

    assert transport.spawns == 2
    assert (first.terminated, second.terminated) == (1, 1)
    messages = [record.getMessage() for record in caplog.records]
    assert messages.count("overlay: helper_ready_timeout") == 2
    assert "overlay: helper_disabled reason=restart_budget_exhausted" in messages


def test_a_malformed_helper_record_fails_the_stream_without_echoing_it(
    host, supervisor, caplog
) -> None:
    """The parent never reflects a record it could not parse — a helper whose
    stdout has been corrupted by a library's stray write must not put that
    text into the daemon's log.
    """
    install, helpers = host
    first, second = _SocketHelper(), _SocketHelper()
    helpers.extend((first, second))
    transport = _Transport([first, second])
    install(transport=transport)

    with caplog.at_level(logging.WARNING, logger=_LOG):
        instance = supervisor()
        assert transport.attempted.acquire(timeout=_DEADLINE)
        first.send_raw(b"secret backend chatter\n")
        assert transport.attempted.acquire(timeout=_DEADLINE)
        second.send_raw(b"secret backend chatter\n")
        assert _finished(instance)

    assert transport.spawns == 2
    protocol_errors = [
        record.getMessage()
        for record in caplog.records
        if "helper_protocol_error" in record.getMessage()
    ]
    assert len(protocol_errors) == 2, [record.getMessage() for record in caplog.records]
    assert all("phase=feed" in message for message in protocol_errors)
    assert all("secret backend chatter" not in message for message in protocol_errors)


def test_an_unavailable_helper_is_believed_rather_than_restarted(host, supervisor) -> None:
    """An overlay that cannot exist on this session must not spend the restart
    budget: the second attempt would reach the same conclusion.
    """
    install, helpers = host
    helper = _SocketHelper()
    helpers.append(helper)
    transport = _Transport([helper])
    install(transport=transport)

    instance = supervisor()
    assert transport.attempted.acquire(timeout=_DEADLINE)
    helper.reply(UnavailableMessage(UnavailableReason.NO_X_DISPLAY))

    assert _finished(instance)
    assert transport.spawns == 1
    assert helper.terminated == 1


def test_a_transport_that_cannot_spawn_retries_exactly_once(host, supervisor, caplog) -> None:
    install, _helpers = host
    transport = _Transport(error=OSError("fork failed"))
    install(transport=transport)

    with caplog.at_level(logging.WARNING, logger=_LOG):
        instance = supervisor()
        assert _finished(instance)

    assert transport.spawns == 2
    messages = [record.getMessage() for record in caplog.records]
    assert messages.count("overlay: helper_start_failed error_type=OSError") == 2


def test_a_host_without_an_overlay_ends_the_supervisor_thread_immediately(
    host, supervisor, caplog
) -> None:
    install, _helpers = host
    install(error=UnsupportedPlatformError("no overlay on this host"))

    with caplog.at_level(logging.INFO, logger=_LOG):
        instance = supervisor()
        assert _finished(instance)

    assert "overlay: helper_unavailable reason=unsupported_platform" in [
        record.getMessage() for record in caplog.records
    ]


def test_a_helper_handle_that_breaks_the_serve_loop_is_still_reaped(
    host, supervisor, caplog
) -> None:
    """A child left running while the supervisor decides what went wrong would
    keep its display surface up for the rest of the session.
    """

    class _BrokenHelper(_SocketHelper):
        def is_running(self) -> bool:
            raise RuntimeError("host handle went bad")

    install, helpers = host
    broken = _BrokenHelper()
    helpers.append(broken)
    transport = _Transport([broken])
    install(transport=transport)

    with caplog.at_level(logging.WARNING, logger=_LOG):
        instance = supervisor()
        assert _finished(instance)

    # Pinned at the counts production currently produces: ``_serve``'s own
    # ``finally`` reaps the helper and ``_thread_main``'s ``except`` reaps it a
    # second time. Both are documented as never raising, so the duplicate is
    # harmless — but tidying it up should have to change this line deliberately.
    assert (broken.terminated, broken.closed) == (2, 2)
    assert "overlay: supervisor_failed error_type=RuntimeError" in [
        record.getMessage() for record in caplog.records
    ]


def test_a_restarted_helper_is_replayed_the_current_state_not_the_history(
    host, supervisor, monkeypatch
) -> None:
    """A fresh helper has no useful history: it gets one atomic snapshot, so
    the pill it draws matches what the daemon is doing rather than replaying
    an edge the dead helper already consumed.

    The replacement is written its snapshot before the serve loop starts, so
    the records are on the wire whatever the replacement then does.
    """
    _short_ready_deadline(monkeypatch)
    install, helpers = host
    first, second = _SocketHelper(), _SocketHelper()
    helpers.extend((first, second))
    transport = _Transport([first, second])
    install(transport=transport)

    instance = supervisor()
    assert transport.attempted.acquire(timeout=_DEADLINE)
    first.reply(ReadyMessage(Backend.XWAYLAND))
    instance.loading_activity(True)
    instance.publish(OverlayState.TRANSCRIBING)

    delivered = first.records(2)
    assert isinstance(delivered[0], LoadingActivityMessage) and delivered[0].active is True
    assert isinstance(delivered[1], StateMessage)
    generation = delivered[1].generation

    first.send_raw(b"corrupt\n")
    assert transport.attempted.acquire(timeout=_DEADLINE)

    assert second.records(2) == [
        LoadingActivityMessage(True),
        StateMessage(generation, OverlayState.TRANSCRIBING),
    ]
    assert _finished(instance)


def test_a_backend_lost_after_readiness_is_worth_one_fresh_helper(host, supervisor, caplog) -> None:
    """``unavailable`` *after* ``ready`` is a display that went away, not one
    that was never there — so unlike an up-front refusal it earns a restart,
    and only the second failure ends the session.
    """
    install, helpers = host
    helper = _SocketHelper()
    helpers.append(helper)
    transport = _Transport([helper])
    install(transport=transport)

    with caplog.at_level(logging.WARNING, logger=_LOG):
        instance = supervisor()
        assert transport.attempted.acquire(timeout=_DEADLINE)
        helper.reply(ReadyMessage(Backend.LAYER_SHELL))
        helper.reply(UnavailableMessage(UnavailableReason.BACKEND_LOST))
        assert _finished(instance)

    assert transport.spawns == 2
    messages = [record.getMessage() for record in caplog.records]
    assert "overlay: backend_lost reason=backend_lost" in messages
    assert "overlay: helper_restarting" in messages
    assert helper.terminated == 1


def test_a_helper_that_dies_mid_record_is_reported_as_a_framing_failure(
    host, supervisor, caplog
) -> None:
    """A child killed between two writes leaves half a record in the pipe; the
    parent must notice at end of stream rather than wait for the rest forever.
    """
    install, helpers = host
    first, second = _SocketHelper(), _SocketHelper()
    helpers.extend((first, second))
    transport = _Transport([first, second])
    install(transport=transport)

    with caplog.at_level(logging.WARNING, logger=_LOG):
        instance = supervisor()
        assert transport.attempted.acquire(timeout=_DEADLINE)
        first.send_raw(b'{"v":4,"type":"rea')
        first.close_output()
        assert transport.attempted.acquire(timeout=_DEADLINE)
        second.close_output()
        assert _finished(instance)

    phases = [
        record.getMessage()
        for record in caplog.records
        if "helper_protocol_error" in record.getMessage()
    ]
    assert len(phases) == 1
    assert "phase=finish" in phases[0]
    assert transport.spawns == 2


def test_a_helper_whose_stdin_is_gone_is_replaced_rather_than_written_to(host, supervisor) -> None:
    """A write to a dead child raises; treating that as fatal for the session
    would lose the overlay on the one failure a restart actually fixes.
    """

    class _DeafHelper(_SocketHelper):
        def write(self, data: bytes) -> None:
            raise BrokenPipeError("the helper is gone")

    install, helpers = host
    first, second = _DeafHelper(), _DeafHelper()
    helpers.extend((first, second))
    transport = _Transport([first, second])
    install(transport=transport)

    instance = supervisor()
    assert transport.attempted.acquire(timeout=_DEADLINE)
    first.reply(ReadyMessage(Backend.XWAYLAND))
    instance.publish(OverlayState.TRANSCRIBING)

    assert transport.attempted.acquire(timeout=_DEADLINE)
    assert _finished(instance)
    assert transport.spawns == 2
    # The replacement failed on its replay snapshot, before serving anything.
    assert second.terminated == 1
