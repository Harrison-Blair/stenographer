# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import contextlib
import logging
import subprocess
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

from stenographer.lib.logging.pipeline import fmt_event
from stenographer.overlay.platform.linux.linux_helper_process import LinuxHelperProcess

log = logging.getLogger(__name__)

_SPAWN_CLEANUP_SECONDS = 0.75


class LinuxHelperTransport:
    """Spawns the helper with piped stdin/stdout, a captured stderr, and no buffering.

    stderr is never a pipe — nobody drains it, and a chatty backend library
    would eventually block the child — so it is either the caller's file, opened
    append-only so it can share the helper's own log with the child's handler,
    or ``DEVNULL``. ``bufsize=0`` keeps every protocol record on the wire as
    soon as it is written. Linux needs no extra ``Popen`` flags.
    """

    def spawn(
        self, command: Sequence[str], *, stderr_path: Path | None = None
    ) -> LinuxHelperProcess:
        stderr: IO[bytes] | int = subprocess.DEVNULL
        if stderr_path is not None:
            try:
                stderr = open(stderr_path, "ab", buffering=0)  # noqa: SIM115
            except OSError as exc:
                log.warning(
                    fmt_event(
                        "overlay",
                        "helper_stderr_unavailable",
                        path=stderr_path,
                        error=type(exc).__name__,
                    )
                )
        try:
            process = subprocess.Popen(
                tuple(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                bufsize=0,
            )
        finally:
            # The child holds its own duplicate of the descriptor from here on.
            if not isinstance(stderr, int):
                with contextlib.suppress(OSError):
                    stderr.close()
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
