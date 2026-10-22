# SPDX-License-Identifier: GPL-3.0-or-later
"""Dictation silence: keep only the Silero VAD speech of a capture.

Dictation runs the same VAD as live mode (``PhraseSegmenter``: same model file,
same parameters) before the decode. Each speech region keeps 0.25 s of the audio
before it. A capture with no speech yields an empty buffer, and the caller skips
the decode."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from stenographer.lib.audio.constants import SAMPLE_RATE

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from stenographer.lib.live.phrase_segmenter import PhraseSegmenter

PRE_PAD_SECONDS = 0.25


def keep_speech(
    samples: np.ndarray, regions: Sequence[tuple[int, int]], *, pad_frames: int
) -> np.ndarray:
    """Join each ``(start, end)`` frame region with up to *pad_frames* before it. PURE.

    A pre-pad stops at the capture start and at the end of the previous region,
    so no frame is kept twice.
    """
    pieces = []
    floor = 0
    for start, end in regions:
        pieces.append(samples[max(floor, start - pad_frames) : end])
        floor = end
    if not pieces:
        return np.empty(0, dtype=np.float32)
    return np.concatenate(pieces).astype(np.float32, copy=False)


def dictation_speech(
    samples: np.ndarray,
    vad_model_path: Path | str,
    *,
    segmenter_factory: Callable[[], PhraseSegmenter] | None = None,
) -> np.ndarray:
    """The padded speech of one capture, or an empty buffer when it holds none."""
    from stenographer.lib.transcribe.pipeline import downmix

    if segmenter_factory is None:
        from stenographer.lib.live.phrase_segmenter import PhraseSegmenter

        def segmenter_factory() -> PhraseSegmenter:
            return PhraseSegmenter("mic", vad_model_path)

    mono = np.ascontiguousarray(downmix(samples), dtype=np.float32)
    segmenter = segmenter_factory()
    phrases = [*segmenter.accept(mono), *segmenter.flush()]
    regions = []
    for phrase in phrases:
        start = round(phrase.start * SAMPLE_RATE)
        regions.append((start, start + phrase.samples.size))
    return keep_speech(mono, regions, pad_frames=round(PRE_PAD_SECONDS * SAMPLE_RATE))
