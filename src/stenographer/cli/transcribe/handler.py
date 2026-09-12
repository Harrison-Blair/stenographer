# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer transcribe``: transcribe an audio file.

The same gate, the same downmix, the same formatter call and the same summary
line as the daemon's pipeline — via ``transcribe.pipeline`` — so a file run is
a faithful rehearsal of a dictation instead of a second, subtly different one.

``--refine`` is an explicit opt-in and deliberately does not inherit
``[stenographer.refine] enabled``: a one-off file transcription should not
start sending text to a model because the daemon was configured to. Everything
else about the stage — host, model, threshold, guard, fail-open — is shared
with the daemon path. ``--raw`` wins over it, since raw means "exactly what the
decoder produced".

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

from stenographer.cli.shared.config import with_config
from stenographer.cli.shared.errors import _fatal
from stenographer.lib.audio.constants import SAMPLE_RATE

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config
    from stenographer.lib.transcribe.utterance_record import UtteranceRecord


def _refine(
    cfg: Config,
    args: argparse.Namespace,
    text: str,
    record: UtteranceRecord | None,
) -> str:
    """Apply the opt-in cleanup pass, or hand *text* straight back."""

    from stenographer.lib.refine.factory import build_refiner
    from stenographer.lib.transcribe.pipeline import apply_refinement

    if args.raw or not getattr(args, "refine", False) or not text.strip():
        return text
    refiner = build_refiner(
        cfg.refine,
        idle_unload_seconds=cfg.asr.idle_unload_seconds,
        enabled=True,
    )
    if not refiner.will_refine(text):
        return text
    refined = refiner.refine(text)
    accepted = refined if refined.strip() else text
    apply_refinement(
        record,
        refiner.last_result,
        delivered=accepted if accepted != text else None,
    )
    return accepted


@with_config
def cmd_transcribe(args: argparse.Namespace, cfg: Config) -> int:
    from stenographer.lib.audio.gate import speech_gate_stats
    from stenographer.lib.transcribe.pipeline import (
        apply_formatting,
        apply_gate,
        apply_recognition,
        downmix,
        log_gate,
        log_summary,
        transcript_text,
    )
    from stenographer.lib.transcribe.utterance_record import UtteranceRecord

    path = pathlib.Path(args.file)
    if not path.exists():
        print(f"stenographer: file not found: {path}", file=sys.stderr)
        return 2

    from stenographer.lib.transcribe import model
    from stenographer.lib.transcribe.download import is_model_cached

    if not is_model_cached(cfg.asr.model):
        return _fatal("ASR model not found; run `stenographer model download`")

    import soundfile

    try:
        samples, sample_rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    except Exception as exc:
        print(f"stenographer: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    from stenographer.lib.audio.resample import _resample_poly
    from stenographer.lib.diagnostics.session import create_session
    from stenographer.lib.platform import current_platform
    from stenographer.lib.transcribe.pipeline import analytics_metrics

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
        apply_gate(record, stats, samples)
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
        apply_recognition(record, result)
        session.checkpoint(record.analytics_id, "accepted_recognition", analytics_metrics(record))
        terminal = "error"
        format_started_at = time.perf_counter()
        text = transcript_text(result, raw=args.raw)
        apply_formatting(record, text, started_at=format_started_at, ready_at=time.perf_counter())
        text = _refine(cfg, args, text, record)
        terminal = "success" if result.text.strip() else "empty"
    except Exception:
        record.outcome = "ERROR"
        raise
    finally:
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
