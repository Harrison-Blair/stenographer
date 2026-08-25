# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for the log format, the tiering, and the flush; opt-in checks below."""

from __future__ import annotations

import logging
import logging.handlers
import os
from io import StringIO

import pytest

from stenographer.utils.logging_setup import (
    UtteranceFilter,
    fmt_event,
    log_failure,
    owned_handlers,
    resolve_log_level,
    set_utterance,
    setup_logging,
    shutdown_logging,
    stderr_format,
)

CANARY = "canary-" + "the quick brown fox"


@pytest.fixture
def captured():
    """A private logger writing the production format into a string."""

    logger = logging.getLogger("stenographer.tests.capture")
    logger.handlers.clear()
    logger.filters.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        logging.Formatter("%(levelname)s %(message)s%(utt_suffix)s", defaults={"utt_suffix": ""})
    )
    logger.addHandler(handler)
    yield logger, stream
    logger.handlers.clear()
    logger.filters.clear()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, logging.INFO),
        ("", logging.INFO),
        ("debug", logging.DEBUG),
        ("WaRnInG", logging.WARNING),
        ("not-a-level", logging.INFO),
    ],
)
def test_resolve_log_level(value, expected):
    assert resolve_log_level(value) == expected


def _require_integration() -> None:
    if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
        pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1")


@pytest.mark.integration
def test_setup_is_idempotent_and_preserves_host_handler(tmp_path):
    _require_integration()
    shutdown_logging()
    logger = logging.getLogger("stenographer")
    host_handler = logging.NullHandler()
    logger.addHandler(host_handler)
    stderr = StringIO()
    try:
        setup_logging(env={"XDG_STATE_HOME": str(tmp_path)}, home=tmp_path, stderr=stderr)
        first = owned_handlers()
        setup_logging(env={"XDG_STATE_HOME": str(tmp_path)}, home=tmp_path, stderr=stderr)

        assert logger.handlers.count(host_handler) == 1
        assert owned_handlers() == first
        assert len(first) == 2
        logger.info("logging smoke metric=%d", 1)
        assert "logging smoke metric=1" in stderr.getvalue()
        assert "logging smoke metric=1" in (tmp_path / "stenographer/stenographer.log").read_text()
    finally:
        shutdown_logging()
        logger.removeHandler(host_handler)


@pytest.mark.integration
def test_file_handler_rotates_at_configured_limit(tmp_path):
    _require_integration()
    shutdown_logging()
    try:
        logger = setup_logging(
            env={"XDG_STATE_HOME": str(tmp_path), "STENOGRAPHER_LOG_LEVEL": "info"},
            home=tmp_path,
            stderr=StringIO(),
        )
        file_handler = next(
            handler
            for handler in owned_handlers()
            if isinstance(handler, logging.handlers.RotatingFileHandler)
        )
        assert file_handler.maxBytes == 5 * 1024 * 1024
        assert file_handler.backupCount == 3

        # Exercise the real handler with a lower threshold after verifying the
        # production threshold; keep the emitted smoke records metrics-only.
        file_handler.maxBytes = 200
        for index in range(20):
            logger.info("rotation metric=%d", index)
        file_handler.flush()

        assert (tmp_path / "stenographer/stenographer.log.1").is_file()
    finally:
        shutdown_logging()


@pytest.mark.integration
def test_file_failure_falls_back_to_stderr_and_warns_once(tmp_path):
    _require_integration()
    shutdown_logging()
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupied", encoding="utf-8")
    stderr = StringIO()
    try:
        env = {
            "XDG_STATE_HOME": str(blocked),
            "STENOGRAPHER_LOG_LEVEL": "critical",
        }
        setup_logging(env=env, home=tmp_path, stderr=stderr)
        setup_logging(env=env, home=tmp_path, stderr=stderr)

        assert len(owned_handlers()) == 1
        records = stderr.getvalue()
        assert records.count("logging: file_unavailable") == 1
        assert " WARNING stenographer logging: file_unavailable path=" in records
        logging.getLogger("stenographer").error("ordinary suppressed metric=%d", 1)
        assert "ordinary suppressed" not in stderr.getvalue()
    finally:
        shutdown_logging()


@pytest.mark.integration
def test_invalid_file_path_value_falls_back_safely(tmp_path):
    _require_integration()
    shutdown_logging()
    stderr = StringIO()
    try:
        env = {"XDG_STATE_HOME": f"{tmp_path}/bad\0path"}
        setup_logging(env=env, home=tmp_path, stderr=stderr)
        setup_logging(env=env, home=tmp_path, stderr=stderr)

        records = stderr.getvalue()
        assert records.count("logging: file_unavailable") == 1
        assert "error=ValueError" in records
        assert len(owned_handlers()) == 1
    finally:
        shutdown_logging()


def test_fmt_event_renders_fields_in_call_order_and_omits_missing_ones():
    assert fmt_event("recorder", "captured") == "recorder: captured"
    assert (
        fmt_event("recorder", "captured", frames=1200, rate_hz=16000, overflow=0)
        == "recorder: captured frames=1200 rate_hz=16000 overflow=0"
    )
    # A measurement that was never taken is absent, not "None".
    assert fmt_event("pipeline", "done", outcome="SILENT", decode_ms=None) == (
        "pipeline: done outcome=SILENT"
    )
    # A quiet mic's floor must survive rendering, and computed float noise must not.
    assert fmt_event("audio", "gate", threshold=0.0005, peak=0.1 + 0.2) == (
        "audio: gate threshold=0.0005 peak=0.3"
    )


def test_utterance_filter_stamps_the_current_id_and_clears_it(captured):
    logger, stream = captured
    logger.addFilter(UtteranceFilter())
    try:
        set_utterance(7)
        logger.info(fmt_event("pipeline", "started"))
        set_utterance(None)
        logger.info(fmt_event("pipeline", "idle"))
    finally:
        set_utterance(None)

    assert "INFO pipeline: started utt=7" in stream.getvalue()
    assert "INFO pipeline: idle\n" in stream.getvalue()


def test_log_failure_unsafe_never_renders_the_exception_message(captured):
    """The ASR child's inferred errors can quote the transcript back at us.

    Seen to FAIL against the same call with ``safe=True`` (the canary appeared
    in the WARNING line and again in the DEBUG traceback).
    """

    logger, stream = captured
    try:
        raise RuntimeError(CANARY)
    except RuntimeError as exc:
        log_failure(logger, logging.WARNING, "asr: job_failed", exc, safe=False, phase="decode")

    records = stream.getvalue()
    assert CANARY not in records
    assert "WARNING asr: job_failed phase=decode error=RuntimeError frames=" in records
    assert "test_logging_setup.py" in records


def test_log_failure_safe_renders_the_message_and_a_debug_traceback(captured):
    logger, stream = captured
    try:
        raise FileNotFoundError(2, "No such file or directory")
    except FileNotFoundError as exc:
        log_failure(logger, logging.WARNING, "notify: send_failed", exc, safe=True, tool="notify")

    records = stream.getvalue()
    assert "WARNING notify: send_failed tool=notify error=FileNotFoundError detail=" in records
    assert "No such file or directory" in records
    assert "DEBUG notify: send_failed tool=notify error=FileNotFoundError" in records
    assert "Traceback (most recent call last)" in records


def test_stderr_format_omits_asctime_only_when_the_journal_stamps_it():
    assert "%(asctime)s" in stderr_format(journal_attached=False)
    assert "%(asctime)s" not in stderr_format(journal_attached=True)
    assert "%(message)s" in stderr_format(journal_attached=True)


def test_queued_records_are_flushed_in_order_by_shutdown(tmp_path):
    """The listener owns the sinks, so the tail exists only until it is stopped.

    Seen to FAIL against a ``shutdown_logging`` that closed the handlers without
    stopping the listener (the last records never reached the stream).
    """

    shutdown_logging()
    stream = StringIO()
    logger = setup_logging(env={"XDG_STATE_HOME": str(tmp_path)}, home=tmp_path, stderr=stream)
    for index in range(500):
        logger.info(fmt_event("bench", "record", index=index))
    shutdown_logging()

    written = [line for line in stream.getvalue().splitlines() if "bench: record" in line]
    assert [line.rsplit("index=", 1)[1] for line in written] == [str(i) for i in range(500)]


def test_unopenable_log_file_is_reported_with_its_path_and_errno(tmp_path):
    """A class name alone cannot be acted on; the path and the errno can.

    Seen to FAIL against the class-name-only warning (no path, no errno).
    """

    blocked = tmp_path / "occupied"
    blocked.write_text("not a directory", encoding="utf-8")
    shutdown_logging()
    stream = StringIO()
    try:
        setup_logging(env={"XDG_STATE_HOME": str(blocked)}, home=tmp_path, stderr=stream)
    finally:
        shutdown_logging()

    records = stream.getvalue()
    assert "logging: file_unavailable" in records
    assert f"path={blocked}" in records
    assert "error=NotADirectoryError" in records
    assert "errno=20" in records
    assert "fallback=stderr" in records
