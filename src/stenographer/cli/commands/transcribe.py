# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer transcribe``: transcribe an audio file.

The same gate, the same downmix, the same formatter call and the same summary
line as the daemon's pipeline — via ``transcribe.pipeline`` — so a file run is
a faithful rehearsal of a dictation instead of a second, subtly different one.

One deliberate difference: the gate here only *reports*. A file the user named
explicitly is decoded whatever its energy, because the answer they asked for is
the transcript, not a verdict. The summary therefore records ``SILENT`` when
the gate would have rejected the audio and ``OK`` otherwise — never
``DELIVERED``, which means a paste that this path never performs.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time
from typing import TYPE_CHECKING

from stenographer.cli import _fatal
from stenographer.cli.commands import with_config
from stenographer.constants import SAMPLE_RATE

if TYPE_CHECKING:
    from stenographer.config import Config


@with_config
def cmd_transcribe(args: argparse.Namespace, cfg: Config) -> int:
    from stenographer.audio import speech_gate_stats
    from stenographer.transcribe.pipeline import (
        UtteranceRecord,
        downmix,
        log_gate,
        log_summary,
        transcript_text,
    )

    path = pathlib.Path(args.file)
    if not path.exists():
        print(f"stenographer: file not found: {path}", file=sys.stderr)
        return 2

    from stenographer.transcribe import model

    if not model.is_model_cached(cfg.asr.model):
        return _fatal("ASR model not found; run `stenographer model download`")

    import soundfile

    try:
        samples, sample_rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    except Exception as exc:
        print(f"stenographer: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    from stenographer.analytics import count_words
    from stenographer.audio import _resample_poly
    from stenographer.diagnostics import create_session
    from stenographer.platform import current_platform
    from stenographer.transcribe.pipeline import analytics_metrics

    session = create_session(cfg, current_platform())
    record = UtteranceRecord(utt=0, started_at=time.perf_counter(), source="file")
    record.analytics_id = session.start(0, source="file")
    record.input_rate = int(sample_rate)
    record.channels = int(samples.shape[1])
    record.in_frames = int(samples.shape[0])
    record.capture_s = record.in_frames / sample_rate
    m = None
    text = ""
    terminal = "error"
    try:
        finalize_started_at = time.perf_counter()
        samples = _resample_poly(downmix(samples), sample_rate, SAMPLE_RATE)
        record.finalize_ms = (time.perf_counter() - finalize_started_at) * 1000
        record.out_frames = int(samples.size)
        session.checkpoint(record.analytics_id, "secured_capture", analytics_metrics(record))
        record.stopped_at = time.perf_counter()
        stats = speech_gate_stats(samples, SAMPLE_RATE, cfg.audio.min_speech_rms)
        log_gate(stats)
        record.gate = "pass" if stats.passed else "fail"
        record.peak_rms = stats.peak_rms
        record.frames_above = stats.frames_above
        record.mean_rms = stats.mean_rms
        record.outcome = "OK" if stats.passed else "SILENT"

        load_started_at = time.perf_counter()
        record.cold = True
        terminal = "model_failed"
        try:
            m = model.Model(cfg.asr)
        finally:
            record.load_ms = (time.perf_counter() - load_started_at) * 1000
        terminal = "decode_failed"
        decode_started_at = time.perf_counter()
        try:
            result = m.transcribe(samples)
        finally:
            record.decode_ms = (time.perf_counter() - decode_started_at) * 1000
        record.recognized_words = count_words(result.text)
        record.asr_audio_s = record.capture_s
        record.vad_s = result.vad_seconds
        session.checkpoint(record.analytics_id, "accepted_recognition", analytics_metrics(record))
        terminal = "error"
        format_started_at = time.perf_counter()
        text = transcript_text(result, raw=args.raw)
        record.format_ms = (time.perf_counter() - format_started_at) * 1000
        record.vad_frames = round(result.vad_seconds * SAMPLE_RATE)
        record.segments = len(result.segments)
        record.words = sum(len(segment.words) for segment in result.segments)
        record.chars_raw = len(result.text)
        record.chars_out = len(text)
        record.final_words = count_words(text)
        terminal = "success" if result.text.strip() else "empty"
    except Exception:
        record.outcome = "ERROR"
        raise
    finally:
        # Ready and inference boundaries deliberately precede model shutdown.
        if record.stopped_at is not None:
            record.stop_to_ready_ms = (time.perf_counter() - record.stopped_at) * 1000
        record.total_ms = (time.perf_counter() - record.started_at) * 1000
        session.finish(record.analytics_id, terminal, analytics_metrics(record))
        session.close()
        primary_error = sys.exception()
        try:
            if m is not None:
                m.close()
        except Exception:
            if primary_error is None:
                raise
        finally:
            log_summary(record)

    sys.stdout.write(text)
    sys.stdout.write("\n")
    return 0
