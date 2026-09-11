# SPDX-License-Identifier: GPL-3.0-or-later
"""The isolated overlay helper's file logging pipeline."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from stenographer.lib.logging.pipeline import (
    _FORMAT,
    _FORMAT_DEFAULTS,
    _LOGGER_NAME,
    _emit_file_warning,
    _mark_owned,
    fmt_event,
    resolve_log_level,
)
from stenographer.lib.logging.utterance_filter import UtteranceFilter
from stenographer.lib.platform import current_platform

_HELPER_MAX_BYTES = 1024 * 1024


def helper_log_path(env: Mapping[str, str], home: Path) -> Path:
    """State-dir path of the overlay helper's own log file."""
    return current_platform().state_dir(env, home) / "overlay-helper.log"


def cap_helper_log(path: Path) -> None:
    """Roll *path* aside once when it has grown past the helper's 1 MiB budget.

    The helper log has two writers — this process's handler and the inherited
    stderr descriptor the transport points at the same file — so it cannot use
    a :class:`~logging.handlers.RotatingFileHandler`: rotating mid-run would
    leave the other writer appending to an unlinked inode. Checking the size
    once, before either descriptor is opened, keeps ``overlay-helper.log`` plus
    one ``.1`` backup with no rotation while the file is open. Never raises:
    an uncapped log beats a helper that will not start.

    This is a start-time budget, not a live size cap. A dying display can log
    many ``display_lost`` records inside one session, and the file will exceed
    the budget until the next start — the supervisor's restart budget, not this
    function, is what stops that session from running forever.
    """
    try:
        if path.stat().st_size < _HELPER_MAX_BYTES:
            return
        path.replace(path.with_name(path.name + ".1"))
    except OSError:
        return


def _stderr_targets(path: Path, stream: TextIO) -> bool:
    """Does *stream* already point at *path*'s current inode?

    True in the spawned helper, whose stderr the transport opened on this very
    file before the child existed. Capping then would rename the inode out from
    under that descriptor, and every later byte of backend chatter would land
    in a ``.1`` the next start overwrites. Identity, not path equality: only
    ``fstat`` can see through an inherited descriptor.
    """
    try:
        here, there = os.fstat(stream.fileno()), path.stat()
    except (OSError, ValueError, AttributeError):
        return False
    return (here.st_dev, here.st_ino) == (there.st_dev, there.st_ino)


def setup_helper_logging(
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    stderr: TextIO | None = None,
) -> logging.Logger:
    """Install the overlay helper's own DEBUG log file in the state directory.

    The helper is a single-threaded child with one short pipe to serve, so it
    needs no queue and no listener thread — one plain append-mode
    :class:`~logging.FileHandler` on ``overlay-helper.log`` is the whole
    pipeline. It never opens ``stenographer.log``: the daemon owns that file,
    and a second unsynchronised writer would interleave with its rotation.

    *stderr* is the fallback sink, installed only when the file cannot be
    opened. With the file live it would be a duplicate rather than a second
    audience: the transport already points the helper's stderr at that same
    file so a backend library's own chatter lands beside these records.

    Nothing here raises. A helper that cannot open its log must still serve the
    protocol; losing the diagnostics is the lesser failure.
    """
    resolved_env = os.environ if env is None else env
    resolved_home = Path.home() if home is None else home
    resolved_stderr = sys.stderr if stderr is None else stderr
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    log_path: Path | None = None
    try:
        log_path = helper_log_path(resolved_env, resolved_home)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not _stderr_targets(log_path, resolved_stderr):
            cap_helper_log(log_path)
        file_handler: logging.Handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    except Exception as exc:
        stream_handler = logging.StreamHandler(resolved_stderr)
        _mark_owned(stream_handler)
        stream_handler.setLevel(resolve_log_level(resolved_env.get("STENOGRAPHER_LOG_LEVEL")))
        stream_handler.setFormatter(logging.Formatter(_FORMAT, defaults=_FORMAT_DEFAULTS))
        logger.addHandler(stream_handler)
        _emit_file_warning(
            logger,
            stream_handler,
            fmt_event(
                "logging",
                "helper_file_unavailable",
                path=log_path,
                error=type(exc).__name__,
                errno=getattr(exc, "errno", None),
                detail=getattr(exc, "strerror", None) or str(exc),
                fallback="stderr",
            ),
        )
        return logger
    _mark_owned(file_handler)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FORMAT, defaults=_FORMAT_DEFAULTS))
    file_handler.addFilter(UtteranceFilter())
    logger.addHandler(file_handler)
    return logger
