# SPDX-License-Identifier: GPL-3.0-or-later
"""Stamp log records at emission time."""

import logging

from stenographer.lib.logging import pipeline


class UtteranceFilter(logging.Filter):
    """Stamp the current utterance id on each record it passes.

    It belongs on the queue handler, not on the ``stenographer`` logger: every
    module logs through ``getLogger(__name__)``, and a logger's own filters run
    only for records emitted on that exact logger. Handler filters run in
    ``Handler.handle`` — in the thread that emitted the record, before the
    queue hands it to the listener.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        number = pipeline._utterance
        record.utt_suffix = "" if number is None else f" utt={number}"
        return True
