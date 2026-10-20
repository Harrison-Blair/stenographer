# SPDX-License-Identifier: GPL-3.0-or-later
"""Reprocess saved sessions with the current models and settings."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import soundfile as sf

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
    ) -> None:
        self._store = store
        self._config = config
        self._platform = platform
        self._speaker_tracker_factory = speaker_tracker_factory
        self._worker_factory = worker_factory

    def update_config(self, config: Config) -> None:
        self._config = config

    def rediarize(self, session_id: str) -> str:
        detail = self._store.read(session_id)
        system_lines = [
            line for line in detail.lines if line.source == "system" and line.end > line.start
        ]
        if system_lines:
            model_path = (
                self._platform.data_dir(os.environ, Path.home())
                / "models"
                / "live"
                / LIVE_MODELS[1].filename
            )
            if not model_path.is_file():
                raise FileNotFoundError(f"speaker model is missing: {model_path}")
            tracker = self._speaker_tracker_factory(model_path)
            embeddings = [
                tracker.embed(self._audio_segment(session_id, line)) for line in system_lines
            ]
            relabeled = relabel_system_lines(system_lines, embeddings)
            if relabeled is None:
                raise RuntimeError("speaker relabeling was cancelled")
            lines = list(detail.lines)
            system_indices = [
                index
                for index, line in enumerate(detail.lines)
                if line.source == "system" and line.end > line.start
            ]
            for index, revised in zip(system_indices, relabeled, strict=True):
                lines[index] = revised
        else:
            lines = detail.lines
        return self._store.write_revision(session_id, lines, method="diarization")

    def retranscribe(self, session_id: str) -> str:
        detail = self._store.read(session_id)
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
                text = worker.transcribe(self._audio_segment(session_id, line)).text
                lines.append(replace(line, text=text))
        finally:
            worker.shutdown()
        return self._store.write_revision(session_id, lines, method="re-transcribe")

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
