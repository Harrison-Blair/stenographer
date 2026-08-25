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

    from stenographer.audio import _resample_poly

    # ``utt=0`` is reserved for the file path: the daemon's ids start at 1.
    record = UtteranceRecord(utt=0, started_at=time.perf_counter(), source="file")
    samples = _resample_poly(downmix(samples), sample_rate, SAMPLE_RATE)
    record.out_frames = int(samples.size)

    stats = speech_gate_stats(samples, SAMPLE_RATE, cfg.audio.min_speech_rms)
    log_gate(stats)
    record.gate = "pass" if stats.passed else "fail"
    record.peak_rms = stats.peak_rms
    record.frames_above = stats.frames_above
    record.outcome = "OK" if stats.passed else "SILENT"

    load_started_at = time.perf_counter()
    m = model.Model(cfg.asr)
    record.cold = True
    record.load_ms = (time.perf_counter() - load_started_at) * 1000.0
    decode_started_at = time.perf_counter()
    try:
        result = m.transcribe(samples)
        vad_frames = round(result.vad_seconds * SAMPLE_RATE)
        segments = len(result.segments)
        words = sum(len(segment.words) for segment in result.segments)
        chars_raw = len(result.text)

        text = transcript_text(result, raw=args.raw)
        record.vad_frames = vad_frames
        record.segments = segments
        record.words = words
        record.chars_raw = chars_raw
        record.chars_out = len(text)
    except Exception:
        record.outcome = "ERROR"
        raise
    finally:
        primary_error = sys.exception()
        try:
            m.close()
        except Exception:
            if primary_error is None:
                raise
        finally:
            record.decode_ms = (time.perf_counter() - decode_started_at) * 1000.0
            record.total_ms = (time.perf_counter() - record.started_at) * 1000.0
            log_summary(record)

    sys.stdout.write(text)
    sys.stdout.write("\n")
    return 0
