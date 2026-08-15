# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure resolver tests and opt-in integration checks for logging setup."""

from __future__ import annotations

import logging
import logging.handlers
import os
from io import StringIO
from pathlib import Path

import pytest

from stenographer.logging_setup import (
    owned_handlers,
    resolve_log_level,
    resolve_state_dir,
    setup_logging,
    shutdown_logging,
)


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


def test_resolve_state_dir_prefers_xdg_state_home():
    assert resolve_state_dir({"XDG_STATE_HOME": "/state"}, Path("/home/alice")) == Path(
        "/state/stenographer"
    )


def test_resolve_state_dir_falls_back_below_home():
    assert resolve_state_dir({}, Path("/home/alice")) == Path(
        "/home/alice/.local/state/stenographer"
    )


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
        assert records.count("file unavailable; continuing with stderr only") == 1
        assert " WARNING stenographer logging: file unavailable" in records
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
        assert records.count("file unavailable; continuing with stderr only") == 1
        assert "ValueError" in records
        assert len(owned_handlers()) == 1
    finally:
        shutdown_logging()
