# SPDX-License-Identifier: GPL-3.0-or-later
"""Utterance processing from secured samples through final delivery."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.audio.gate import speech_gate_stats
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.daemon.outcome import Outcome
from stenographer.lib.daemon.policy import classify_pipeline
from stenographer.lib.logging.pipeline import log_failure
from stenographer.lib.refine.null_refiner import NullRefiner
from stenographer.lib.transcribe.errors import WorkerError, WorkerPathologicalError
from stenographer.lib.transcribe.pipeline import (
    apply_delivery,
    apply_formatting,
    apply_gate,
    apply_recognition,
    apply_refinement,
    apply_worker_timings,
    log_gate,
    transcript_text,
)
from stenographer.lib.transcribe.worker_policy import classify_worker_failure

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

    from stenographer.lib.daemon.telemetry import UtteranceTelemetry
    from stenographer.lib.delivery.deliverer import Deliverer
    from stenographer.lib.refine.text_refiner import TextRefiner
    from stenographer.lib.transcribe.results import TranscriptionResult
    from stenographer.lib.transcribe.utterance_record import UtteranceRecord
    from stenographer.lib.transcribe.worker import Worker

log = logging.getLogger("stenographer.lib.daemon")


class UtterancePipeline:
    """Process one explicit utterance without owning its lifecycle or threads.

    The daemon retains the active record and finalizes it under its state lock.
    This collaborator only fills processing measurements and returns an outcome;
    it never retains samples, transcript text, or a record between runs.
    """

    def __init__(
        self,
        *,
        min_speech_rms: float,
        worker: Worker,
        deliverer: Deliverer,
        refiner: TextRefiner | None = None,
        telemetry: UtteranceTelemetry,
        publish_state: Callable[[OverlayState], None],
        fail: Callable[[str], None],
        play_cue: Callable[[str], None],
        cancelled: Callable[[], bool],
        cancel_state: Callable[[], OverlayState],
    ) -> None:
        self._min_speech_rms = min_speech_rms
        self._worker = worker
        self._deliverer = deliverer
        self._refiner = refiner if refiner is not None else NullRefiner()
        self._telemetry = telemetry
        self._publish_state = publish_state
        self._fail = fail
        self._play_cue = play_cue
        self._cancelled = cancelled
        self._cancel_state = cancel_state

    def run(self, samples: np.ndarray, *, utterance: int, record: UtteranceRecord | None) -> str:
        """Run the ordered stages and report the existing terminal outcome name."""
        outcome_name = Outcome.ERROR.name
        try:
            if self._cancelled():
                outcome_name = "CANCELLED"
                self._publish_state(self._cancel_state())
                return outcome_name
            if not self._gate(samples, record):
                outcome_name = Outcome.SILENT.name
                self._publish_state(OverlayState.HIDDEN)
                return outcome_name
            if record is not None:
                record.cold = not self._worker.is_model_ready
            try:
                result = self._worker.transcribe(samples, utterance)
            except WorkerError as exc:
                self._apply_worker_timings(record)
                if self._cancelled():
                    outcome_name = "CANCELLED"
                    self._publish_state(self._cancel_state())
                    return outcome_name
                # Pathological rejections contain audited counts only. Other
                # worker errors may carry decoder output and must stay private.
                log_failure(
                    log,
                    logging.WARNING,
                    "pipeline: transcription_failed",
                    exc,
                    safe=isinstance(exc, WorkerPathologicalError),
                )
                if record is not None:
                    record.failure = classify_worker_failure(exc)
                self._fail("transcription failed")
                return outcome_name
            self._apply_worker_timings(record)
            apply_recognition(record, result)
            self._telemetry.checkpoint(record, "accepted_recognition")
            if self._cancelled():
                outcome_name = "CANCELLED"
                self._publish_state(self._cancel_state())
                return outcome_name
            text, transcript_nonempty = self._format(result, record)
            if transcript_nonempty:
                text = self._refine(text, record)
                if self._cancelled():
                    outcome_name = "CANCELLED"
                    self._publish_state(self._cancel_state())
                    return outcome_name
                self._publish_state(OverlayState.DELIVERING)
            try:
                deliver_result = (
                    self._deliverer.deliver(
                        text,
                        on_copied=lambda: self._clipboard_checkpoint(record),
                        cancelled=self._cancelled,
                    )
                    if transcript_nonempty
                    else None
                )
            except Exception as exc:
                self._apply_delivery(record, attempted=transcript_nonempty)
                if self._cancelled():
                    outcome_name = "CANCELLED"
                    self._publish_state(self._cancel_state())
                    return outcome_name
                log_failure(log, logging.WARNING, "pipeline: delivery_failed", exc, safe=False)
                if record is not None:
                    record.failure = (
                        "chord_failed" if record.copied_words is not None else "copy_failed"
                    )
                self._fail("delivery failed")
                return outcome_name
            self._apply_delivery(record, attempted=transcript_nonempty)
            outcome, message = classify_pipeline(
                gate_passed=True,
                transcript_nonempty=transcript_nonempty,
                deliver_result=deliver_result,
            )
            outcome_name = outcome.name
            if self._cancelled() and not deliver_result:
                outcome_name = "CANCELLED"
                if record is not None:
                    record.failure = None
                self._publish_state(self._cancel_state())
                return outcome_name
            elif outcome is Outcome.ERROR and record is not None:
                record.failure = "copy_failed"
            if outcome is Outcome.DELIVERED:
                self._publish_state(OverlayState.HIDDEN)
                self._play_cue("delivered")
            elif outcome is Outcome.ERROR:
                self._fail(message or "delivery failed")
        except Exception as exc:
            if record is not None:
                record.failure = "error"
            log_failure(log, logging.WARNING, "pipeline: failed", exc, safe=False)
            self._fail("transcription pipeline failed")
        finally:
            # Reporting can itself raise after a terminal outcome is selected.
            # Keep that verdict available to the daemon's finalization even if
            # this call cannot return; record detachment remains daemon-owned.
            if record is not None:
                record.outcome = outcome_name
        return outcome_name

    def _gate(self, samples: np.ndarray, record: UtteranceRecord | None) -> bool:
        """Gate on the pipeline thread, outside callbacks and the state lock."""
        stats = speech_gate_stats(samples, SAMPLE_RATE, self._min_speech_rms)
        log_gate(stats)
        apply_gate(record, stats, samples)
        if not stats.passed and record is not None:
            record.failure = "gate_rejected"
        return stats.passed

    def _format(
        self, result: TranscriptionResult, record: UtteranceRecord | None
    ) -> tuple[str, bool]:
        """Measure readiness at successful formatting, before any delivery."""
        transcript_nonempty = bool(result.text.strip())
        format_started_at = time.perf_counter()
        text = transcript_text(result)
        apply_formatting(record, text, started_at=format_started_at, ready_at=time.perf_counter())
        if record is not None and not transcript_nonempty:
            record.failure = "empty"
        if not transcript_nonempty:
            self._publish_state(OverlayState.HIDDEN)
        return text, transcript_nonempty

    def _refine(self, text: str, record: UtteranceRecord | None) -> str:
        """Run the optional cleanup stage. Never raises; never loses the text.

        The refiner already fails open on its own errors, so the guard here is
        for the stage around it: a refiner that violated its contract must not
        be able to turn a finished transcript into a lost one. That is why
        *every* call into the collaborator is inside the try, not just
        ``refine`` — asking whether it will run, and reading back what it
        measured, are calls into the same object and can fail the same way. The
        only statement outside is the one that cannot raise: ``accepted``
        already holds the text to deliver by the time anything else runs.

        A refusal below the word threshold never shows the pill and never
        records a phase, because from the user's side nothing happened.

        The stage is also the longest one an utterance can sit in — a cold
        model load plus a reply is a two-minute worst case — so the cancel
        predicate goes in with the text. Cancelling is what gives the hotkey
        back: the overlay says CANCELLED at once, but the daemon stays busy
        until this returns, and every press until then is counted as an
        ignored busy press rather than starting a new utterance.
        """
        accepted = text
        try:
            if not self._refiner.will_refine(text):
                return text
            self._publish_state(OverlayState.REFINING)
            refined = self._refiner.refine(text, cancelled=self._cancelled)
            # A refiner that broke its contract and returned nothing must not
            # cost the utterance; the formatted transcript stays deliverable.
            accepted = refined if refined.strip() else text
            apply_refinement(
                record,
                self._refiner.last_result,
                delivered=accepted if accepted != text else None,
            )
            self._telemetry.checkpoint(record, "accepted_refinement")
        except Exception as exc:
            log_failure(log, logging.WARNING, "pipeline: refine_failed", exc, safe=False)
        return accepted

    def _apply_worker_timings(self, record: UtteranceRecord | None) -> None:
        apply_worker_timings(record, self._worker.last_timings)

    def _clipboard_checkpoint(self, record: UtteranceRecord | None) -> None:
        self._apply_delivery(record, attempted=True)
        self._telemetry.checkpoint(record, "clipboard_confirmed")

    def _apply_delivery(self, record: UtteranceRecord | None, *, attempted: bool) -> None:
        apply_delivery(
            record,
            self._deliverer.last_timings,
            attempted=attempted,
            observed_at=time.perf_counter(),
        )
