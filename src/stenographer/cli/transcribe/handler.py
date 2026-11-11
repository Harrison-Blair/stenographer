# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer transcribe``: transcribe an audio file.

The same speech check, the same downmix, the same formatter call and the same summary
line as the daemon's pipeline — via ``transcribe.pipeline`` — so a file run is
a faithful rehearsal of a dictation instead of a second, subtly different one.

``--refine`` is an explicit opt-in and deliberately does not inherit
``[stenographer.refine] enabled``: a one-off file transcription should not
start sending text to a model because the daemon was configured to. Everything
else about the stage — host, model, threshold, guard, fail-open — is shared
with the daemon path. ``--raw`` wins over it, since raw means "exactly what the
decoder produced".

One deliberate difference: the speech check here only *reports*. A file the
user named explicitly is decoded whatever the VAD finds, because the answer they
asked for is the transcript, not a verdict. The summary therefore records
``SILENT`` when the VAD finds no speech and ``OK`` otherwise — never
``DELIVERED``, which means a paste that this path never performs.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time
from typing import TYPE_CHECKING

from stenographer.cli.shared.config import with_config
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

    if args.raw or not args.refine:
        return text
    refiner = build_refiner(
        cfg.refine,
        idle_unload_seconds=cfg.asr.idle_unload_seconds,
        enabled=True,
    )
    if refiner is None or not refiner.will_refine(text):
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
    import numpy as np

    from stenographer.lib.files.media import inspect_media, iter_media_audio
    from stenographer.lib.live.models import vad_model_path
    from stenographer.lib.transcribe.dictation_vad import speech_seconds
    from stenographer.lib.transcribe.pipeline import (
        apply_formatting,
        apply_levels,
        apply_recognition,
        apply_speech,
        log_summary,
        transcript_text,
    )
    from stenographer.lib.transcribe.utterance_record import UtteranceRecord

    if args.raw and args.refine:
        print("stenographer: --raw skips refinement requested by --refine", file=sys.stderr)

    from stenographer.lib.platform import current_platform

    path = pathlib.Path(args.file)
    decoder = current_platform().ffmpeg_decoder()
    if not path.is_file():
        print(f"stenographer: cannot read {path}: not a file", file=sys.stderr)
        return 2
    info = inspect_media(path, decoder)
    if info.needs_ffmpeg:
        print(
            f"stenographer: cannot read {path}: needs ffmpeg; install it with your system "
            "package manager",
            file=sys.stderr,
        )
        return 69
    try:
        blocks = list(iter_media_audio(path, info, decoder))
    except Exception as exc:
        print(f"stenographer: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    samples = np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)
    sample_rate = SAMPLE_RATE

    from stenographer.lib.transcribe import bark_download, model

    if not bark_download.is_model_cached():
        print(
            "stenographer: ASR model not found; run `stenographer model download --asr`",
            file=sys.stderr,
        )
        return 78

    from stenographer.lib.diagnostics.session import create_session
    from stenographer.lib.transcribe.pipeline import analytics_metrics

    session = create_session(cfg, current_platform())
    record = UtteranceRecord(utt=0, started_at=time.perf_counter(), source="file")
    record.analytics_id = session.start(0, source="file")
    record.input_rate = int(sample_rate)
    record.channels = 1
    record.in_frames = int(samples.size)
    record.capture_s = record.in_frames / sample_rate
    m = None
    terminal = "error"
    try:
        finalize_started_at = time.perf_counter()
        record.finalize_ms = (time.perf_counter() - finalize_started_at) * 1000
        record.out_frames = int(samples.size)
        session.checkpoint(record.analytics_id, "secured_capture", analytics_metrics(record))
        record.stopped_at = time.perf_counter()
        apply_levels(record, samples)
        speech = speech_seconds(samples, vad_model_path())
        apply_speech(record, speech)
        record.outcome = "OK" if speech > 0 else "SILENT"

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
