# SPDX-License-Identifier: GPL-3.0-or-later
"""Reprocess saved sessions with the current models and settings."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import soundfile as sf

from stenographer.lib.files.media import inspect_media, iter_media_audio
from stenographer.lib.live.models import SPEAKER_MODEL, live_model_dir
from stenographer.lib.live.relabel import relabel_system_lines
from stenographer.lib.live.speaker_tracker import SpeakerTracker
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions import SessionStore
from stenographer.lib.transcribe.worker import Worker

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator, Sequence

    from stenographer.lib.config.models import Config
    from stenographer.lib.platform.platform import Platform

_SAMPLE_RATE = 16000


class SessionJobs:
    """Create transcript revisions from the saved audio and phrase intervals."""

    def __init__(
        self,
        store: SessionStore,
        config: Config,
        platform: Platform,
        *,
        speaker_tracker_factory: Callable[..., SpeakerTracker] = SpeakerTracker,
        worker_factory: Callable[..., Worker] = Worker,
        media_decoder: Callable[[Path], Generator[np.ndarray]] | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._platform = platform
        self._speaker_tracker_factory = speaker_tracker_factory
        self._worker_factory = worker_factory
        self._media_decoder = media_decoder

    def update_config(self, config: Config) -> None:
        self._config = config

    def rediarize(self, session_id: str) -> str:
        detail = self._store.read(session_id)
        if detail.summary.kind == "file":
            raise ValueError("re-diarize is not available for a file session; use Re-transcribe")
        # Mic lines are relabeled only in sessions recorded with mic diarization.
        prefixes = {"system": "Speaker", **({"mic": "Room"} if detail.diarize_mic else {})}
        indices = {
            source: [
                index
                for index, line in enumerate(detail.lines)
                if line.source == source and line.end > line.start
            ]
            for source in prefixes
        }
        lines = list(detail.lines)
        if any(indices.values()):
            model_path = (
                live_model_dir(self._platform.data_dir(os.environ, Path.home()))
                / SPEAKER_MODEL.filename
            )
            if not model_path.is_file():
                raise FileNotFoundError(f"speaker model is missing: {model_path}")
            tracker = self._speaker_tracker_factory(model_path)
            for source, source_indices in indices.items():
                if not source_indices:
                    continue
                source_lines = [detail.lines[index] for index in source_indices]
                embeddings = [
                    tracker.embed(self._audio_segment(session_id, line)) for line in source_lines
                ]
                relabeled = relabel_system_lines(
                    source_lines, embeddings, label_prefix=prefixes[source]
                )
                for index, revised in zip(source_indices, relabeled, strict=True):
                    lines[index] = revised
        return self._store.write_revision(
            session_id, lines, method="diarization", expected_revision=detail.revision
        )

    def retranscribe(self, session_id: str) -> str:
        detail = self._store.read(session_id)
        lines = list(detail.lines)
        chunks = None
        if detail.summary.kind == "file":
            chunks = self._decode_source(self._store.source_audio(session_id))
            segments = self._source_segments(chunks, lines)
        else:
            segments = (
                (index, self._audio_segment(session_id, line))
                for index, line in enumerate(lines)
                if line.end > line.start
            )
        worker = self._worker_factory(
            self._config.asr,
            transport=self._platform.asr_transport(),
        )
        try:
            for index, samples in segments:
                lines[index] = replace(lines[index], text=worker.transcribe(samples).text)
        finally:
            worker.shutdown()
            if chunks is not None:
                chunks.close()
        return self._store.write_revision(
            session_id, lines, method="re-transcribe", expected_revision=detail.revision
        )

    def _decode_source(self, path: Path) -> Generator[np.ndarray]:
        if self._media_decoder is not None:
            return self._media_decoder(path)
        decoder = self._platform.ffmpeg_decoder()
        return iter_media_audio(path, inspect_media(path, decoder), decoder)

    @staticmethod
    def _source_segments(
        chunks: Iterator[np.ndarray], lines: Sequence[TranscriptLine]
    ) -> Iterator[tuple[int, np.ndarray]]:
        """Yield the index and samples of each timed line in one pass over the decoded chunks.

        The session reader orders lines by start, so a later line never needs a dropped sample.
        """
        buffer = np.empty(0, dtype=np.float32)
        buffer_start = 0
        for index, line in enumerate(lines):
            if line.end <= line.start:
                continue
            start = max(0, int(line.start * _SAMPLE_RATE))
            end = max(start, int(line.end * _SAMPLE_RATE))
            while buffer_start + buffer.size < end and (chunk := next(chunks, None)) is not None:
                dropped = min(buffer.size, start - buffer_start)
                buffer = np.concatenate((buffer[dropped:], chunk))
                buffer_start += dropped
            samples = buffer[start - buffer_start : end - buffer_start]
            if samples.size == 0:
                raise ValueError("file session phrase has no audio")
            yield index, samples
        # A decode error after the last line still fails the job.
        for _ in chunks:
            pass

    def _audio_segment(self, session_id: str, line: TranscriptLine) -> np.ndarray:
        if line.source not in {"mic", "system"}:
            raise ValueError(f"unsupported audio source: {line.source}")
        path = self._store.root / session_id / f"{line.source}.flac"
        with sf.SoundFile(path) as audio:
            if audio.samplerate != _SAMPLE_RATE:
                raise ValueError(f"session audio must use {_SAMPLE_RATE} Hz: {path}")
            start = min(audio.frames, max(0, int(line.start * audio.samplerate)))
            end = min(audio.frames, max(start, int(line.end * audio.samplerate)))
            audio.seek(start)
            samples = audio.read(end - start, dtype="float32", always_2d=True)
        if len(samples) == 0:
            raise ValueError(f"session phrase has no audio: {path}")
        return np.ascontiguousarray(np.mean(samples, axis=1, dtype=np.float32))
