# SPDX-License-Identifier: GPL-3.0-or-later
"""Find the pieces of speech in the saved audio of one source with the bundled pyannote model."""

from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

import numpy as np

from stenographer.lib.live.errors import PassCancelledError

_MINIMUM_PIECE_SECONDS = 0.5
_NUM_THREADS = 2
# The library's own clustering, tested with these settings. It decides how pieces merge.
# It is not the limit that groups the pieces into speakers.
_CLUSTERING_THRESHOLD = 0.9
_MINIMUM_DURATION_ON = 0.3
_MINIMUM_DURATION_OFF = 0.5


def segmentation_model_path() -> Path:
    """Return the path of the bundled model."""
    return Path(str(files("stenographer"))) / "assets" / "models" / "pyannote-segmentation-3-0.onnx"


def find_speech_pieces(
    samples: np.ndarray,
    speaker_model: Path,
    *,
    progress: Callable[[float], None],
    should_cancel: Callable[[], bool],
) -> tuple[tuple[float, float], ...] | None:
    """Return ``(start, end)`` of each piece of 0.5 s or more, by start.

    The library's speaker numbers are not used. Silence gives no pieces. Return ``None`` on
    a cancel.
    """
    import sherpa_onnx

    pyannote = sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
        model=str(segmentation_model_path())
    )
    diarizer = sherpa_onnx.OfflineSpeakerDiarization(
        sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=pyannote, num_threads=_NUM_THREADS
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(speaker_model), num_threads=_NUM_THREADS
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=-1, threshold=_CLUSTERING_THRESHOLD
            ),
            min_duration_on=_MINIMUM_DURATION_ON,
            min_duration_off=_MINIMUM_DURATION_OFF,
        )
    )

    def report(done: int, total: int) -> int:
        if should_cancel():
            raise PassCancelledError
        progress(done / total)
        return 0

    try:
        result = diarizer.process(samples, callback=report)
    except PassCancelledError:
        return None
    return tuple(
        (segment.start, segment.end)
        for segment in result.sort_by_start_time()
        if segment.end - segment.start >= _MINIMUM_PIECE_SECONDS
    )
