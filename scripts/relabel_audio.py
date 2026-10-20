# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure live and batch speaker labels on one local audio recording."""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf

from stenographer.lib.audio.resample import _resample_poly
from stenographer.lib.live.models import LIVE_MODELS
from stenographer.lib.live.phrase import Phrase
from stenographer.lib.live.phrase_segmenter import PhraseSegmenter
from stenographer.lib.live.relabel import relabel_system_lines
from stenographer.lib.live.speaker import MINIMUM_SPEECH_DURATION_SECONDS
from stenographer.lib.live.speaker_tracker import SpeakerTracker
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.platform import current_platform

_SAMPLE_RATE = 16000
_BLOCK_SECONDS = 30


def _models() -> tuple[Path, Path]:
    data_dir = current_platform().data_dir(os.environ, Path.home())
    model_dir = data_dir / "models" / "live"
    paths = tuple(model_dir / model.filename for model in LIVE_MODELS)
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing live model {missing[0]}; download live models explicitly before running."
        )
    return paths[0], paths[1]


def run(path: Path, *, baseline: bool = False) -> None:
    vad_model, speaker_model = _models()
    segmenter = PhraseSegmenter("system", vad_model)
    tracker = SpeakerTracker(speaker_model, threshold=0.50, num_threads=2)
    lines: list[TranscriptLine] = []
    embeddings: list[np.ndarray] = []
    short_phrases = 0
    input_frames = 0
    output_frames = 0

    def accept_phrases(phrases: list[Phrase]) -> None:
        nonlocal short_phrases
        for phrase in phrases:
            duration = phrase.end - phrase.start
            if duration < MINIMUM_SPEECH_DURATION_SECONDS:
                short_phrases += 1
            try:
                embedding = tracker.embed(phrase.samples)
            except ValueError:
                continue
            if baseline:
                speaker_id = tracker.assign_embedding(embedding)
            else:
                speaker_id = tracker.assign_embedding(embedding, duration=duration)
            line = TranscriptLine(
                start=phrase.start,
                end=phrase.end,
                wall="",
                source="system",
                speaker_id=speaker_id,
                label=tracker.label(speaker_id),
                text="",
            )
            lines.append(line)
            embeddings.append(embedding.copy())

    with sf.SoundFile(path) as audio:
        input_rate = audio.samplerate
        while True:
            block = audio.read(input_rate * _BLOCK_SECONDS, dtype="float32", always_2d=True)
            if not len(block):
                break
            input_frames += len(block)
            samples = _resample_poly(np.ascontiguousarray(block[:, 0]), input_rate, _SAMPLE_RATE)
            expected_output = input_frames * _SAMPLE_RATE // input_rate
            samples = samples[: expected_output - output_frames]
            output_frames += len(samples)
            accept_phrases(segmenter.accept(samples))

    accept_phrases(segmenter.flush())
    if not baseline:
        lines = list(relabel_system_lines(lines, embeddings, threshold=0.50) or ())

    talk_time: dict[str, float] = defaultdict(float)
    for line in lines:
        talk_time[line.label] += line.end - line.start
    cluster_count = len({line.speaker_id for line in lines})
    print(f"Clusters: {cluster_count}")
    print(f"Labels: {len(talk_time)}")
    for label, seconds in sorted(talk_time.items()):
        print(f"{label}: {seconds:.1f} s")
    print(f"Phrases under {MINIMUM_SPEECH_DURATION_SECONDS:.1f} s: {short_phrases}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="use the original online clustering and skip the batch pass",
    )
    args = parser.parse_args()
    if not args.path.is_file():
        print("stenographer: recording does not exist or is not a file", file=sys.stderr)
        return 2
    try:
        run(args.path, baseline=args.baseline)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"stenographer: could not relabel recording: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
