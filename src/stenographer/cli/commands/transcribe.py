# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer transcribe``: transcribe an audio file."""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import TYPE_CHECKING

from stenographer.cli import _fatal
from stenographer.cli.commands import with_config
from stenographer.constants import SAMPLE_RATE

if TYPE_CHECKING:
    from stenographer.config import Config


@with_config
def cmd_transcribe(args: argparse.Namespace, cfg: Config) -> int:
    from stenographer.transcribe.format import format_transcript

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

    samples = samples.mean(axis=1, dtype="float32")
    samples = _resample_poly(samples, sample_rate, SAMPLE_RATE)

    m = model.Model(cfg.asr)
    try:
        result = m.transcribe(samples)
    finally:
        m.close()

    text = result.text if args.raw else format_transcript(result.text)
    sys.stdout.write(text)
    sys.stdout.write("\n")
    return 0
