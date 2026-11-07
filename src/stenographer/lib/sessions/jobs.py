# SPDX-License-Identifier: GPL-3.0-or-later
"""Reprocess saved sessions and write their audio for playback."""

from __future__ import annotations

import os
import tempfile
from contextlib import ExitStack
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import soundfile as sf

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.files.media import decode_media
from stenographer.lib.live.models import SPEAKER_MODEL, live_model_dir
from stenographer.lib.live.speaker_tracker import SpeakerTracker
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.live.voice_split import (
    group_and_split,
    read_saved_audio,
    read_saved_source,
    source_segments,
)
from stenographer.lib.sessions import SessionStore
from stenographer.lib.sessions.errors import SessionNotFoundError
from stenographer.lib.sessions.models import SessionDetail
from stenographer.lib.sessions.reader import session_directory, session_metadata
from stenographer.lib.transcribe.worker import Worker

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from stenographer.lib.config.models import Config
    from stenographer.lib.platform.platform import Platform

_LABEL_PREFIXES = {"system": "Speaker", "mic": "Room", "file": "Speaker"}


class SessionJobs:
    """Create transcript revisions from saved audio and write that audio for playback."""

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
        indices = self._separated_lines(detail)
        lines = detail.lines
        if indices:
            tracker = self._make_speaker_tracker()
            worker = self._make_worker()
            try:
                embeddings = {
                    index: tracker.embed(self._audio_segment(session_id, detail.lines[index]))
                    for source_indices in indices.values()
                    for index in source_indices
                }
                lines = self._group_sources(
                    session_id, detail, indices, embeddings, tracker, worker
                )
            finally:
                worker.shutdown()
        return self._store.write_revision(
            session_id, lines, method="diarization", expected_revision=detail.revision
        )

    def retranscribe(self, session_id: str) -> str:
        detail = self._store.read(session_id)
        lines = list(detail.lines)
        chunks = None
        if detail.summary.kind == "file":
            chunks = self._decode_source(self._store.source_audio(session_id))
            segments = source_segments(chunks, lines)
        else:
            segments = (
                (index, self._audio_segment(session_id, line))
                for index, line in enumerate(lines)
                if line.end > line.start
            )
        indices = self._separated_lines(detail)
        separated = {index for source_indices in indices.values() for index in source_indices}
        tracker = self._make_speaker_tracker() if separated else None
        embeddings = {}
        worker = self._make_worker()
        try:
            for index, samples in segments:
                lines[index] = replace(lines[index], text=worker.transcribe(samples).text)
                if index in separated:
                    embeddings[index] = tracker.embed(samples)
            if separated:
                detail = replace(detail, lines=tuple(lines))
                lines = self._group_sources(
                    session_id, detail, indices, embeddings, tracker, worker
                )
        finally:
            worker.shutdown()
            if chunks is not None:
                chunks.close()
        return self._store.write_revision(
            session_id, lines, method="re-transcribe", expected_revision=detail.revision
        )

    @staticmethod
    def _separated_lines(detail: SessionDetail) -> dict[str, list[int]]:
        """Return the timed line indices of each source with speaker separation.

        Mic lines have it only in sessions recorded with mic diarization. A file session
        keeps no record of the job's speaker option, so one speaker there means no separation.
        """
        if detail.summary.kind == "file":
            if len({line.speaker_id for line in detail.lines}) < 2:
                return {}
            sources = ("file",)
        else:
            sources = ("system", "mic") if detail.diarize_mic else ("system",)
        indices = {
            source: [
                index
                for index, line in enumerate(detail.lines)
                if line.source == source and line.end > line.start
            ]
            for source in sources
        }
        return {source: found for source, found in indices.items() if found}

    def _group_sources(
        self,
        session_id: str,
        detail: SessionDetail,
        indices: dict[str, list[int]],
        embeddings: dict[int, np.ndarray],
        tracker: SpeakerTracker,
        worker: Worker,
    ) -> list[TranscriptLine]:
        """Return the session lines with each separated source grouped and split."""
        replacements: dict[int, list[TranscriptLine]] = {}
        for source, source_indices in indices.items():
            grouped = group_and_split(
                [detail.lines[index] for index in source_indices],
                [embeddings[index] for index in source_indices],
                read_source=(
                    partial(self._file_source, session_id)
                    if detail.summary.kind == "file"
                    else partial(
                        read_saved_source, self._store.root / session_id / f"{source}.flac"
                    )
                ),
                speaker_model=self._speaker_model_path(),
                embed=tracker.embed,
                decode=lambda samples: worker.transcribe(samples).text,
                label_prefix=_LABEL_PREFIXES[source],
            )
            for parent, line in zip(grouped.parents, grouped.lines, strict=True):
                replacements.setdefault(source_indices[parent], []).append(line)
        return [
            revised
            for index, line in enumerate(detail.lines)
            for revised in replacements.get(index, (line,))
        ]

    def _make_speaker_tracker(self) -> SpeakerTracker:
        model_path = self._speaker_model_path()
        if not model_path.is_file():
            raise FileNotFoundError(f"speaker model is missing: {model_path}")
        return self._speaker_tracker_factory(model_path)

    def _speaker_model_path(self) -> Path:
        return (
            live_model_dir(self._platform.data_dir(os.environ, Path.home()))
            / SPEAKER_MODEL.filename
        )

    def _make_worker(self) -> Worker:
        return self._worker_factory(
            self._config.asr,
            transport=self._platform.asr_transport(),
        )

    def _file_source(self, session_id: str) -> np.ndarray:
        return np.concatenate(list(self._decode_source(self._store.source_audio(session_id))))

    def _decode_source(self, path: Path) -> Generator[np.ndarray]:
        if self._media_decoder is not None:
            return self._media_decoder(path)
        return decode_media(path, self._platform.ffmpeg_decoder())

    def _audio_segment(self, session_id: str, line: TranscriptLine) -> np.ndarray:
        if line.source not in {"mic", "system"}:
            raise ValueError(f"unsupported audio source: {line.source}")
        path = self._store.root / session_id / f"{line.source}.flac"
        return read_saved_audio(path, line.start, line.end)

    def write_play_audio(self, session_id: str) -> Path:
        """Write the audio of a session to a private temporary WAV file."""
        directory = session_directory(self._store.root, session_id)
        if directory is None:
            raise SessionNotFoundError(f"session not found: {session_id}")
        if session_metadata(directory).get("kind") == "file":
            return self._write_source_audio(self._store.source_audio(session_id))
        return self._write_mixed_audio(directory, session_id)

    def _write_source_audio(self, source: Path) -> Path:
        """Decode the copied source of a file session into a private temporary WAV file."""
        blocks = self._decode_source(source)
        fd, name = tempfile.mkstemp(prefix="stenographer-session-", suffix=".wav")
        os.close(fd)
        path = Path(name)
        try:
            with sf.SoundFile(path, "w", SAMPLE_RATE, 1, format="WAV", subtype="PCM_16") as output:
                for block in blocks:
                    output.write(np.clip(block, -1.0, 1.0))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            blocks.close()
        return path

    def _write_mixed_audio(self, directory: Path, session_id: str) -> Path:
        paths = [directory / "mic.flac", directory / "system.flac"]
        with ExitStack() as stack:
            streams = [stack.enter_context(sf.SoundFile(path)) for path in paths if path.is_file()]
            if not streams:
                raise FileNotFoundError(f"session has no audio: {session_id}")
            sample_rate = streams[0].samplerate
            if any(stream.samplerate != sample_rate for stream in streams):
                raise ValueError("session audio sources use different sample rates")
            total_frames = max(stream.frames for stream in streams)
            fd, name = tempfile.mkstemp(prefix="stenographer-session-", suffix=".wav")
            os.close(fd)
            mixed_path = Path(name)
            try:
                with sf.SoundFile(
                    mixed_path,
                    mode="w",
                    samplerate=sample_rate,
                    channels=1,
                    format="WAV",
                    subtype="PCM_16",
                ) as output:
                    for start in range(0, total_frames, 65_536):
                        count = min(65_536, total_frames - start)
                        mixed = np.zeros(count, dtype=np.float32)
                        for stream in streams:
                            available = min(count, max(0, stream.frames - start))
                            if available:
                                stream.seek(start)
                                samples = stream.read(available, dtype="float32", always_2d=True)
                                mixed[: len(samples)] += np.mean(samples, axis=1, dtype=np.float32)
                        output.write(np.clip(mixed, -1.0, 1.0))
            except Exception:
                mixed_path.unlink(missing_ok=True)
                raise
        return mixed_path
