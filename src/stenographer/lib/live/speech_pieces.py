# SPDX-License-Identifier: GPL-3.0-or-later
"""Find the pieces of speech in the saved audio of one source with the bundled pyannote model.

The library holds the Python interpreter lock for a long time, and it uses much memory, so the
pass runs in a child process. The app stays live, a skip kills the child, and the memory
returns to the system when the child ends.
"""

from __future__ import annotations

import contextlib
import multiprocessing
import os
import threading
from collections.abc import Callable
from importlib.resources import files
from multiprocessing.connection import Connection
from pathlib import Path

import numpy as np

from stenographer.lib.live.errors import SpeechPassError

_MINIMUM_PIECE_SECONDS = 0.5
_NUM_THREADS = 2
# The library's own clustering. It decides how pieces merge. It is not the limit that
# groups the pieces into speakers. Calibrated for WeSpeaker on six sources of saved sessions.
_CLUSTERING_THRESHOLD = 0.975
_MINIMUM_DURATION_ON = 0.3
_MINIMUM_DURATION_OFF = 0.5
# A skip stops the child within this time.
_POLL_SECONDS = 0.05


def segmentation_model_path() -> Path:
    """Return the path of the bundled model."""
    return Path(str(files("stenographer"))) / "assets" / "models" / "pyannote-segmentation-3-0.onnx"


def run_pass(
    samples: np.ndarray, speaker_model: str, progress: Callable[[float], None]
) -> tuple[tuple[float, float], ...]:
    """Return ``(start, end)`` of each piece of 0.5 s or more, by start. Silence gives no pieces.

    The library's speaker numbers are not used.
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
                model=speaker_model, num_threads=_NUM_THREADS
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=-1, threshold=_CLUSTERING_THRESHOLD
            ),
            min_duration_on=_MINIMUM_DURATION_ON,
            min_duration_off=_MINIMUM_DURATION_OFF,
        )
    )

    def report(done: int, total: int) -> int:
        progress(done / total)
        return 0

    result = diarizer.process(samples, callback=report)
    return tuple(
        (segment.start, segment.end)
        for segment in result.sort_by_start_time()
        if segment.end - segment.start >= _MINIMUM_PIECE_SECONDS
    )


def _end_with_parent() -> None:
    # A parent that is killed runs no exit handlers, so the child ends itself.
    multiprocessing.parent_process().join()
    os._exit(1)


def _child_main(audio: Connection, results: Connection, speaker_model: str) -> None:
    threading.Thread(target=_end_with_parent, daemon=True).start()
    samples = np.frombuffer(audio.recv_bytes(), dtype=np.float32)
    audio.close()
    try:
        pieces = run_pass(samples, speaker_model, lambda done: results.send(("progress", done)))
    except Exception as exc:
        # The type only: a message of the library is not needed in the parent's log.
        results.send(("failed", type(exc).__name__))
        return
    results.send(("pieces", pieces))


def _send_audio(audio: Connection, samples: np.ndarray) -> None:
    # A child that died closed its end. The results pipe tells the parent about it.
    with audio, contextlib.suppress(BrokenPipeError):
        audio.send_bytes(memoryview(samples))


def find_speech_pieces(
    samples: np.ndarray,
    speaker_model: Path,
    *,
    progress: Callable[[float], None],
    should_cancel: Callable[[], bool],
) -> tuple[tuple[float, float], ...] | None:
    """Run the pass on float32 *samples* in a child process and return its pieces.

    Return ``None`` on a cancel. Raise ``SpeechPassError`` if the child fails or dies for
    any reason. No child stays after this returns.
    """
    context = multiprocessing.get_context("spawn")
    audio_read, audio_write = context.Pipe(duplex=False)
    results_read, results_write = context.Pipe(duplex=False)
    process = context.Process(
        target=_child_main,
        args=(audio_read, results_write, str(speaker_model)),
        daemon=True,
    )
    process.start()
    # The parent must hold no write end, or the death of the child shows no end of file.
    audio_read.close()
    results_write.close()
    sender = threading.Thread(target=_send_audio, args=(audio_write, samples), daemon=True)
    sender.start()
    try:
        while not should_cancel():
            if not results_read.poll(_POLL_SECONDS):
                continue
            try:
                kind, value = results_read.recv()
            except EOFError:
                process.join()
                raise SpeechPassError(
                    f"speech pass ended with exit code {process.exitcode}"
                ) from None
            if kind == "pieces":
                return value
            if kind == "failed":
                raise SpeechPassError(f"speech pass failed: {value}")
            progress(value)
        return None
    finally:
        process.kill()
        process.join()
        sender.join()
        results_read.close()
        process.close()
