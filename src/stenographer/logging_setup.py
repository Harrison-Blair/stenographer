# SPDX-License-Identifier: GPL-3.0-or-later
"""Privacy-safe process-wide logging for Stenographer.

The parent process owns stderr and rotating-file handlers. Spawned ASR workers
forward records over a multiprocessing queue and never open the log file.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from multiprocessing.queues import Queue

_LOGGER_NAME = "stenographer"
_LOG_FILENAME = "stenographer.log"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3
_HANDLER_MARKER = "_stenographer_owned"
_FILE_WARNING_MARKER = "_stenographer_file_warning_emitted"
_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def resolve_log_level(value: str | None) -> int:
    """Resolve a case-insensitive level name, defaulting invalid input to INFO."""
    if not value:
        return logging.INFO
    level = logging.getLevelNamesMapping().get(value.upper())
    return level if isinstance(level, int) else logging.INFO


def resolve_state_dir(env: Mapping[str, str], home: Path) -> Path:
    """Resolve the application state directory using XDG precedence."""
    root = Path(env["XDG_STATE_HOME"]) if env.get("XDG_STATE_HOME") else home / ".local/state"
    return root / _LOGGER_NAME


def setup_logging(
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    stderr: TextIO | None = None,
) -> logging.Logger:
    """Install Stenographer-owned stderr and rotating-file handlers once.

    Existing handlers, including handlers installed by an embedding host, are
    left untouched. File setup errors degrade to stderr and are reported once.
    """
    resolved_env = os.environ if env is None else env
    resolved_home = Path.home() if home is None else home
    resolved_stderr = sys.stderr if stderr is None else stderr
    level = resolve_log_level(resolved_env.get("STENOGRAPHER_LOG_LEVEL"))
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    formatter = logging.Formatter(_FORMAT)

    owned = owned_handlers(logger)
    if _owned_stderr_handler(logger) is None:
        stream_handler = logging.StreamHandler(resolved_stderr)
        _mark_owned(stream_handler)
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    for handler in owned_handlers(logger):
        handler.setLevel(level)

    if not any(isinstance(handler, logging.handlers.RotatingFileHandler) for handler in owned):
        try:
            log_path = resolve_state_dir(resolved_env, resolved_home) / _LOG_FILENAME
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
        except (OSError, ValueError) as exc:
            if not getattr(logger, _FILE_WARNING_MARKER, False):
                setattr(logger, _FILE_WARNING_MARKER, True)
                _emit_file_warning(
                    logger,
                    "logging: file unavailable; continuing with stderr only: %s",
                    (type(exc).__name__,),
                )
        else:
            _mark_owned(file_handler)
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    return logger


def owned_handlers(logger: logging.Logger | None = None) -> tuple[logging.Handler, ...]:
    """Return only handlers installed by this module."""
    target = logging.getLogger(_LOGGER_NAME) if logger is None else logger
    return tuple(handler for handler in target.handlers if getattr(handler, _HANDLER_MARKER, False))


def configure_worker_logging(log_queue: Queue, level: int) -> None:
    """Replace child-side Stenographer handlers with a queue forwarder."""
    logger = logging.getLogger(_LOGGER_NAME)
    # The child is a fresh spawn. Remove every child-local handler so even an
    # embedding host cannot make it open or rotate a second copy of the file;
    # the corresponding parent handlers receive these records via the queue.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    queue_handler = logging.handlers.QueueHandler(log_queue)
    _mark_owned(queue_handler)
    logger.addHandler(queue_handler)
    logger.setLevel(level)
    logger.propagate = False


def shutdown_logging() -> None:
    """Close only Stenographer-owned handlers; primarily useful to test setup."""
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in owned_handlers(logger):
        logger.removeHandler(handler)
        handler.close()
    if hasattr(logger, _FILE_WARNING_MARKER):
        delattr(logger, _FILE_WARNING_MARKER)


def _mark_owned(handler: logging.Handler) -> None:
    setattr(handler, _HANDLER_MARKER, True)


def _owned_stderr_handler(logger: logging.Logger) -> logging.StreamHandler | None:
    for handler in owned_handlers(logger):
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        ):
            return handler
    return None


def _emit_file_warning(logger: logging.Logger, message: str, args: tuple[object, ...]) -> None:
    """Emit the one setup warning even when the requested threshold is higher."""
    handler = _owned_stderr_handler(logger)
    if handler is None:
        return
    record = logger.makeRecord(
        logger.name,
        logging.WARNING,
        __file__,
        0,
        message,
        args,
        None,
    )
    # Calling this owned handler directly bypasses logger/handler thresholds for
    # only this record. Filters and the normal formatter still apply.
    handler.handle(record)
