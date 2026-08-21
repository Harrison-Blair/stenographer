# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer transcribe``: transcribe an audio file."""

from __future__ import annotations

import argparse
import pathlib
import sys

from stenographer.cli import _fatal


def cmd_transcribe(args: argparse.Namespace) -> int:
    from stenographer import config
    from stenographer.transcribe.format import format_transcript

    try:
        cfg = config.load_or_default()
    except config.ConfigError as exc:
        return _fatal(str(exc))

    path = pathlib.Path(args.file)
    if not path.exists():
        print(f"stenographer: file not found: {path}", file=sys.stderr)
        return 2

    from stenographer.transcribe import model

    if not model.is_model_cached(cfg.asr.model):
        return _fatal("ASR model not found; run `stenographer model download`")

    import soundfile

    samples, sample_rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    if sample_rate != 16000:
        import logging

        logging.getLogger(__name__).warning(
            "transcribe: file sample rate is %d, not 16000 (pass-through)", sample_rate
        )

    m = model.Model(cfg.asr)
    try:
        result = m.transcribe(samples)
    finally:
        m.close()

    text = result.text if args.raw else format_transcript(result.text)
    sys.stdout.write(text)
    sys.stdout.write("\n")
    return 0
