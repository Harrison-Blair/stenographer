# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import contextlib
import os
import selectors
import subprocess


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
