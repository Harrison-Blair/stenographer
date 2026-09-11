# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared numeric measurements for one accepted utterance."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UtteranceRecord:
    """Everything measured about one utterance, in summary-line order.

    Every field but ``utt`` is optional: an utterance that fails its gate never
    reaches a decode, and a rendered ``None`` field is dropped rather than
    printed, so one record serves every early exit.
    """

    utt: int
    #: ``perf_counter`` at the moment this utterance was accepted. On the
    #: record, not on the daemon: the summary is rendered after the state lock
    #: is handed on, and a process-global origin would already belong to the
    #: next utterance after a fast re-press.
    started_at: float = 0.0
    source: str | None = None
    mode: str | None = None
    outcome: str | None = None
    activate_ms: float | None = None
    press_to_callback_ms: float | None = None
    activation_to_callback_ms: float | None = None
    max_adc_gap_ms: float | None = None
    adc_discontinuities: int | None = None
    capture_s: float | None = None
    in_frames: int | None = None
    out_frames: int | None = None
    overflow: bool | None = None
    capped: bool | None = None
    gate: str | None = None
    peak_rms: float | None = None
    frames_above: int | None = None
    cold: bool | None = None
    load_ms: float | None = None
    lock_wait_ms: float | None = None
    decode_ms: float | None = None
    vad_frames: int | None = None
    segments: int | None = None
    words: int | None = None
    chars_raw: int | None = None
    chars_out: int | None = None
    refine_ms: float | None = None
    refine_chars_in: int | None = None
    refine_chars_out: int | None = None
    refine_applied: bool | None = None
    refine_attempted: bool | None = None
    refine_failed: bool | None = None
    copy_ms: float | None = None
    release_wait_ms: float | None = None
    release_timeout: bool | None = None
    total_ms: float | None = None
    analytics_id: str | None = None
    device_name: str | None = None
    stopped_at: float | None = None
    recognized_words: int | None = None
    final_words: int | None = None
    copied_words: int | None = None
    chord_words: int | None = None
    asr_audio_s: float | None = None
    vad_s: float | None = None
    format_ms: float | None = None
    round_trip_ms: float | None = None
    finalize_ms: float | None = None
    stop_to_ready_ms: float | None = None
    stop_to_chord_ms: float | None = None
    input_rate: int | None = None
    channels: int | None = None
    callback_timing_count: int | None = None
    callback_count: int | None = None
    callback_metadata_dropped: int | None = None
    overflow_count: int | None = None
    recovered: bool | None = None
    mean_rms: float | None = None
    clipping_fraction: float | None = None
    ignored_busy_presses: int = 0
    failure: str | None = None
