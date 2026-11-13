# SPDX-License-Identifier: GPL-3.0-or-later
"""Reprocess saved sessions and write their audio for playback."""

from __future__ import annotations

import logging
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
from stenographer.lib.logging.pipeline import log_failure
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
    from stenographer.lib.platform.speaker_diarizer import SpeakerDiarizer, SpeakerSegment

log = logging.getLogger(__name__)


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

    @classmethod
    def rediarize_refusal(cls, detail: SessionDetail) -> str | None:
        """Why Re-diarize cannot run on *detail*, or ``None`` when it can."""
        if detail.summary.kind == "file":
            return "Re-diarize is not available for a file session: use Re-transcribe."
        if cls._separated_sources(detail):
            return None
        if any(line.source == "mic" for line in detail.lines):
            return "Nothing to re-diarize: mic lines are You."
        return "Nothing to re-diarize: this recording has no timed lines."

    def rediarize(self, session_id: str) -> str:
        detail = self._store.read(session_id)
        refusal = self.rediarize_refusal(detail)
        if refusal is not None:
            raise ValueError(refusal)
        sources = self._separated_sources(detail)
        diarizer = self._open_diarizer(required=True)
        try:
            found = self._speaker_segments(session_id, detail, sources, diarizer)
        finally:
            diarizer.close()
        worker = self._make_worker()
        try:
            lines = self._relabel_sources(session_id, detail, found, worker)
        finally:
            worker.shutdown()
        return self._store.write_revision(
            session_id, lines, method="diarization", expected_revision=detail.revision
        )

    def retranscribe(self, session_id: str) -> str:
        """Decode every line again; separated sources also get their speakers again by
        the line rule. Without speaker separation, lines keep their speakers."""
        detail = self._store.read(session_id)
        sources = self._separated_sources(detail)
        found: dict[str, tuple[SpeakerSegment, ...]] = {}
        diarizer = self._open_diarizer(required=False) if sources else None
        if diarizer is not None:
            try:
                found = self._speaker_segments(session_id, detail, sources, diarizer)
            except SpeakerDiarizerError as exc:
                # The text is still decoded again; the lines keep their speakers.
                log_failure(log, logging.WARNING, "sessions: speakers_failed", exc, safe=True)
            finally:
                diarizer.close()
        lines = list(detail.lines)
        worker = self._make_worker()
        chunks = None
        try:
            if detail.summary.kind != "file":
                segments = (
                    (index, self._audio_segment(session_id, line))
                    for index, line in enumerate(lines)
                    if line.end > line.start and line.source not in found
                )
            elif not found:
                chunks = self._decode_source(self._store.source_audio(session_id))
                segments = source_segments(chunks, lines)
            else:
                segments = iter(())
            for index, samples in segments:
                lines[index] = replace(lines[index], text=worker.transcribe(samples).text)
            if found:
                detail = replace(detail, lines=tuple(lines))
                lines = self._relabel_sources(session_id, detail, found, worker, decode_all=True)
        finally:
            worker.shutdown()
            if chunks is not None:
                chunks.close()
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

    def _speaker_segments(
        self,
        session_id: str,
        detail: SessionDetail,
        sources: tuple[str, ...],
        diarizer: SpeakerDiarizer,
    ) -> dict[str, tuple[SpeakerSegment, ...]]:
        """Return the speaker segments of each source, from its saved audio."""
        found = {}
        for source in sources:
            if detail.summary.kind == "file":
                chunks = self._decode_source(self._store.source_audio(session_id))
                try:
                    found[source] = diarizer.diarize_file(chunks)
                finally:
                    chunks.close()
            else:
                found[source] = diarizer.diarize_file(
                    self._store.root / session_id / f"{source}.flac"
                )
        return found

    def _relabel_sources(
        self,
        session_id: str,
        detail: SessionDetail,
        found: dict[str, tuple[SpeakerSegment, ...]],
        worker: Worker,
        *,
        decode_all: bool = False,
    ) -> list[TranscriptLine]:
        """Return the session lines with each source of *found* labelled by the line
        rule, in time order."""
        lines = list(detail.lines)
        for source, segments in found.items():
            own = [line for line in lines if line.source == source and line.end > line.start]
            chunks = None
            if detail.summary.kind == "file":
                chunks = self._decode_source(self._store.source_audio(session_id))
                reader = ForwardReader(chunks)
                read = reader.read
            else:
                read = partial(read_saved_audio, self._store.root / session_id / f"{source}.flac")
            try:
                relabeled = relabel_lines(
                    own,
                    segments,
                    SpeakerNames(source),
                    read_audio=read,
                    decode=lambda samples: worker.transcribe(samples).text,
                    decode_all=decode_all,
                )
            finally:
                if chunks is not None:
                    chunks.close()
            owned = {id(line) for line in own}
            others = [line for line in lines if id(line) not in owned]
            lines = sorted([*others, *relabeled], key=lambda line: line.start)
        return lines

    def _make_worker(self) -> Worker:
        return self._worker_factory(
            self._config.asr,
            transport=self._platform.asr_transport(),
        )

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


class ForwardReader:
    """Read intervals of decoded audio chunks in order of start.

    It keeps only the audio from the last start on, so memory stays about one
    interval and one chunk.
    """

    def __init__(self, chunks: Iterator[np.ndarray]) -> None:
        self._chunks = chunks
        self._buffer = np.empty(0, dtype=np.float32)
        self._buffer_start = 0

    def read(self, start: float, end: float) -> np.ndarray:
        first = max(0, int(start * SAMPLE_RATE))
        last = max(first, int(end * SAMPLE_RATE))
        while (
            self._buffer_start + self._buffer.size < last
            and (chunk := next(self._chunks, None)) is not None
        ):
            dropped = min(self._buffer.size, first - self._buffer_start)
            self._buffer = np.concatenate((self._buffer[dropped:], chunk))
            self._buffer_start += dropped
        samples = self._buffer[first - self._buffer_start : last - self._buffer_start]
        if samples.size == 0:
            raise ValueError("file session phrase has no audio")
        return samples


def source_segments(
    chunks: Iterator[np.ndarray], lines: Sequence[TranscriptLine]
) -> Iterator[tuple[int, np.ndarray]]:
    """Yield the index and samples of each timed line in one pass over the decoded chunks.

    The lines must be in order of start, so a later line never needs a dropped sample.
    """
    reader = ForwardReader(chunks)
    for index, line in enumerate(lines):
        if line.end > line.start:
            yield index, reader.read(line.start, line.end)
    # A decode error after the last line still fails the job.
    for _ in chunks:
        pass
