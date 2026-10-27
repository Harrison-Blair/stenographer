# SPDX-License-Identifier: GPL-3.0-or-later
"""Serial background queue for file transcription jobs."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING

import numpy as np

from stenographer.lib.files.job import FileJob
from stenographer.lib.files.media import MediaInfo, inspect_media, iter_media_audio
from stenographer.lib.files.models import FileJobOptions
from stenographer.lib.live.models import LIVE_MODELS
from stenographer.lib.live.phrase_segmenter import PhraseSegmenter
from stenographer.lib.live.relabel import relabel_system_lines
from stenographer.lib.live.speaker_tracker import SpeakerTracker
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.platform import current_platform
from stenographer.lib.sessions.errors import SessionWriteCancelledError, StaleRevisionError
from stenographer.lib.sessions.store import SessionStore
from stenographer.lib.transcribe.worker import Worker

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config
    from stenographer.lib.platform.asr_transport import AsrTransport
    from stenographer.lib.platform.ffmpeg_decoder import FfmpegDecoder
    from stenographer.lib.platform.platform import Platform
    from stenographer.lib.refine.text_refiner import TextRefiner

log = logging.getLogger(__name__)
_STOP = object()
_VAD_WINDOW_FRAMES = 512
_SOURCE_ORDER = {"mic": 0, "system": 1}


class FilesEngine:
    """Queue jobs in submission order and run one at a time in a background thread."""

    def __init__(
        self,
        config: Config,
        *,
        data_dir: str | Path | None = None,
        decoder: FfmpegDecoder | None = None,
        transport: AsrTransport | None = None,
        platform: Platform | None = None,
        segmenter_factory: Callable[[], object] | None = None,
        speaker_tracker_factory: Callable[[], object] | None = None,
        refiner_factory: Callable[[Config], TextRefiner] | None = None,
        session_store: SessionStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if platform is None and (data_dir is None or decoder is None or transport is None):
            platform = current_platform()
        self._config = config
        self._data_dir = (
            Path(data_dir).expanduser()
            if data_dir is not None
            else platform.data_dir(os.environ, Path.home())
        )
        self._decoder = decoder if decoder is not None else platform.ffmpeg_decoder()
        self._worker = Worker(
            config.asr,
            transport=transport if transport is not None else platform.asr_transport(),
        )
        live_model_dir = self._data_dir / "models" / "live"
        vad_path = live_model_dir / LIVE_MODELS[0].filename
        speaker_path = live_model_dir / LIVE_MODELS[1].filename
        self._segmenter_factory = segmenter_factory or (lambda: PhraseSegmenter("system", vad_path))
        self._speaker_tracker_factory = speaker_tracker_factory or (
            lambda: SpeakerTracker(speaker_path)
        )
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
            lines, embeddings = self._transcribe(job, media)
            if job.cancel_requested:
                job._cancelled(tuple(lines))
                return
            if job.options.diarize:
                lines = self._diarize(job, lines, embeddings)
                if job.cancel_requested:
                    job._cancelled(tuple(lines))
                    return
            job._update("save", 95, None, tuple(lines))
            if target is None:
                session_id = self._store.create_file_session(
                    job.options.path,
                    started_at=started_at,
                    duration_seconds=media.duration_seconds
                    or max((line.end for line in lines), default=0.0),
                    lines=lines,
                    should_cancel=lambda: job.cancel_requested,
                )
            else:
                session_id, source = target
                lines = self._write_revision(job, session_id, source, lines)
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
        self, job: FileJob, media: MediaInfo
    ) -> tuple[list[TranscriptLine], list[np.ndarray]]:
        segmenter = self._segmenter_factory()
        tracker = self._speaker_tracker_factory() if job.options.diarize else None
        refiner = self._make_refiner() if job.options.refine else None
        lines: list[TranscriptLine] = []
        embeddings: list[np.ndarray] = []
        started = time.monotonic()
        duration = media.duration_seconds or 0.0

        def transcribe_phrases(phrases) -> bool:
            for phrase in phrases:
                if job.cancel_requested:
                    return False
                result = self._worker.transcribe(phrase.samples)
                text = result.text.strip()
                if text:
                    if tracker is not None:
                        embedding = tracker.embed(phrase.samples)
                        speaker_id = tracker.assign_embedding(
                            embedding, duration=phrase.end - phrase.start
                        )
                        label = tracker.label(speaker_id)
                        embeddings.append(np.asarray(embedding, dtype=np.float32).copy())
                    else:
                        speaker_id = "speaker-1"
                        label = "Speaker 1"
                    if refiner is not None and refiner.will_refine(text):
                        text = refiner.refine(text, cancelled=lambda: job.cancel_requested)
                    lines.append(
                        TranscriptLine(
                            start=phrase.start,
                            end=phrase.end,
                            wall="",
                            source="file",
                            speaker_id=speaker_id,
                            label=label,
                            text=text,
                        )
                    )
                processed = min(duration, max(0.0, phrase.end)) if duration > 0 else 0.0
                percent = round(80 * processed / duration) if duration > 0 else 0
                elapsed = time.monotonic() - started
                eta = elapsed * (duration - processed) / processed if processed > 0 else None
                job._update("transcribe", percent, eta, tuple(lines))
            return True

        blocks = iter_media_audio(job.options.path, media, self._decoder)
        pending = np.empty(0, dtype=np.float32)
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
            if not job.cancel_requested and pending.size:
                transcribe_phrases(segmenter.accept(pending))
            if not job.cancel_requested:
                transcribe_phrases(segmenter.flush())
        finally:
            blocks.close()
        job._update("transcribe", 80, None, tuple(lines))
        return lines, embeddings

    def _diarize(
        self,
        job: FileJob,
        lines: list[TranscriptLine],
        embeddings: list[np.ndarray],
    ) -> list[TranscriptLine]:
        started = time.monotonic()

        def report(done: int, total: int) -> None:
            fraction = done / total if total else 1.0
            elapsed = time.monotonic() - started
            eta = elapsed * (total - done) / done if done > 0 else None
            job._update("diarize", 80 + round(15 * fraction), eta, tuple(lines))

        relabeled = relabel_system_lines(
            lines,
            embeddings,
            progress=report,
            should_cancel=lambda: job.cancel_requested,
            speaker_count=job.options.speaker_count,
        )
        if relabeled is None:
            return lines
        result = list(relabeled)
        job._update("diarize", 95, 0.0, tuple(result))
        return result

    def _make_refiner(self) -> TextRefiner:
        if self._refiner_factory is not None:
            return self._refiner_factory(self._config)
        from stenographer.lib.refine.factory import build_refiner

        return build_refiner(
            self._config.refine,
            idle_unload_seconds=self._config.asr.idle_unload_seconds,
            enabled=True,
        )

    def _write_revision(
        self, job: FileJob, session_id: str, source: str, lines: list[TranscriptLine]
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
            method="file-transcribe",
            expected_revision=detail.revision,
            revision_name=revision_name,
            should_cancel=lambda: job.cancel_requested,
        )
        return revised
