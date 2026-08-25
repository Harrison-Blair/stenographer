# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer transcribe``: transcribe an audio file.

The same gate, the same downmix, the same formatter call and the same summary
line as the daemon's pipeline — via ``transcribe.pipeline`` — so a file run is
a faithful rehearsal of a dictation instead of a second, subtly different one.
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

    from stenographer.audio import _resample_poly

    # ``utt=0`` is reserved for the file path: the daemon's ids start at 1.
    record = UtteranceRecord(utt=0, source="file")
    started_at = time.perf_counter()
    samples = _resample_poly(downmix(samples), sample_rate, SAMPLE_RATE)
    record.out_frames = int(samples.size)

    stats = speech_gate_stats(samples, SAMPLE_RATE, cfg.audio.min_speech_rms)
    log_gate(stats)
    record.gate = "pass" if stats.passed else "fail"
    record.peak_rms = stats.peak_rms
    record.frames_above = stats.frames_above

    load_started_at = time.perf_counter()
    m = model.Model(cfg.asr)
    record.cold = True
    record.load_ms = (time.perf_counter() - load_started_at) * 1000.0
    decode_started_at = time.perf_counter()
    try:
        result = m.transcribe(samples)
    finally:
        m.close()
    record.decode_ms = (time.perf_counter() - decode_started_at) * 1000.0
    record.vad_frames = round(result.vad_seconds * SAMPLE_RATE)
    record.segments = len(result.segments)
    record.words = sum(len(segment.words) for segment in result.segments)
    record.chars_raw = len(result.text)

    text = transcript_text(result, raw=args.raw)
    record.chars_out = len(text)
    record.outcome = "SILENT" if not text.strip() else "DELIVERED"
    record.total_ms = (time.perf_counter() - started_at) * 1000.0
    log_summary(record)

    sys.stdout.write(text)
    sys.stdout.write("\n")
    return 0
