# SPDX-License-Identifier: GPL-3.0-or-later
"""Dictation silence: does the Silero VAD hear speech in a capture?

Dictation runs the same VAD as live mode (``PhraseSegmenter``: same model file,
same parameters, same running gain) over the channel-0 downmix of a capture.
The VAD only decides: a capture with speech is decoded whole, and a capture
with none is not decoded."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from stenographer.lib.audio.constants import SAMPLE_RATE

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from stenographer.lib.live.phrase_segmenter import PhraseSegmenter


def speech_seconds(
    samples: np.ndarray,
    vad_model_path: Path | str,
    *,
    segmenter_factory: Callable[[], PhraseSegmenter] | None = None,
) -> float:
    """The seconds of speech the VAD finds in one capture; 0.0 when it finds none."""
    from stenographer.lib.transcribe.pipeline import downmix

    if segmenter_factory is None:
        from stenographer.lib.live.phrase_segmenter import PhraseSegmenter

        def segmenter_factory() -> PhraseSegmenter:
            return PhraseSegmenter("mic", vad_model_path)

    mono = np.ascontiguousarray(downmix(samples), dtype=np.float32)
    segmenter = segmenter_factory()
    phrases = [*segmenter.accept(mono), *segmenter.flush()]
    return sum(phrase.samples.size for phrase in phrases) / SAMPLE_RATE
