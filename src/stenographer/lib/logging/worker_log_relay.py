# SPDX-License-Identifier: GPL-3.0-or-later
"""Forward child log records to the parent's prepared-record receiver."""

import logging
import logging.handlers
from collections.abc import Callable


class WorkerLogRelay(logging.handlers.QueueListener):
    def __init__(self, log_queue, *, on_log: Callable[[logging.LogRecord], None]):
        super().__init__(log_queue)
        self._on_log = on_log

    def handle(self, record: logging.LogRecord) -> None:
        self._on_log(record)
