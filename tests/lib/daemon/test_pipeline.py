# SPDX-License-Identifier: GPL-3.0-or-later
"""Daemon pipeline behavior and regression coverage."""

from __future__ import annotations

import time

import pytest

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.daemon.pipeline import UtterancePipeline
from stenographer.lib.delivery.timings import DeliveryTimings
from stenographer.lib.transcribe.errors import WorkerError, WorkerPathologicalError
from stenographer.lib.transcribe.results import TranscriptionResult
from stenographer.lib.transcribe.utterance_record import UtteranceRecord

from .support import (
    _SILENCE,
    _SPEECH,
    CANARY,
    _daemon,
    _daemon_with_status,
    _run_utterance,
    _summary,
)


def test_transcription_failure_never_renders_the_worker_message(daemon_logs):
    # A ``WorkerError`` round-trips the ASR child's own detail string, whose
    # inference branch can quote decoder output derived from the audio: the
    # safe=False tier must keep it out of the log at every level, DEBUG
    # included. Seen to FAIL against ``log_failure(..., safe=True)``.
    daemon = _daemon(error=WorkerError(f"inference blew up on {CANARY}"))
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert CANARY not in daemon_logs.text
    assert "pipeline: transcription_failed" in daemon_logs.text
    assert "error=WorkerError" in daemon_logs.text
    assert "outcome=ERROR" in _summary(daemon_logs)


def test_gate_rejection_is_silent_and_reports_only_the_phases_it_reached(daemon_logs):
    daemon = _daemon(samples=_SILENCE)
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert daemon._deliverer.delivered == []
    line = _summary(daemon_logs)
    assert "outcome=SILENT" in line
    assert "gate=fail" in line
    assert "decode_ms=" not in line
    assert "chars_out=" not in line
    assert "audio: speech_gate verdict=fail" in daemon_logs.text


def test_a_pathological_decode_keeps_its_counts_only_reason(daemon_logs):
    # PathologicalOutputError's message is audited to carry counts only, and it
    # is the only thing that explains a decode the daemon silently discarded.
    # Seen to FAIL against a handler that caught WorkerPathologicalError under
    # the plain WorkerError arm at safe=False: detail= disappeared entirely.
    reason = "decoder word density exceeded limit (312 > 40)"
    daemon = _daemon(error=WorkerPathologicalError(reason))
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert f'detail="{reason}"' in daemon_logs.text
    assert "error=WorkerPathologicalError" in daemon_logs.text
    assert "outcome=ERROR" in _summary(daemon_logs)


def test_an_inference_failure_beside_it_still_renders_nothing(daemon_logs):
    # The sibling of the test above: same handler, opposite tier. Seen to FAIL
    # against collapsing both arms to safe=True.
    daemon = _daemon(error=WorkerError(f"inference blew up on {CANARY}"))
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert CANARY not in daemon_logs.text
    assert "error=WorkerError" in daemon_logs.text


def test_the_pill_stays_up_from_release_until_the_paste_lands():
    # The pill is the only sign the tool is still working after release. It
    # must run recording -> transcribing -> delivering -> hidden with no hidden
    # gap, even when the model is already warm. Seen to FAIL against a key-up
    # that published HIDDEN and only a cold load published TRANSCRIBING: the
    # sequence read [RECORDING, HIDDEN, DELIVERING, HIDDEN].
    daemon, status = _daemon_with_status(
        result=TranscriptionResult(text="one", duration_seconds=1.0), warm=True
    )
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert status.states == [
        OverlayState.RECORDING,
        OverlayState.TRANSCRIBING,
        OverlayState.DELIVERING,
        OverlayState.HIDDEN,
    ]


def test_a_gate_rejection_still_takes_the_pill_down():
    # Silence is success-shaped: the pill goes away without an error state.
    daemon, status = _daemon_with_status(samples=_SILENCE)
    try:
        _run_utterance(daemon)
    finally:
        daemon.stop()

    assert status.states[0] is OverlayState.RECORDING
    assert status.states[-1] is OverlayState.HIDDEN
    assert OverlayState.ERROR not in status.states
    assert OverlayState.DELIVERING not in status.states


def test_feedback_failures_preserve_the_already_delivered_outcome(daemon_logs):
    # The callback failure must not lose the selected outcome while unwinding
    # from the extracted pipeline into the daemon's finalization wrapper.
    # Seen to fail when the wrapper's default ERROR overwrote DELIVERED because
    # the exception prevented the pipeline's return-value assignment.
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    record = UtteranceRecord(utt=1, started_at=time.perf_counter(), source="hotkey", mode="hold")
    daemon._record = record
    daemon._utterance_id = record.utt
    daemon._busy = True

    def publish_state(state):
        if state is OverlayState.HIDDEN:
            raise ValueError("feedback failed after delivery")

    def fail(message):
        raise RuntimeError("failure reporting also failed")

    daemon._pipeline = UtterancePipeline(
        min_speech_rms=daemon._cfg.audio.min_speech_rms,
        worker=daemon._worker,
        deliverer=daemon._deliverer,
        telemetry=daemon._telemetry,
        publish_state=publish_state,
        fail=fail,
        play_cue=daemon._feedback.play,
        cancelled=daemon._cancel_pending,
        cancel_state=lambda: OverlayState.HIDDEN,
    )
    try:
        with pytest.raises(RuntimeError, match="failure reporting also failed"):
            daemon._run_pipeline(_SPEECH)
        assert daemon._busy is False
        assert daemon._record is None
        assert record.failure == "error"
        assert len(daemon._deliverer.delivered) == 1
        assert "outcome=DELIVERED" in _summary(daemon_logs)
    finally:
        daemon.stop()


class _Recorded:
    """The pipeline's injected reporting surface, captured in call order."""

    def __init__(self) -> None:
        self.states: list[OverlayState] = []
        self.cues: list[str] = []
        self.failures: list[str] = []

    def publish(self, state: OverlayState) -> None:
        self.states.append(state)

    def cue(self, name: str) -> None:
        self.cues.append(name)

    def fail(self, message: str) -> None:
        self.failures.append(message)


class _StubDeliverer:
    """Delivery double with a real ``last_timings`` contract."""

    def __init__(self, *, result=True, error=None, copy_first=False) -> None:
        self._result = result
        self._error = error
        self._copy_first = copy_first
        self.delivered: list[str] = []
        self.last_timings: DeliveryTimings | None = None

    def deliver(self, text, *, on_copied=None, cancelled=None):
        self.delivered.append(text)
        if self._copy_first:
            self.last_timings = DeliveryTimings(
                copy_ms=8.0, release_wait_ms=None, release_timeout=None, copied=True
            )
            if on_copied is not None:
                on_copied()
        if self._error is not None:
            raise self._error
        self.last_timings = DeliveryTimings(
            copy_ms=8.0,
            release_wait_ms=30.0,
            release_timeout=False,
            copied=True,
            chord_sent=bool(self._result),
        )
        return self._result

    def close(self) -> None: ...


class _CountingCancel:
    """Cancelled after *after* questions: the edge can land between two checks."""

    def __init__(self, after: int) -> None:
        self.after = after
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.calls > self.after


def _pipeline(daemon, *, deliverer=None, cancelled=None):
    reported = _Recorded()
    pipeline = UtterancePipeline(
        min_speech_rms=daemon._cfg.audio.min_speech_rms,
        worker=daemon._worker,
        deliverer=daemon._deliverer if deliverer is None else deliverer,
        telemetry=daemon._telemetry,
        publish_state=reported.publish,
        fail=reported.fail,
        play_cue=reported.cue,
        cancelled=(lambda: False) if cancelled is None else cancelled,
        cancel_state=lambda: OverlayState.CANCELLED,
    )
    return pipeline, reported


def _record() -> UtteranceRecord:
    return UtteranceRecord(
        utt=1,
        started_at=time.perf_counter(),
        stopped_at=time.perf_counter(),
        source="hotkey",
        mode="hold",
    )


def test_a_cancel_before_the_gate_skips_every_later_stage():
    daemon = _daemon(result=TranscriptionResult(text="never", duration_seconds=1.0))
    pipeline, reported = _pipeline(daemon, cancelled=lambda: True)
    record = _record()

    assert pipeline.run(_SPEECH, utterance=1, record=record) == "CANCELLED"

    assert record.outcome == "CANCELLED"
    assert record.gate is None
    assert daemon._worker.utterances == []
    assert reported.states == [OverlayState.CANCELLED]
    assert reported.failures == []


def test_a_cancel_racing_a_transcription_failure_is_reported_as_cancelled(daemon_logs):
    # The user let go of the cancel binding while the decode was already
    # failing: the failure must not become an error pill after the cancel.
    daemon = _daemon(error=WorkerError(f"inference blew up on {CANARY}"))
    cancelled = _CountingCancel(after=1)
    pipeline, reported = _pipeline(daemon, cancelled=cancelled)
    record = _record()

    assert pipeline.run(_SPEECH, utterance=1, record=record) == "CANCELLED"

    assert record.outcome == "CANCELLED"
    assert record.failure is None
    assert reported.states[-1] is OverlayState.CANCELLED
    assert reported.failures == []
    assert "pipeline: transcription_failed" not in daemon_logs.text


def test_a_failed_copy_is_reported_as_a_copy_failure(daemon_logs):
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    deliverer = _StubDeliverer(error=RuntimeError(f"clipboard refused {CANARY}"))
    pipeline, reported = _pipeline(daemon, deliverer=deliverer)
    record = _record()

    assert pipeline.run(_SPEECH, utterance=1, record=record) == "ERROR"

    assert record.failure == "copy_failed"
    assert reported.failures == ["delivery failed"]
    assert reported.states == [OverlayState.DELIVERING]
    assert "pipeline: delivery_failed" in daemon_logs.text
    assert "error=RuntimeError" in daemon_logs.text
    # The clipboard writer's own message can quote the transcript it was given.
    assert CANARY not in daemon_logs.text


def test_a_chord_failure_after_a_confirmed_copy_keeps_the_copied_words(daemon_logs):
    daemon = _daemon(result=TranscriptionResult(text="one two three", duration_seconds=1.0))
    deliverer = _StubDeliverer(error=RuntimeError("chord refused"), copy_first=True)
    pipeline, reported = _pipeline(daemon, deliverer=deliverer)
    record = _record()

    assert pipeline.run(_SPEECH, utterance=1, record=record) == "ERROR"

    assert record.failure == "chord_failed"
    assert record.copied_words == 3
    assert record.chord_words is None
    assert record.copy_ms == 8.0
    assert reported.failures == ["delivery failed"]
    assert "pipeline: delivery_failed" in daemon_logs.text
    assert "error=RuntimeError" in daemon_logs.text


def test_a_cancel_during_delivery_is_reported_as_cancelled(daemon_logs):
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    deliverer = _StubDeliverer(error=RuntimeError("clipboard refused"))
    cancelled = _CountingCancel(after=2)
    pipeline, reported = _pipeline(daemon, deliverer=deliverer, cancelled=cancelled)
    record = _record()

    assert pipeline.run(_SPEECH, utterance=1, record=record) == "CANCELLED"

    assert record.failure is None
    assert reported.failures == []
    assert reported.states[-1] is OverlayState.CANCELLED
    assert "pipeline: delivery_failed" not in daemon_logs.text


def test_a_cancel_that_withheld_the_chord_clears_the_failure():
    # ``deliver`` returns False when it sees the cancel before the chord: that
    # is the user's own doing, not a copy failure to report.
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    deliverer = _StubDeliverer(result=False)
    cancelled = _CountingCancel(after=2)
    pipeline, reported = _pipeline(daemon, deliverer=deliverer, cancelled=cancelled)
    record = _record()

    assert pipeline.run(_SPEECH, utterance=1, record=record) == "CANCELLED"

    assert record.failure is None
    assert reported.failures == []
    assert reported.cues == []
    assert reported.states[-1] is OverlayState.CANCELLED


def test_a_refused_copy_without_a_cancel_is_an_error_with_its_own_message():
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    deliverer = _StubDeliverer(result=False)
    pipeline, reported = _pipeline(daemon, deliverer=deliverer)
    record = _record()

    assert pipeline.run(_SPEECH, utterance=1, record=record) == "ERROR"

    assert record.failure == "copy_failed"
    assert reported.failures == ["could not copy transcript to clipboard"]
    assert reported.cues == []


def test_an_empty_transcript_takes_the_pill_down_without_delivering():
    daemon = _daemon(result=TranscriptionResult(text="   ", duration_seconds=1.0))
    deliverer = _StubDeliverer()
    pipeline, reported = _pipeline(daemon, deliverer=deliverer)
    record = _record()

    assert pipeline.run(_SPEECH, utterance=1, record=record) == "SILENT"

    assert record.failure == "empty"
    assert record.chars_out == 0
    assert deliverer.delivered == []
    assert reported.states == [OverlayState.HIDDEN]
    assert reported.failures == []


def test_a_confirmed_copy_checkpoints_the_clipboard_before_the_chord():
    daemon = _daemon(result=TranscriptionResult(text="one two", duration_seconds=1.0))
    deliverer = _StubDeliverer(copy_first=True)
    pipeline, reported = _pipeline(daemon, deliverer=deliverer)
    record = _record()

    assert pipeline.run(_SPEECH, utterance=1, record=record) == "DELIVERED"

    assert record.copied_words == 2
    assert record.chord_words == 2
    assert record.stop_to_chord_ms is not None
    assert reported.states == [OverlayState.DELIVERING, OverlayState.HIDDEN]
    assert reported.cues == ["delivered"]


def test_a_run_without_a_record_still_reports_its_outcome(daemon_logs):
    # ``transcribe <file>`` and a torn-down utterance both run the pipeline
    # with no record to fill; every stage must stay projection-free.
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    pipeline, reported = _pipeline(daemon, deliverer=_StubDeliverer())

    assert pipeline.run(_SPEECH, utterance=1, record=None) == "DELIVERED"
    assert reported.states == [OverlayState.DELIVERING, OverlayState.HIDDEN]

    broken, failed = _pipeline(daemon, deliverer=_StubDeliverer(error=RuntimeError("no clipboard")))
    assert broken.run(_SPEECH, utterance=2, record=None) == "ERROR"
    assert failed.failures == ["delivery failed"]

    refused, cancelled = _pipeline(
        daemon, deliverer=_StubDeliverer(result=False), cancelled=_CountingCancel(after=2)
    )
    assert refused.run(_SPEECH, utterance=3, record=None) == "CANCELLED"
    assert cancelled.states[-1] is OverlayState.CANCELLED

    assert daemon_logs.text.count("pipeline: delivery_failed") == 1
    # The summary line belongs to the daemon's record, which there is none of.
    assert "pipeline: utterance " not in daemon_logs.text
