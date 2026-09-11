# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for the shared gate → decode → format core.

Covered here: the summary line's field order and its dropping of fields no
early exit ever measured, the channel-0 downmix both capture paths use, and the
one formatter call the daemon and ``stenographer transcribe`` share.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from stenographer.lib.logging.pipeline import fmt_event
from stenographer.lib.transcribe.pipeline import downmix, summary_fields, transcript_text
from stenographer.lib.transcribe.results import TranscriptionResult
from stenographer.lib.transcribe.utterance_record import UtteranceRecord


def _line(record: UtteranceRecord) -> str:
    return fmt_event("pipeline", "utterance", **summary_fields(record))


def test_summary_omits_every_phase_the_utterance_never_reached():
    # A capture that fails its gate never loads a model, decodes, or delivers.
    # Seen to FAIL against a ``summary_fields`` that substituted 0 for None:
    # a reported decode_ms=0 on a gate-rejected utterance is a lie about what
    # happened, not a missing measurement.
    record = UtteranceRecord(utt=7, mode="hold", outcome="SILENT", gate="fail")
    line = _line(record)

    assert line.startswith("pipeline: utterance utt=7 mode=hold outcome=SILENT ")
    for absent in ("decode_ms=", "load_ms=", "chars_out=", "copy_ms=", "cold=", "source="):
        assert absent not in line


def test_summary_keeps_the_field_order_and_renders_flags_as_digits():
    record = UtteranceRecord(
        utt=1,
        mode="toggle",
        outcome="DELIVERED",
        activate_ms=1.2345,
        capture_s=2.0,
        in_frames=32000,
        out_frames=32000,
        overflow=False,
        capped=False,
        gate="pass",
        peak_rms=0.0005123456,
        frames_above=12,
        cold=True,
        load_ms=900.0,
        lock_wait_ms=0.0,
        decode_ms=1500.0,
        vad_frames=16000,
        segments=1,
        words=4,
        chars_raw=20,
        chars_out=21,
        copy_ms=8.0,
        release_wait_ms=30.0,
        release_timeout=False,
        total_ms=2500.0,
    )

    assert _line(record) == (
        "pipeline: utterance utt=1 mode=toggle outcome=DELIVERED activate_ms=1.2 capture_s=2 "
        "in_frames=32000 out_frames=32000 overflow=0 capped=0 gate=pass peak_rms=0.000512 "
        "frames_above=12 cold=1 load_ms=900 lock_wait_ms=0 decode_ms=1500 vad_frames=16000 "
        "segments=1 words=4 chars_raw=20 chars_out=21 copy_ms=8 release_wait_ms=30 "
        "release_timeout=0 total_ms=2500"
    )


def test_file_runs_carry_their_own_source_field():
    line = _line(UtteranceRecord(utt=0, source="file", outcome="DELIVERED"))
    assert line.startswith("pipeline: utterance utt=0 source=file outcome=DELIVERED")


def test_error_summary_keeps_attempt_metrics_and_omits_result_metrics():
    record = UtteranceRecord(
        utt=0,
        source="file",
        outcome="ERROR",
        out_frames=3200,
        gate="pass",
        peak_rms=0.1,
        frames_above=4,
        cold=True,
        load_ms=10.0,
        decode_ms=20.0,
        total_ms=30.0,
    )
    line = _line(record)

    assert line == (
        "pipeline: utterance utt=0 source=file outcome=ERROR out_frames=3200 gate=pass "
        "peak_rms=0.1 frames_above=4 cold=1 load_ms=10 decode_ms=20 total_ms=30"
    )
    for absent in ("vad_frames=", "segments=", "words=", "chars_raw=", "chars_out="):
        assert absent not in line


def test_downmix_keeps_channel_zero_not_the_channel_mean():
    # Seen to FAIL against ``samples.mean(axis=1)``: averaging a stereo capture
    # whose second channel is silent halves the speech the gate has to find,
    # and one that is out of phase cancels it outright.
    stereo = np.array([[1.0, -1.0], [0.5, -0.5]], dtype=np.float32)

    assert downmix(stereo).tolist() == [1.0, 0.5]
    assert downmix(np.array([[0.25], [0.75]], dtype=np.float32)).tolist() == [0.25, 0.75]
    assert downmix(np.array([0.25, 0.75], dtype=np.float32)).tolist() == [0.25, 0.75]


def test_the_shared_formatter_owns_the_dictation_trailing_space():
    # The daemon and ``stenographer transcribe`` both reach the formatter only
    # through here, so the trailing space that keeps consecutive utterances
    # from running together is decided once. Seen to FAIL against a
    # ``transcript_text`` that forwarded ``trailing_space=False``.
    result = TranscriptionResult(text="hello there", duration_seconds=1.0)

    assert transcript_text(result) == "Hello there "
    assert transcript_text(result, raw=True) == "hello there"


@pytest.mark.parametrize("text", ["hello world", ""])
def test_measurement_phases_preserve_recognition_and_readiness(text):
    from stenographer.lib.delivery.timings import DeliveryTimings
    from stenographer.lib.transcribe.pipeline import (
        analytics_metrics,
        apply_delivery,
        apply_formatting,
        apply_recognition,
        apply_worker_timings,
    )
    from stenographer.lib.transcribe.worker_timings import WorkerTimings

    records = [
        UtteranceRecord(utt=0, source=source, capture_s=2, stopped_at=10)
        for source in ("file", "hotkey")
    ]
    result = TranscriptionResult(text=text, duration_seconds=2, vad_seconds=1)
    for record in records:
        apply_worker_timings(record, WorkerTimings(2, None, None))
        assert record.load_ms is None and record.decode_ms is None
        apply_recognition(record, result)
        # This is also the retained snapshot when formatting raises.
        assert record.chars_raw == len(text)
        assert record.recognized_words == (2 if text else 0)
        assert record.vad_frames == 16000 and record.asr_audio_s == 2
        assert record.chars_out is None and record.stop_to_ready_ms is None
        apply_formatting(record, text, started_at=11, ready_at=12)
        assert record.format_ms == 1000 and record.stop_to_ready_ms == 2000
    assert analytics_metrics(records[0]) == analytics_metrics(records[1])
    record = records[1]
    apply_delivery(record, DeliveryTimings(1, 2, False, True, True), attempted=True, observed_at=15)
    assert record.stop_to_ready_ms == 2000 and record.stop_to_chord_ms == 5000
    assert record.copied_words == record.final_words == record.chord_words


def test_capture_measurements_are_projected_relative_to_the_press():
    from stenographer.lib.audio.records import CaptureStats
    from stenographer.lib.transcribe.pipeline import apply_capture

    record = UtteranceRecord(utt=3, started_at=100.0)
    stats = CaptureStats(
        activate_ms=4.5,
        capture_seconds=2.0,
        input_frames=96000,
        output_frames=32000,
        overflow=True,
        capped=True,
        first_callback_at=100.25,
        activation_to_callback_ms=12.5,
        max_adc_gap_ms=3.0,
        adc_discontinuities=2,
        device_name="USB microphone",
        input_rate=48000,
        channels=2,
        finalize_ms=1.5,
        callback_timing_count=180,
        callback_count=200,
        callback_metadata_dropped=20,
        overflow_count=3,
        recovered=True,
    )

    apply_capture(record, stats)

    # The press-relative latency is derived here; the recorder only ever
    # reports the raw callback timestamp on its own clock.
    assert record.press_to_callback_ms == pytest.approx(250.0)
    assert record.capture_s == pytest.approx(2.0)  # 96000 frames at 48 kHz
    assert record.in_frames == 96000
    assert record.out_frames == 32000
    assert record.input_rate == 48000
    assert record.channels == 2
    assert record.device_name == "USB microphone"
    assert record.overflow is True
    assert record.capped is True
    assert record.recovered is True
    assert record.callback_metadata_dropped == 20
    assert record.adc_discontinuities == 2
    assert record.activate_ms == 4.5


def test_capture_without_a_callback_leaves_press_latency_unknown():
    from stenographer.lib.audio.records import CaptureStats
    from stenographer.lib.transcribe.pipeline import apply_capture

    record = UtteranceRecord(utt=3, started_at=100.0)

    apply_capture(
        record,
        CaptureStats(
            activate_ms=1.0,
            capture_seconds=0.0,
            input_frames=0,
            output_frames=0,
            overflow=False,
            capped=False,
        ),
    )

    assert record.press_to_callback_ms is None
    assert record.in_frames == 0


def test_gate_verdict_and_clipping_come_from_the_same_samples():
    from stenographer.lib.audio.records import GateStats
    from stenographer.lib.transcribe.pipeline import apply_gate

    record = UtteranceRecord(utt=1)
    stats = GateStats(
        peak_rms=0.02,
        mean_rms=0.01,
        frames_total=10,
        frames_above=4,
        threshold=0.0005,
        passed=True,
    )
    samples = np.array([1.0, 0.5, -1.0, 0.0], dtype=np.float32)

    apply_gate(record, stats, samples)

    assert record.gate == "pass"
    assert record.peak_rms == 0.02
    assert record.mean_rms == 0.01
    assert record.frames_above == 4
    assert record.clipping_fraction == pytest.approx(0.5)


def test_gate_failure_and_empty_audio_report_no_clipping():
    from stenographer.lib.audio.records import GateStats
    from stenographer.lib.transcribe.pipeline import apply_gate

    record = UtteranceRecord(utt=1)

    apply_gate(
        record,
        GateStats(
            peak_rms=0.0,
            mean_rms=0.0,
            frames_total=0,
            frames_above=0,
            threshold=0.0005,
            passed=False,
        ),
        np.empty(0, dtype=np.float32),
    )

    assert record.gate == "fail"
    assert record.clipping_fraction == 0.0


def test_a_warm_model_load_measurement_survives_a_later_warm_transcription():
    from stenographer.lib.transcribe.pipeline import apply_worker_timings
    from stenographer.lib.transcribe.worker_timings import WorkerTimings

    record = UtteranceRecord(utt=1)

    apply_worker_timings(record, WorkerTimings(1.0, 900.0, 20.0, round_trip_ms=25.0))
    apply_worker_timings(record, WorkerTimings(2.0, None, 30.0, round_trip_ms=35.0))

    # A second, warm request has no load of its own: the measured cold load
    # must not be overwritten with "unknown".
    assert record.load_ms == 900.0
    assert record.lock_wait_ms == 2.0
    assert record.decode_ms == 30.0
    assert record.round_trip_ms == 35.0


def test_every_phase_is_a_no_op_without_a_record():
    from stenographer.lib.audio.records import CaptureStats, GateStats
    from stenographer.lib.delivery.timings import DeliveryTimings
    from stenographer.lib.transcribe.pipeline import (
        apply_capture,
        apply_delivery,
        apply_formatting,
        apply_gate,
        apply_recognition,
        apply_worker_timings,
    )
    from stenographer.lib.transcribe.worker_timings import WorkerTimings

    stats = CaptureStats(
        activate_ms=1.0,
        capture_seconds=1.0,
        input_frames=16000,
        output_frames=16000,
        overflow=False,
        capped=False,
    )
    gate = GateStats(
        peak_rms=0.1, mean_rms=0.1, frames_total=1, frames_above=1, threshold=0.0005, passed=True
    )

    # An unrecorded utterance (analytics disabled) runs the same phases.
    apply_capture(None, stats)
    apply_capture(UtteranceRecord(utt=1), None)
    apply_gate(None, gate, np.zeros(4, dtype=np.float32))
    apply_recognition(None, TranscriptionResult(text="hi", duration_seconds=1.0))
    apply_formatting(None, "hi", started_at=0.0, ready_at=1.0)
    apply_worker_timings(None, WorkerTimings(1.0, None, None))
    apply_worker_timings(UtteranceRecord(utt=1), None)
    apply_delivery(None, DeliveryTimings(1.0, None, None), attempted=True, observed_at=1.0)

    # An attempt that never reached delivery leaves the boundaries unknown.
    record = UtteranceRecord(utt=1, stopped_at=1.0)
    apply_delivery(record, DeliveryTimings(1.0, None, None), attempted=False, observed_at=2.0)
    apply_delivery(record, None, attempted=True, observed_at=2.0)
    assert record.copy_ms is None
    assert record.copied_words is None
    assert record.stop_to_chord_ms is None


def test_one_utterance_logs_exactly_one_summary_line(caplog):
    from stenographer.lib.transcribe.pipeline import log_summary

    record = UtteranceRecord(utt=9, mode="hold", outcome="DELIVERED", total_ms=1234.5)
    with caplog.at_level(logging.INFO, logger="stenographer.lib.transcribe.pipeline"):
        log_summary(record)

    assert [r.getMessage() for r in caplog.records] == [
        "pipeline: utterance utt=9 mode=hold outcome=DELIVERED total_ms=1234.5"
    ]


def test_the_gate_line_reports_the_numbers_behind_its_verdict(caplog):
    from stenographer.lib.audio.records import GateStats
    from stenographer.lib.transcribe.pipeline import log_gate

    with caplog.at_level(logging.INFO, logger="stenographer.lib.transcribe.pipeline"):
        log_gate(
            GateStats(
                peak_rms=0.0012345678,
                mean_rms=0.0009,
                frames_total=10,
                frames_above=0,
                threshold=0.01,
                passed=False,
            )
        )

    assert [r.getMessage() for r in caplog.records] == [
        "audio: speech_gate verdict=fail peak_rms=0.001235 mean_rms=0.0009 "
        "frames_total=10 frames_above=0 threshold=0.01"
    ]


def test_delivery_counts_only_the_words_that_actually_got_that_far():
    from stenographer.lib.delivery.timings import DeliveryTimings
    from stenographer.lib.transcribe.pipeline import apply_delivery, apply_formatting

    copied_only = UtteranceRecord(utt=1, stopped_at=10.0)
    apply_formatting(copied_only, "hello there ", started_at=10.0, ready_at=10.5)
    apply_delivery(
        copied_only, DeliveryTimings(1.0, 2.0, False, copied=True), attempted=True, observed_at=11.0
    )

    # The clipboard holds the transcript; the chord never fired.
    assert copied_only.copied_words == 2
    assert copied_only.chord_words is None
    assert copied_only.stop_to_chord_ms is None
    assert copied_only.release_wait_ms == 2.0

    failed = UtteranceRecord(utt=2, stopped_at=10.0)
    apply_formatting(failed, "hello there ", started_at=10.0, ready_at=10.5)
    apply_delivery(failed, DeliveryTimings(1.0, None, None), attempted=True, observed_at=11.0)
    assert failed.copied_words is None
    assert failed.chord_words is None
    assert failed.copy_ms == 1.0


def test_a_file_run_has_no_stop_boundary_to_measure_against():
    from stenographer.lib.delivery.timings import DeliveryTimings
    from stenographer.lib.transcribe.pipeline import apply_delivery, apply_formatting

    record = UtteranceRecord(utt=1, source="file")
    apply_formatting(record, "hello ", started_at=10.0, ready_at=10.5)
    apply_delivery(
        record,
        DeliveryTimings(1.0, None, None, copied=True, chord_sent=True),
        attempted=True,
        observed_at=11.0,
    )

    assert record.format_ms == 500
    assert record.stop_to_ready_ms is None
    assert record.chord_words == 1
    assert record.stop_to_chord_ms is None
