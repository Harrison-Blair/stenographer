# SPDX-License-Identifier: GPL-3.0-or-later
"""Daemon-side transport for the isolated overlay helper process (POSIX half).

The supervisor keeps every policy — mailbox, backend selection, NDJSON
framing, readiness deadline, failure-disable. What lives here is the part that
does not survive a move to another OS: the ``Popen`` pipe layout, ``select``
over the helper's stdout followed by ``os.read`` on its raw fd (Windows'
``SelectSelector`` accepts only sockets), and the SIGTERM → grace → SIGKILL
escalation (``terminate()`` on Windows is already a kill, which would make the
grace period dead time).
"""

from __future__ import annotations

import contextlib
import os
import selectors
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_SPAWN_CLEANUP_SECONDS = 0.75


class LinuxHelperProcess:
    """One spawned helper child, its two pipes, and the stdout read selector."""

    __slots__ = ("_fd", "_process", "_selector")

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        assert process.stdin is not None
        assert process.stdout is not None
        self._process = process
        self._fd = process.stdout.fileno()
        self._selector = selectors.DefaultSelector()
        try:
            self._selector.register(process.stdout, selectors.EVENT_READ)
        except BaseException:
            with contextlib.suppress(OSError):
                self._selector.close()
            raise

    def write(self, data: bytes) -> None:
        stdin = self._process.stdin
        assert stdin is not None
        stdin.write(data)
        stdin.flush()

    def close_input(self) -> None:
        stdin = self._process.stdin
        if stdin is not None:
            with contextlib.suppress(OSError):
                stdin.close()

    def wait_readable(self, timeout: float) -> bool:
        return bool(self._selector.select(timeout))

    def read(self, size: int) -> bytes:
        try:
            return os.read(self._fd, size)
        except OSError:
            return b""

    def is_running(self) -> bool:
        return self._process.poll() is None

    def wait(self, timeout: float) -> None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            self._process.wait(timeout=timeout)

    def terminate(self, grace_seconds: float) -> None:
        process = self._process
        if process.poll() is not None:
            with contextlib.suppress(OSError):
                process.wait(timeout=0)
            return
        with contextlib.suppress(OSError):
            process.terminate()
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=grace_seconds)

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._selector.close()
        self.close_input()
        stdout = self._process.stdout
        if stdout is not None:
            with contextlib.suppress(OSError):
                stdout.close()


class LinuxHelperTransport:
    """Spawns the helper with piped stdin/stdout, a discarded stderr, and no buffering.

    stderr goes to ``DEVNULL`` so a backend's library chatter can never fill a
    pipe nobody drains, and ``bufsize=0`` keeps every protocol record on the
    wire as soon as it is written. Linux needs no extra ``Popen`` flags (a
    Windows transport will want ``CREATE_NO_WINDOW``).
    """

    def spawn(self, command: Sequence[str]) -> LinuxHelperProcess:
        process = subprocess.Popen(
            tuple(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        try:
            return LinuxHelperProcess(process)
        except BaseException:
            # A child that outlives a failed handoff would never be reaped,
            # and its pipes must not linger while fds are scarce.
            with contextlib.suppress(OSError):
                process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=_SPAWN_CLEANUP_SECONDS)
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    with contextlib.suppress(OSError):
                        pipe.close()
            raise
