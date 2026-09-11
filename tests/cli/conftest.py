# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep the application logger's state inside the test that changed it.

``setup_logging`` puts the ``stenographer`` logger at DEBUG with
``propagate = False`` and its own queue handler attached; ``shutdown_logging``
detaches the handlers it owns but restores neither the level nor the
propagation flag. A CLI test that opens the real pipeline therefore leaves
every later ``caplog`` assertion — in any directory — seeing DEBUG records
from a logger that no longer reaches the root handlers. Snapshotting the three
attributes here bounds that to the test that caused it.
"""

from __future__ import annotations

import logging

import pytest

_LOGGER_NAME = "stenographer"


@pytest.fixture(autouse=True)
def _isolate_application_logging():
    logger = logging.getLogger(_LOGGER_NAME)
    level, propagate, handlers = logger.level, logger.propagate, list(logger.handlers)
    try:
        yield
    finally:
        logger.setLevel(level)
        logger.propagate = propagate
        if logger.handlers != handlers:
            logger.handlers[:] = handlers
