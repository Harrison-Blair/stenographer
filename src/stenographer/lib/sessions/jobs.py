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
from stenographer.lib.live.speaker_lines import SpeakerNames, read_saved_audio, relabel_lines
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.platform.errors import SpeakerDiarizerError
from stenographer.lib.sessions import SessionStore
from stenographer.lib.sessions.errors import SessionNotFoundError
from stenographer.lib.sessions.models import SessionDetail
from stenographer.lib.sessions.reader import session_directory, session_metadata
from stenographer.lib.transcribe.worker import Worker

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator, Sequence

    from stenographer.lib.config.models import Config
    from stenographer.lib.platform.platform import Platform
    from stenographer.lib.platform.speaker_diarizer import SpeakerDiarizer


class SessionJobs:
    """Create transcript revisions from saved audio and write that audio for playback."""

    def __init__(
        self,
        store: SessionStore,
        config: Config,
        platform: Platform,
        *,
        worker_factory: Callable[..., Worker] = Worker,
        media_decoder: Callable[[Path], Generator[np.ndarray]] | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._platform = platform
        self._worker_factory = worker_factory
        self._media_decoder = media_decoder

    def update_config(self, config: Config) -> None:
        self._config = config

    def rediarize(self, session_id: str) -> str:
        detail = self._store.read(session_id)
        if detail.summary.kind == "file":
            raise ValueError("re-diarize is not available for a file session; use Re-transcribe")
        sources = self._separated_sources(detail)
        lines = list(detail.lines)
        if sources:
            diarizer = self._open_diarizer(required=True)
            worker = self._make_worker()
            try:
                lines = self._relabel_sources(session_id, detail, sources, diarizer, worker)
            finally:
                worker.shutdown()
                diarizer.close()
        return self._store.write_revision(
            session_id, lines, method="diarization", expected_revision=detail.revision
        )

    def retranscribe(self, session_id: str) -> str:
        """Decode every line again; separated sources also get their speakers again by
        the line rule. Without speaker separation, lines keep their speakers."""
        detail = self._store.read(session_id)
        sources = self._separated_sources(detail)
        diarizer = self._open_diarizer(required=False) if sources else None
        relabel = sources if diarizer is not None else ()
        lines = list(detail.lines)
        worker = self._make_worker()
        chunks = None
        try:
            if detail.summary.kind != "file":
                segments = (
                    (index, self._audio_segment(session_id, line))
                    for index, line in enumerate(lines)
                    if line.end > line.start and line.source not in relabel
                )
            elif not relabel:
                chunks = self._decode_source(self._store.source_audio(session_id))
                segments = source_segments(chunks, lines)
            else:
                segments = iter(())
            for index, samples in segments:
                lines[index] = replace(lines[index], text=worker.transcribe(samples).text)
            if relabel:
                detail = replace(detail, lines=tuple(lines))
                lines = self._relabel_sources(
                    session_id, detail, relabel, diarizer, worker, decode_all=True
                )
        finally:
            worker.shutdown()
            if chunks is not None:
                chunks.close()
            if diarizer is not None:
                diarizer.close()
        return self._store.write_revision(
            session_id, lines, method="re-transcribe", expected_revision=detail.revision
        )

    @staticmethod
    def _separated_sources(detail: SessionDetail) -> tuple[str, ...]:
        """Return the sources with speaker separation that have timed lines.

        Mic lines have it only in sessions recorded with mic diarization. A file session
        has the job's speaker option; an older one without that record had separation
        when it has two speakers or its speaker pass failed.
        """
        if detail.summary.kind == "file":
            separated = detail.diarize
            if separated is None:
                separated = (
                    len({line.speaker_id for line in detail.lines}) >= 2
                    or detail.summary.speaker_pass_failed
                )
            if not separated:
                return ()
            sources = ("file",)
        else:
            sources = ("system", "mic") if detail.diarize_mic else ("system",)
        return tuple(
            source
            for source in sources
            if any(line.source == source and line.end > line.start for line in detail.lines)
        )

    def _open_diarizer(self, *, required: bool) -> SpeakerDiarizer | None:
        diarizer = self._platform.speaker_diarizer()
        reason = diarizer.unavailable_reason()
        if reason is None:
            return diarizer
        if required:
            raise SpeakerDiarizerError(reason)
        return None

    def _relabel_sources(
        self,
        session_id: str,
        detail: SessionDetail,
        sources: tuple[str, ...],
        diarizer: SpeakerDiarizer,
        worker: Worker,
        *,
        decode_all: bool = False,
    ) -> list[TranscriptLine]:
        """Return the session lines with each separated source labelled from its saved
        audio by the line rule, in time order."""
        lines = list(detail.lines)
        for source in sources:
            if detail.summary.kind == "file":
                samples = self._file_samples(session_id)
                segments = diarizer.diarize_file(samples)

                def read(start: float, end: float, samples=samples) -> np.ndarray:
                    return samples[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)]
            else:
                path = self._store.root / session_id / f"{source}.flac"
                segments = diarizer.diarize_file(path)
                read = partial(read_saved_audio, path)
            own = [line for line in lines if line.source == source and line.end > line.start]
            relabeled = relabel_lines(
                own,
                segments,
                SpeakerNames(source),
                read_audio=read,
                decode=lambda samples: worker.transcribe(samples).text,
                decode_all=decode_all,
            )
            owned = {id(line) for line in own}
            others = [line for line in lines if id(line) not in owned]
            lines = sorted([*others, *relabeled], key=lambda line: line.start)
        return lines

    def _make_worker(self) -> Worker:
        return self._worker_factory(
            self._config.asr,
            transport=self._platform.asr_transport(),
        )

    def _file_samples(self, session_id: str) -> np.ndarray:
        chunks = self._decode_source(self._store.source_audio(session_id))
        try:
            return np.concatenate(list(chunks))
        finally:
            chunks.close()

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


def source_segments(
    chunks: Iterator[np.ndarray], lines: Sequence[TranscriptLine]
) -> Iterator[tuple[int, np.ndarray]]:
    """Yield the index and samples of each timed line in one pass over the decoded chunks.

    The lines must be in order of start, so a later line never needs a dropped sample.
    """
    buffer = np.empty(0, dtype=np.float32)
    buffer_start = 0
    for index, line in enumerate(lines):
        if line.end <= line.start:
            continue
        start = max(0, int(line.start * SAMPLE_RATE))
        end = max(start, int(line.end * SAMPLE_RATE))
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
