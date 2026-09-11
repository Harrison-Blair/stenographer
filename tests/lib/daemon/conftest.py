# SPDX-License-Identifier: GPL-3.0-or-later
"""Capture daemon logs without leaking global logging state between tests."""

from __future__ import annotations

import logging

import pytest

from stenographer.lib.logging.pipeline import set_utterance


@pytest.fixture
def daemon_logs(caplog):
    """Capture the daemon's own records regardless of what earlier tests left.

    ``setup_logging`` sets ``propagate = False`` on the package logger and
    ``shutdown_logging`` does not put it back, so caplog's root handler can
    otherwise see nothing at all — and a privacy assertion over an empty log
    passes for the wrong reason.
    """
    logger = logging.getLogger("stenographer")
    saved_propagate, saved_level = logger.propagate, logger.level
    saved_handlers = list(logger.handlers)
    logger.propagate = True
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    try:
        with caplog.at_level(logging.DEBUG, logger="stenographer"):
            yield caplog
    finally:
        logger.propagate, logger.level = saved_propagate, saved_level
        logger.handlers[:] = saved_handlers
        set_utterance(None)
