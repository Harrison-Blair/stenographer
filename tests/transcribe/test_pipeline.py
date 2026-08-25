# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for the shared gate → decode → format core.

Covered here: the summary line's field order and its dropping of fields no
early exit ever measured, the channel-0 downmix both capture paths use, and the
one formatter call the daemon and ``stenographer transcribe`` share.
"""

from __future__ import annotations

import numpy as np

from stenographer.transcribe.model import TranscriptionResult
from stenographer.transcribe.pipeline import (
    UtteranceRecord,
    downmix,
    summary_fields,
    transcript_text,
)
from stenographer.utils.logging_setup import fmt_event


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
