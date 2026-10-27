# SPDX-License-Identifier: GPL-3.0-or-later
"""Reprocess saved sessions with the current models and settings."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import soundfile as sf

from stenographer.lib.files.media import DecodedAudio, decode_media, inspect_media
from stenographer.lib.live.models import LIVE_MODELS
from stenographer.lib.live.relabel import relabel_system_lines
from stenographer.lib.live.speaker_tracker import SpeakerTracker
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions import SessionStore
from stenographer.lib.transcribe.worker import Worker

if TYPE_CHECKING:
    from collections.abc import Callable

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
        media_decoder: Callable[[Path], DecodedAudio] | None = None,
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
                self._platform.data_dir(os.environ, Path.home())
                / "models"
                / "live"
                / LIVE_MODELS[1].filename
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
                if relabeled is None:
                    raise RuntimeError("speaker relabeling was cancelled")
                for index, revised in zip(source_indices, relabeled, strict=True):
                    lines[index] = revised
        return self._store.write_revision(
            session_id, lines, method="diarization", expected_revision=detail.revision
        )

    def retranscribe(self, session_id: str) -> str:
        detail = self._store.read(session_id)
        source_audio = None
        if detail.summary.kind == "file":
            source_audio = self._decode_source(self._store.source_audio(session_id))
        worker = self._worker_factory(
            self._config.asr,
            transport=self._platform.asr_transport(),
        )
        try:
            lines = []
            for line in detail.lines:
                if line.end <= line.start:
                    lines.append(line)
                    continue
                samples = (
                    self._audio_segment(session_id, line)
                    if source_audio is None
                    else self._source_segment(source_audio, line)
                )
                lines.append(replace(line, text=worker.transcribe(samples).text))
        finally:
            worker.shutdown()
        return self._store.write_revision(
            session_id, lines, method="re-transcribe", expected_revision=detail.revision
        )

    def _decode_source(self, path: Path) -> DecodedAudio:
        if self._media_decoder is not None:
            return self._media_decoder(path)
        decoder = self._platform.ffmpeg_decoder()
        return decode_media(path, inspect_media(path, decoder), decoder)

    @staticmethod
    def _source_segment(audio: DecodedAudio, line: TranscriptLine) -> np.ndarray:
        start = min(audio.samples.size, max(0, int(line.start * audio.sample_rate)))
        end = min(audio.samples.size, max(start, int(line.end * audio.sample_rate)))
        if end == start:
            raise ValueError("file session phrase has no audio")
        return np.ascontiguousarray(audio.samples[start:end], dtype=np.float32)

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
