# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-utterance analytics operations without lifecycle or active-record ownership."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import log_failure
from stenographer.lib.transcribe.pipeline import analytics_metrics
from stenographer.lib.transcribe.utterance_record import UtteranceRecord

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from stenographer.lib.config.models import Config
    from stenographer.lib.diagnostics.collection import Collection
    from stenographer.lib.platform.platform import Platform

log = logging.getLogger("stenographer.lib.daemon")


class UtteranceTelemetry:
    """Own the diagnostics collection and project explicitly supplied records into it.

    The daemon decides when a record starts, reaches a checkpoint, and finishes.
    Collection failures remain isolated from dictation, and record timing stays
    with the caller.
    """

    def __init__(self) -> None:
        self._collection: Collection | None = None

    def open(
        self,
        cfg: Config,
        platform: Platform | None,
        *,
        pids: Callable[[], Sequence[int]],
    ) -> None:
        """Initialize diagnostics when the daemon starts its listener."""
        if platform is None:
            return
        try:
            from stenographer.lib.diagnostics.session import create_session

            self._collection = create_session(cfg, platform, pids=pids)
        except Exception as exc:
            log_failure(log, logging.WARNING, "analytics: unavailable", exc, safe=False)

    def start(self, record: UtteranceRecord) -> None:
        """Assign the collection's identity to a newly accepted record."""
        if self._collection is not None:
            try:
                record.analytics_id = self._collection.start(record.utt)
            except Exception as exc:
                log_failure(log, logging.DEBUG, "analytics: start_failed", exc, safe=False)

    def checkpoint(self, record: UtteranceRecord | None, phase: str) -> None:
        """Project measurements and capture context at an existing phase boundary."""
        if record is None or self._collection is None or record.analytics_id is None:
            return
        try:
            context = {}
            if phase == "secured_capture":
                context = {"sample_rate": record.input_rate, "channels": record.channels}
                name = record.device_name
                if name and not any(ord(char) < 32 for char in name):
                    context["device"] = name[:256]
            self._collection.checkpoint(
                record.analytics_id,
                phase,
                metrics=analytics_metrics(record),
                context=context,
            )
        except Exception as exc:
            log_failure(log, logging.DEBUG, "analytics: checkpoint_failed", exc, safe=False)

    def finish(self, record: UtteranceRecord) -> None:
        """Persist terminal measurements after the daemon stamps total duration."""
        if self._collection is not None and record.analytics_id is not None:
            try:
                self._collection.finish(
                    record.analytics_id,
                    record.failure or record.outcome.lower(),
                    metrics=analytics_metrics(record),
                )
            except Exception as exc:
                log_failure(log, logging.DEBUG, "analytics: finish_failed", exc, safe=False)

    def close(self) -> None:
        """Close the collection after terminal records have been emitted."""
        if self._collection is not None:
            self._collection.close()
            self._collection = None
