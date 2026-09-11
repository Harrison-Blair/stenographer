# SPDX-License-Identifier: GPL-3.0-or-later
"""Daemon pipeline behavior and regression coverage."""

from __future__ import annotations

import time

import pytest

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.daemon.pipeline import UtterancePipeline
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
