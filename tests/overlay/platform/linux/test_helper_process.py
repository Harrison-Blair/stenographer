# SPDX-License-Identifier: GPL-3.0-or-later
"""The Linux helper host, driven against real child processes and real pipes.

Everything below this line is host semantics — pipe creation, a blocking wait
for child output, POSIX signal escalation — and none of it survives being
mocked: a ``terminate`` that never sends a signal passes any stand-in and
leaves a wedged helper running forever on a real machine. So every test here
spawns a small ``sys.executable`` child and asserts on what actually happened
to it.

No overlay backend, display server, or protocol record is involved: the
children are two-line scripts that echo, ignore SIGTERM, or exit.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time

import pytest

from stenographer.overlay.platform.linux.linux_helper_process import LinuxHelperProcess
from stenographer.overlay.platform.linux.linux_helper_transport import LinuxHelperTransport

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux helper process and POSIX pipe semantics"
)

_ECHO = (
    "import sys\n"
    "for line in sys.stdin.buffer:\n"
    "    sys.stdout.buffer.write(line)\n"
    "    sys.stdout.buffer.flush()\n"
)

_IGNORES_SIGTERM = (
    "import signal, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "sys.stdout.buffer.write(b'up\\n')\n"
    "sys.stdout.buffer.flush()\n"
    "time.sleep(120)\n"
)

_NOISY_STDERR = "import sys\nsys.stderr.write('backend chatter\\n')\nsys.stderr.flush()\n"

# Generous: these bound a failure rather than pace a passing test, which
# finishes as soon as the child has actually answered.
_WAIT_SECONDS = 10.0

_GRACE_SECONDS = 0.1


@pytest.fixture
def spawn():
    """Start real children through the transport and reap every one of them."""
    started: list[LinuxHelperProcess] = []

    def start(script: str, **kwargs) -> LinuxHelperProcess:
        process = LinuxHelperTransport().spawn((sys.executable, "-c", script), **kwargs)
        started.append(process)
        return process

    try:
        yield start
    finally:
        for process in started:
            process.terminate(_GRACE_SECONDS)
            process.close()


def _read_line(process: LinuxHelperProcess) -> bytes:
    """Block until the child has written something, bounded by a real deadline."""
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        if process.wait_readable(0.05):
            return process.read(4096)
    raise AssertionError("the child produced no output before the deadline")


def test_a_spawned_child_round_trips_bytes_over_its_own_pipes(spawn) -> None:
    process = spawn(_ECHO)

    process.write(b"one record\n")

    assert _read_line(process) == b"one record\n"
    assert process.is_running() is True


def test_closing_stdin_is_what_lets_a_cooperative_child_exit(spawn) -> None:
    """The supervisor's expected-exit path writes shutdown and closes stdin; a
    child that never saw EOF would then be killed instead of leaving on its own.
    """
    process = spawn(_ECHO)
    process.write(b"ping\n")
    assert _read_line(process) == b"ping\n"

    process.close_input()
    process.wait(_WAIT_SECONDS)

    assert process.is_running() is False
    assert process.read(4096) == b""


def test_an_idle_child_makes_the_wait_time_out_rather_than_report_readable(spawn) -> None:
    process = spawn(_ECHO)

    assert process.wait_readable(0.05) is False


def test_a_child_that_ignores_sigterm_is_killed_within_the_grace_window() -> None:
    """Seen to matter on a wedged display connection: a helper blocked inside a
    display library never handles SIGTERM, and a ``terminate`` without the kill
    escalation would leave it alive for the rest of the session.
    """
    popen = subprocess.Popen(
        (sys.executable, "-c", _IGNORES_SIGTERM),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    process = LinuxHelperProcess(popen)
    try:
        assert _read_line(process) == b"up\n"

        started = time.monotonic()
        process.terminate(_GRACE_SECONDS)
        elapsed = time.monotonic() - started

        assert process.is_running() is False
        assert popen.returncode == -signal.SIGKILL
        # The child asked to sleep for two minutes: only the kill explains this.
        assert elapsed < _WAIT_SECONDS
    finally:
        popen.kill()
        popen.wait(timeout=_WAIT_SECONDS)
        process.close()


def test_terminating_an_already_exited_child_only_reaps_it(spawn) -> None:
    process = spawn(_NOISY_STDERR)
    deadline = time.monotonic() + _WAIT_SECONDS
    while process.is_running() and time.monotonic() < deadline:
        process.wait(0.05)
    assert process.is_running() is False

    process.terminate(_GRACE_SECONDS)
    process.terminate(_GRACE_SECONDS)

    assert process.is_running() is False


def test_closing_an_exited_child_is_idempotent_and_never_raises(spawn) -> None:
    process = spawn(_ECHO)
    process.close_input()
    process.wait(_WAIT_SECONDS)

    process.close()
    process.close()

    # Every read after close is EOF, not an exception the supervisor must catch.
    assert process.read(4096) == b""


def test_a_command_that_cannot_start_raises_instead_of_returning_a_dead_handle(
    tmp_path,
) -> None:
    transport = LinuxHelperTransport()

    with pytest.raises(OSError):
        transport.spawn((str(tmp_path / "no-such-helper"),))


def test_child_stderr_is_appended_to_the_caller_s_file_not_a_pipe(tmp_path, spawn) -> None:
    """Nobody drains the helper's stderr, so a chatty backend library on a pipe
    would eventually block the child. It goes to the shared log file instead.
    """
    stderr_path = tmp_path / "overlay-helper.log"
    stderr_path.write_bytes(b"earlier record\n")

    process = spawn(_NOISY_STDERR, stderr_path=stderr_path)
    process.wait(_WAIT_SECONDS)

    assert stderr_path.read_bytes() == b"earlier record\nbackend chatter\n"


def test_an_unwritable_stderr_path_still_starts_the_helper(tmp_path, spawn) -> None:
    """Losing the diagnostics is the lesser failure: no overlay at all is worse."""
    process = spawn(_ECHO, stderr_path=tmp_path / "missing-directory" / "helper.log")

    process.write(b"still alive\n")

    assert _read_line(process) == b"still alive\n"


def test_two_concurrent_helpers_never_share_a_stdout_descriptor(spawn) -> None:
    """A restart overlaps the old and new child briefly; crossed pipes would
    hand the supervisor the dead helper's records as the new one's.
    """
    first = spawn(_ECHO)
    second = spawn(_ECHO)

    second.write(b"second\n")

    assert _read_line(second) == b"second\n"
    assert first.wait_readable(0.05) is False
