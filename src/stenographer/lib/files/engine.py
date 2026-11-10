# SPDX-License-Identifier: GPL-3.0-or-later
"""Serial background queue for file transcription jobs."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING

import numpy as np

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.files.job import FileJob
from stenographer.lib.files.media import MediaInfo, inspect_media, iter_media_audio
from stenographer.lib.files.models import FileJobOptions
from stenographer.lib.live.models import vad_model_path
from stenographer.lib.live.phrase_segmenter import PhraseSegmenter
from stenographer.lib.live.speaker_lines import SpeakerNames, speaker_pieces
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.sessions.errors import SessionWriteCancelledError, StaleRevisionError
from stenographer.lib.sessions.store import SessionStore
from stenographer.lib.transcribe.worker import Worker

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config
    from stenographer.lib.platform.platform import Platform
    from stenographer.lib.platform.speaker_diarizer import SpeakerSegment
    from stenographer.lib.refine.ollama_refiner import OllamaRefiner

log = logging.getLogger(__name__)
_STOP = object()
_VAD_WINDOW_FRAMES = 512
_SOURCE_ORDER = {"mic": 0, "system": 1}
# Shares of the progress of a job with speaker separation.
_DIARIZE_SHARE = 20
_TRANSCRIBED = 95


class FilesEngine:
    """Queue jobs in submission order and run one at a time in a background thread."""

    def __init__(
        self,
        config: Config,
        *,
        platform: Platform,
        segmenter_factory: Callable[[], object] | None = None,
        refiner_factory: Callable[[Config], OllamaRefiner | None] | None = None,
        session_store: SessionStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._data_dir = platform.data_dir(os.environ, Path.home())
        self._decoder = platform.ffmpeg_decoder()
        self._worker = Worker(config.asr, transport=platform.asr_transport())
        self._platform = platform
        vad_path = vad_model_path()
        self._segmenter_factory = segmenter_factory or (lambda: PhraseSegmenter("system", vad_path))
        self._refiner_factory = refiner_factory
        self._store = (
            session_store
            if session_store is not None
            else SessionStore(self._data_dir / "sessions")
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._queue: Queue[FileJob | object] = Queue()
        self._jobs: list[FileJob] = []
        self._active: FileJob | None = None
        self._lock = threading.RLock()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run_queue,
            name="stenographer-files-engine",
            daemon=True,
        )
        self._thread.start()

    @property
    def jobs(self) -> tuple[FileJob, ...]:
        """Return all jobs in submission order."""
        with self._lock:
            return tuple(self._jobs)

    @property
    def active_job(self) -> FileJob | None:
        with self._lock:
            return self._active

    @property
    def process_ids(self) -> tuple[int, ...]:
        """Return the ASR worker child of this engine, if it runs."""
        return self._worker.process_ids

    @property
    def idle_unload_deadline(self) -> float | None:
        """Return the monotonic time of the idle unload of its worker, or ``None``."""
        return self._worker.idle_unload_deadline

    def submit(
        self,
        path: str | Path,
        *,
        diarize: bool = True,
        speaker_count: int | None = None,
        refine: bool = False,
    ) -> FileJob:
        """Queue one file without blocking on media inspection or inference."""
        options = FileJobOptions(
            path=Path(path),
            diarize=diarize,
            speaker_count=speaker_count,
            refine=refine,
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("Files engine is closed")
            job = FileJob(f"file-{len(self._jobs) + 1}", options, None)
            self._jobs.append(job)
            self._queue.put(job)
        log.info(fmt_event("files", "job_queued", job_id=job.id))
        return job

    def close(self) -> None:
        """Cancel queued work, stop the active job at its next boundary, and reap ASR."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            jobs = tuple(self._jobs)
            active = self._active
            self._queue.put(_STOP)
        for job in jobs:
            if job is not active:
                job.cancel()
        if active is not None:
            active.cancel()
        self._worker.shutdown()
        self._thread.join()

    def _run_queue(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                assert isinstance(item, FileJob)
                with self._lock:
                    self._active = item
                self._run_one(item)
            finally:
                if item is not _STOP:
                    with self._lock:
                        self._active = None
                self._queue.task_done()

    def _run_one(self, job: FileJob) -> None:
        if job.cancel_requested:
            job._cancelled(())
            return
        if not job.options.path.is_file():
            job._fail("file not found")
            return
        try:
            media = inspect_media(job.options.path, self._decoder)
            job._set_media_info(media)
            if job.cancel_requested:
                job._cancelled(())
                return
            if media.needs_ffmpeg:
                job._needs_ffmpeg()
                return
            if not job._start():
                return
            started_at = self._clock()
            target = self._store.revision_target(job.options.path)
            segmenter = self._segmenter_factory()
            refiner = self._make_refiner() if job.options.refine else None
            segments, speaker_pass_failed = None, False
            if job.options.diarize:
                segments, speaker_pass_failed = self._diarize(job, media)
                if job.cancel_requested:
                    job._cancelled(())
                    return
            lines = self._transcribe(job, media, segmenter, segments, refiner)
            if job.cancel_requested:
                job._cancelled(tuple(lines))
                return
            job._update("save", _TRANSCRIBED, tuple(lines))
            if target is None:
                session_id = self._store.create_file_session(
                    job.options.path,
                    started_at=started_at,
                    duration_seconds=media.duration_seconds
                    or max((line.end for line in lines), default=0.0),
                    lines=lines,
                    should_cancel=lambda: job.cancel_requested,
                    speaker_pass_failed=speaker_pass_failed,
                )
            else:
                session_id, source = target
                lines = self._write_revision(
                    job,
                    session_id,
                    source,
                    lines,
                    # A failed pass reads as a recording does after a failed end pass.
                    method="live" if speaker_pass_failed else "file-transcribe",
                )
            job._complete(session_id, tuple(lines))
        except SessionWriteCancelledError:
            job._cancelled(job.progress.completed_lines)
        except StaleRevisionError:
            job._fail("session changed during this job; nothing was saved")
        except Exception as exc:
            if job.cancel_requested:
                job._cancelled(job.progress.completed_lines)
                return
            job._fail(f"file job failed: {type(exc).__name__}")
            log_failure(log, logging.ERROR, "files: job_failed", exc, safe=False, job_id=job.id)

    def _transcribe(
        self,
        job: FileJob,
        media: MediaInfo,
        segmenter,
        segments: tuple[SpeakerSegment, ...] | None,
        refiner: OllamaRefiner | None,
    ) -> list[TranscriptLine]:
        """Cut the file at pauses and, with *segments*, where the speaker changes, and
        decode each part once."""
        lines: list[TranscriptLine] = []
        names = SpeakerNames("file")
        duration = media.duration_seconds or 0.0
        furthest = 0.0
        first_percent = _DIARIZE_SHARE if segments is not None else 0
        span = _TRANSCRIBED - first_percent

        def report_position(seconds: float) -> None:
            # A phrase can end behind the audio already read, so progress keeps its maximum.
            nonlocal furthest
            furthest = max(furthest, seconds)
            done = min(duration, furthest) / duration if duration > 0 else 0
            job._update("transcribe", first_percent + round(span * done), tuple(lines))

        def transcribe_phrases(phrases) -> bool:
            for phrase in phrases:
                pieces = speaker_pieces(phrase.start, phrase.end, segments or ())
                for piece in pieces:
                    if job.cancel_requested:
                        return False
                    first = round((piece.start - phrase.start) * SAMPLE_RATE)
                    last = round((piece.end - phrase.start) * SAMPLE_RATE)
                    if last <= first:
                        continue
                    text = self._worker.transcribe(phrase.samples[first:last]).text.strip()
                    if not text:
                        continue
                    speaker_id, label = names.speaker(piece.speaker)
                    if refiner is not None and refiner.will_refine(text):
                        text = refiner.refine(text, cancelled=lambda: job.cancel_requested)
                    lines.append(
                        TranscriptLine(
                            start=piece.start,
                            end=piece.end,
                            wall="",
                            source="file",
                            speaker_id=speaker_id,
                            label=label,
                            text=text,
                        )
                    )
                report_position(phrase.end)
            return True

        blocks = iter_media_audio(job.options.path, media, self._decoder)
        pending = np.empty(0, dtype=np.float32)
        accepted_frames = 0
        try:
            for block in blocks:
                if job.cancel_requested:
                    break
                if pending.size:
                    block = np.concatenate((pending, block))
                aligned_size = block.size - block.size % _VAD_WINDOW_FRAMES
                pending = block[aligned_size:].copy()
                if aligned_size and not transcribe_phrases(segmenter.accept(block[:aligned_size])):
                    break
                accepted_frames += aligned_size
                report_position(accepted_frames / SAMPLE_RATE)
            if not job.cancel_requested and pending.size:
                transcribe_phrases(segmenter.accept(pending))
            if not job.cancel_requested:
                transcribe_phrases(segmenter.flush())
        finally:
            blocks.close()
        job._update("transcribe", _TRANSCRIBED, tuple(lines))
        return lines

    def _diarize(
        self, job: FileJob, media: MediaInfo
    ) -> tuple[tuple[SpeakerSegment, ...] | None, bool]:
        """Return the speaker segments of the file, and whether the speaker pass failed.

        A failed or unavailable pass gives no segments: the lines get one speaker.
        """
        diarizer = self._platform.speaker_diarizer()
        try:
            reason = diarizer.unavailable_reason()
            if reason is not None:
                log.warning(fmt_event("files", "speakers_unavailable", reason=reason))
                return None, True
            blocks = iter_media_audio(job.options.path, media, self._decoder)
            try:
                samples = np.concatenate(list(blocks))
            finally:
                blocks.close()
            segments = diarizer.diarize_file(
                samples,
                progress=lambda done: job._update("diarize", round(_DIARIZE_SHARE * done), ()),
                should_cancel=lambda: job.cancel_requested,
            )
        except Exception as exc:
            if job.cancel_requested:
                return None, False
            log_failure(log, logging.WARNING, "files: speaker_pass_failed", exc, safe=True)
            return None, True
        finally:
            diarizer.close()
        return segments, False

    def _make_refiner(self) -> OllamaRefiner | None:
        if self._refiner_factory is not None:
            return self._refiner_factory(self._config)
        from stenographer.lib.refine.factory import build_refiner

        return build_refiner(
            self._config.refine,
            idle_unload_seconds=self._config.asr.idle_unload_seconds,
            enabled=True,
        )

    def _write_revision(
        self,
        job: FileJob,
        session_id: str,
        source: str,
        lines: list[TranscriptLine],
        *,
        method: str,
    ) -> list[TranscriptLine]:
        """Save new lines of one source as a revision of the session that holds it."""
        detail = self._store.read(session_id)
        revision_name = self._store.next_revision_name(session_id)
        revised = list(lines)
        if source != "file":
            number = revision_name.removeprefix("transcript.r").removesuffix(".jsonl")
            prefix = "Room" if source == "mic" else "Speaker"
            speakers: dict[str, int] = {}
            new_lines = []
            for line in lines:
                index = speakers.setdefault(line.speaker_id, len(speakers) + 1)
                if not job.options.diarize:
                    index = 1
                    label = "You" if source == "mic" else "Speaker 1"
                else:
                    label = f"{prefix} {index}"
                new_lines.append(
                    replace(
                        line,
                        source=source,
                        speaker_id=f"{source}-file-r{number}-{index}",
                        label=label,
                    )
                )
            combined = [*new_lines, *(line for line in detail.lines if line.source != source)]
            ordered = sorted(
                enumerate(combined),
                key=lambda item: (item[1].start, _SOURCE_ORDER.get(item[1].source, 2), item[0]),
            )
            revised = [line for _, line in ordered]
        self._store.write_revision(
            session_id,
            revised,
            method=method,
            expected_revision=detail.revision,
            revision_name=revision_name,
            should_cancel=lambda: job.cancel_requested,
        )
        return revised
