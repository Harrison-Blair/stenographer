# SPDX-License-Identifier: GPL-3.0-or-later
"""Privacy-safe process-wide logging for Stenographer.

The logger itself only enqueues: one :class:`~logging.handlers.QueueListener`
thread owns the stderr handler and the rotating file handler, so no daemon
thread ever blocks on a write or a rotation. The file sink is unconditionally
DEBUG — a report is worthless without the records that precede the failure —
and only the stderr/journal threshold is tunable. Spawned ASR workers forward
records over a multiprocessing queue and never open the log file.

Every message is rendered as ``subsystem: event key=value ...`` (:func:`fmt_event`),
carries the current utterance id when one is set (:func:`set_utterance`), and
reports exceptions through :func:`log_failure`, which decides per call site
whether the exception's own text may be rendered at all.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import queue
import sys
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from stenographer.platform import current_platform

if TYPE_CHECKING:
    from multiprocessing.queues import Queue

_LOGGER_NAME = "stenographer"
_LOG_FILENAME = "stenographer.log"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3
_HANDLER_MARKER = "_stenographer_owned"
_FILE_WARNING_MARKER = "_stenographer_file_warning_emitted"
_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s%(utt_suffix)s"
_JOURNAL_FORMAT = "%(levelname)s %(name)s %(message)s%(utt_suffix)s"
# Records that never passed the logger's filter (the ASR child's, logging's own)
# still format: the suffix is a rendered field, not a required attribute.
_FORMAT_DEFAULTS = {"utt_suffix": ""}

_listener: logging.handlers.QueueListener | None = None
#: STENOGRAPHER_LOG_LEVEL is per-process and outranks the config value.
_stderr_level_pinned = False
_utterance: int | None = None


def resolve_log_level(value: str | None) -> int:
    """Resolve a case-insensitive level name, defaulting invalid input to INFO."""
    if not value:
        return logging.INFO
    level = logging.getLevelNamesMapping().get(value.upper())
    return level if isinstance(level, int) else logging.INFO


def fmt_event(subsystem: str, event: str, **fields: object) -> str:
    """Render one ``subsystem: event key=value ...`` line. PURE.

    Fields keep call order — a log line is read by eye far more often than it
    is parsed — and a ``None`` field is omitted rather than rendered, so one
    template serves the paths where a measurement was never taken.
    """
    return _with_fields(f"{subsystem}: {event}", fields)


def stderr_format(*, journal_attached: bool) -> str:
    """The stderr format string: no ``asctime`` when the journal stamps it. PURE."""
    return _JOURNAL_FORMAT if journal_attached else _FORMAT


def set_utterance(number: int | None) -> None:
    """Stamp every later record with ``utt=<number>``; ``None`` clears it.

    A module-level value rather than a ``ContextVar``: one utterance runs at a
    time but its records come from several threads (hotkey, pipeline, overlay
    supervisor), and a per-context value would leave every thread but the
    setter's unstamped.
    """
    global _utterance
    _utterance = number


class UtteranceFilter(logging.Filter):
    """Attach the current utterance id to each record it passes."""

    def filter(self, record: logging.LogRecord) -> bool:
        number = _utterance
        record.utt = number
        record.utt_suffix = "" if number is None else f" utt={number}"
        return True


def log_failure(
    log: logging.Logger,
    level: int,
    event: str,
    exc: BaseException,
    *,
    safe: bool,
    **fields: object,
) -> None:
    """Log *exc* under the ``"subsystem: event"`` label *event*, tiered by audit.

    ``safe=True`` says this lineage's exception text is host vocabulary (a
    device path, an OS error, a protocol complaint): it is rendered at *level*
    and the whole traceback follows at DEBUG. ``safe=False`` says the lineage
    can carry transcript- or audio-derived text, so only the class name and the
    traceback frames are ever rendered — the message is never formatted, at any
    level, and no ``exc_info`` record follows that would print it.
    """
    kind = type(exc).__name__
    if safe:
        log.log(level, _with_fields(event, {**fields, "error": kind, "detail": str(exc)}))
        log.debug(_with_fields(event, {**fields, "error": kind}), exc_info=exc)
        return
    frames = " | ".join(" ".join(frame.split()) for frame in traceback.format_tb(exc.__traceback__))
    log.log(level, _with_fields(event, {**fields, "error": kind, "frames": frames or None}))


def setup_logging(
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    stderr: TextIO | None = None,
    stderr_level: str | None = None,
) -> logging.Logger:
    """Install the Stenographer-owned logging pipeline once.

    *stderr_level* is the configured threshold for the stderr/journal sink;
    ``STENOGRAPHER_LOG_LEVEL`` outranks it for the whole process. The CLI runs
    this before any config exists, so the daemon re-applies the configured
    value through :func:`apply_stderr_level`. Existing handlers, including
    handlers installed by an embedding host, are left untouched. File setup
    errors degrade to stderr and are reported once.
    """
    global _listener, _stderr_level_pinned
    resolved_env = os.environ if env is None else env
    resolved_home = Path.home() if home is None else home
    resolved_stderr = sys.stderr if stderr is None else stderr
    override = resolved_env.get("STENOGRAPHER_LOG_LEVEL")
    _stderr_level_pinned = bool(override)
    level = resolve_log_level(override or stderr_level)
    logger = logging.getLogger(_LOGGER_NAME)
    # The logger passes everything; the sinks decide. Anything it dropped here
    # would be missing from the always-DEBUG file too.
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    _install_utterance_filter(logger)

    if _listener is None:
        stream_handler = logging.StreamHandler(resolved_stderr)
        _mark_owned(stream_handler)
        stream_handler.setFormatter(
            logging.Formatter(
                stderr_format(journal_attached=current_platform().journal_attached(resolved_env)),
                defaults=_FORMAT_DEFAULTS,
            )
        )
        sinks: list[logging.Handler] = [stream_handler]
        file_handler = _build_file_handler(logger, resolved_env, resolved_home, stream_handler)
        if file_handler is not None:
            sinks.append(file_handler)
        log_queue: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
        queue_handler = logging.handlers.QueueHandler(log_queue)
        _mark_owned(queue_handler)
        logger.addHandler(queue_handler)
        _listener = logging.handlers.QueueListener(log_queue, *sinks, respect_handler_level=True)
        _listener.start()

    _set_stderr_level(level)
    return logger


def apply_stderr_level(level: str) -> None:
    """Re-apply the stderr threshold once ``feedback.log_level`` is known.

    A no-op when ``STENOGRAPHER_LOG_LEVEL`` is set: the per-process override
    was resolved before the config could be read and stays authoritative.
    """
    if _stderr_level_pinned:
        return
    _set_stderr_level(resolve_log_level(level))


def owned_handlers(logger: logging.Logger | None = None) -> tuple[logging.Handler, ...]:
    """Return the real sinks this module owns, never the queue forwarder.

    In the daemon they live on the listener thread, which is also where the ASR
    child's forwarded records must land — one queue hop, one write each.
    """
    target = logging.getLogger(_LOGGER_NAME) if logger is None else logger
    attached = tuple(
        handler
        for handler in target.handlers
        if getattr(handler, _HANDLER_MARKER, False)
        and not isinstance(handler, logging.handlers.QueueHandler)
    )
    listener = _listener
    return attached + (tuple(listener.handlers) if listener is not None else ())


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
    _install_utterance_filter(logger)
    logger.setLevel(level)
    logger.propagate = False


def shutdown_logging() -> None:
    """Stop the listener so the queued tail is written, then close owned sinks."""
    global _listener
    logger = logging.getLogger(_LOGGER_NAME)
    # Detach before stopping: nothing may enqueue behind the listener's sentinel.
    for handler in tuple(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()
    for log_filter in tuple(logger.filters):
        if getattr(log_filter, _HANDLER_MARKER, False):
            logger.removeFilter(log_filter)
    listener, _listener = _listener, None
    if listener is not None:
        listener.stop()
        for handler in listener.handlers:
            handler.close()
    if hasattr(logger, _FILE_WARNING_MARKER):
        delattr(logger, _FILE_WARNING_MARKER)


def _with_fields(head: str, fields: Mapping[str, object]) -> str:
    parts = [head]
    parts += [f"{key}={_render(value)}" for key, value in fields.items() if value is not None]
    return " ".join(parts)


def _render(value: object) -> str:
    # %g keeps a quiet mic's 0.0005 readable instead of rounding it to zero,
    # and drops the float noise a computed duration carries.
    return f"{value:g}" if isinstance(value, float) else str(value)


def _mark_owned(handler: logging.Handler | logging.Filter) -> None:
    setattr(handler, _HANDLER_MARKER, True)


def _install_utterance_filter(logger: logging.Logger) -> None:
    # On the logger, not the sinks: it must run in the thread that emitted the
    # record, before the queue hands it to another one.
    if any(getattr(existing, _HANDLER_MARKER, False) for existing in logger.filters):
        return
    log_filter = UtteranceFilter()
    _mark_owned(log_filter)
    logger.addFilter(log_filter)


def _set_stderr_level(level: int) -> None:
    for handler in owned_handlers():
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        ):
            handler.setLevel(level)


def _build_file_handler(
    logger: logging.Logger,
    env: Mapping[str, str],
    home: Path,
    stream_handler: logging.StreamHandler,
) -> logging.Handler | None:
    log_path: Path | None = None
    try:
        log_path = current_platform().state_dir(env, home) / _LOG_FILENAME
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
                stream_handler,
                fmt_event(
                    "logging",
                    "file_unavailable",
                    path=log_path,
                    error=type(exc).__name__,
                    errno=getattr(exc, "errno", None),
                    detail=getattr(exc, "strerror", None) or str(exc),
                    fallback="stderr",
                ),
            )
        return None
    _mark_owned(file_handler)
    # Unconditionally DEBUG: the file is the report, and a threshold applied
    # here cannot be lifted after the failure it was supposed to explain.
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FORMAT, defaults=_FORMAT_DEFAULTS))
    return file_handler


def _emit_file_warning(
    logger: logging.Logger,
    handler: logging.StreamHandler,
    message: str,
) -> None:
    """Emit the one setup warning even when the requested threshold is higher."""
    record = logger.makeRecord(
        logger.name,
        logging.WARNING,
        __file__,
        0,
        message,
        (),
        None,
    )
    # Calling the stderr handler directly bypasses logger/handler thresholds for
    # only this record — and it must go out before the queue pipeline exists.
    handler.handle(record)
