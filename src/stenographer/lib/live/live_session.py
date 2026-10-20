# SPDX-License-Identifier: GPL-3.0-or-later
"""Coordinate live audio sources, phrase recognition, speaker labels, and storage."""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING

import numpy as np

from stenographer.lib.audio.recorder import Recorder
from stenographer.lib.live.models import LIVE_MODELS
from stenographer.lib.live.phrase import Phrase
from stenographer.lib.live.phrase_segmenter import PhraseSegmenter
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.speaker_tracker import SpeakerTracker
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.platform import current_platform
from stenographer.lib.platform.errors import SystemAudioCaptureError, UnsupportedPlatformError
from stenographer.lib.transcribe.results import TranscriptionResult
from stenographer.lib.transcribe.worker import Worker

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.config.models import Config
    from stenographer.lib.platform.platform import Platform

log = logging.getLogger(__name__)
_SAMPLE_RATE = 16000
_STOP = object()


class LiveSession:
    """Run one session with a shared FIFO ASR queue and one worker thread."""

    def __init__(
        self,
        cfg: Config,
        *,
        mic: bool = True,
        system: bool = True,
        device: str | int | None = None,
        platform: Platform | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if not mic and not system:
            raise ValueError("at least one source must be enabled")
        self._cfg = cfg
        self._platform = platform if platform is not None else current_platform()
        self._started_at = datetime.now(UTC)
        data_dir = self._platform.data_dir(os.environ, Path.home())
        self._writer = SessionWriter.open(data_dir, self._started_at)
        model_dir = data_dir / "models" / "live"
        vad_model = model_dir / LIVE_MODELS[0].filename
        speaker_model = model_dir / LIVE_MODELS[1].filename
        self._worker = Worker(cfg.asr, transport=self._platform.asr_transport())
        self._speaker_tracker = SpeakerTracker(speaker_model)
        try:
            self._system_capture = self._platform.system_audio_capture()
            self._system_platform_reason = None
        except UnsupportedPlatformError as exc:
            self._system_capture = None
            self._system_platform_reason = str(exc)
        self._recorder = Recorder(
            device=cfg.audio.input_device if device is None else device,
            max_seconds=0,
            on_block=self._on_mic_block,
            streaming=True,
        )
        self._vad_model = vad_model
        self._monotonic = monotonic if monotonic is not None else time.monotonic
        self._queue: Queue[Phrase | object] = Queue()
        self._lock = threading.RLock()
        self._control_lock = threading.RLock()
        self._enabled = {"mic": mic, "system": system and self._system_capture is not None}
        self._active = {"mic": False, "system": False}
        self._reasons: dict[str, str | None] = {
            "mic": None,
            "system": self._system_platform_reason,
        }
        self._levels = {"mic": float("-inf"), "system": float("-inf")}
        self._segmenters: dict[str, PhraseSegmenter | None] = {"mic": None, "system": None}
        self._segment_offsets = {"mic": 0.0, "system": 0.0}
        self._source_samples = {"mic": 0, "system": 0}
        self._source_seen = {"mic": False, "system": False}
        self._lines: list[TranscriptLine] = []
        self._subscribers: list[Callable[[TranscriptLine], None]] = []
        self._paused = False
        self._stopped = False
        self._started = False
        self._elapsed_before_run = 0.0
        self._run_started_at: float | None = None
        self._transcriber: threading.Thread | None = None
        self._model_name = cfg.asr.model
        if system and self._system_capture is not None:
            self._check_system_availability()

    def start(self) -> None:
        """Hold the ASR model, start its queue consumer, and start enabled sources."""
        with self._control_lock:
            if self._started:
                return
            self._worker.hold_model()
            self._run_started_at = self._monotonic()
            self._transcriber = threading.Thread(
                target=self._transcribe_queue,
                name="stenographer-live-transcriber",
                daemon=True,
            )
            self._transcriber.start()
            self._started = True
            for source in ("mic", "system"):
                if self._enabled[source] and self._reasons[source] is None:
                    self._start_source(source)

    def subscribe(self, callback: Callable[[TranscriptLine], None]) -> None:
        """Send each accepted transcript line to *callback*."""
        with self._lock:
            self._subscribers.append(callback)

    @property
    def path(self) -> Path:
        return self._writer.path

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def elapsed_seconds(self) -> float:
        elapsed = self._elapsed_before_run
        if self._run_started_at is not None:
            elapsed += max(0.0, self._monotonic() - self._run_started_at)
        return elapsed

    @property
    def source_states(self) -> dict[str, str]:
        with self._lock:
            return {
                source: (
                    "off"
                    if self._stopped or not self._enabled[source]
                    else "paused"
                    if self._paused
                    else "on"
                    if self._active[source]
                    else "off"
                )
                for source in ("mic", "system")
            }

    @property
    def source_reasons(self) -> dict[str, str | None]:
        with self._lock:
            return dict(self._reasons)

    @property
    def levels_dbfs(self) -> dict[str, float]:
        with self._lock:
            return dict(self._levels)

    @property
    def lines(self) -> tuple[TranscriptLine, ...]:
        with self._lock:
            return tuple(self._lines)

    @property
    def speakers(self) -> tuple[tuple[str, str], ...]:
        with self._lock:
            clustering = getattr(self._speaker_tracker, "_clustering", None)
            speaker_ids = getattr(self._speaker_tracker, "speaker_ids", None)
            if speaker_ids is None:
                speaker_ids = [speaker.speaker_id for speaker in clustering.speakers]
            return tuple(
                (speaker_id, self._speaker_tracker.label(speaker_id)) for speaker_id in speaker_ids
            )

    def toggle(self, source: str) -> None:
        """Toggle one source. An unavailable source keeps its reason until retried."""
        self._validate_source(source)
        with self._control_lock:
            if self._stopped:
                return
            if self._enabled[source]:
                self._enabled[source] = False
                self._stop_source(source)
            else:
                self._enabled[source] = True
                self._reasons[source] = None
                if not self._paused:
                    self._start_source(source)
            log.info(
                fmt_event("live", "source_toggled", source=source, state=self.source_states[source])
            )

    def pause(self) -> None:
        """Stop capture and freeze the session clock."""
        with self._control_lock:
            if self._paused or self._stopped:
                return
            self._freeze_clock()
            for source in ("mic", "system"):
                if self._active[source] or self._source_seen[source]:
                    self._stop_source(source)
            self._paused = True
            log.info(fmt_event("live", "paused", duration_seconds=round(self.elapsed_seconds, 3)))

    def resume(self) -> None:
        """Resume the session clock and start sources that remain enabled."""
        with self._control_lock:
            if not self._paused or self._stopped:
                return
            self._paused = False
            self._run_started_at = self._monotonic()
            for source in ("mic", "system"):
                if self._enabled[source] and self._reasons[source] is None:
                    self._start_source(source)
            log.info(fmt_event("live", "resumed", duration_seconds=round(self.elapsed_seconds, 3)))

    def rename(self, speaker_id: str, name: str) -> None:
        """Rename one system speaker and update its existing transcript lines."""
        with self._lock:
            self._speaker_tracker.rename(speaker_id, name)
            label = self._speaker_tracker.label(speaker_id)
            self._lines = [
                replace(line, label=label) if line.speaker_id == speaker_id else line
                for line in self._lines
            ]
        self._writer.relabel({speaker_id: label})
        log.info(fmt_event("live", "speaker_renamed", speaker_id=speaker_id))

    def stop(self) -> None:
        """Stop capture, flush phrases, drain ASR, save the session, and stop the worker."""
        with self._control_lock:
            if self._stopped:
                return
            self._freeze_clock()
            for source in ("mic", "system"):
                if self._active[source] or self._source_seen[source]:
                    self._stop_source(source)
            duration = self._elapsed_before_run
            for source in ("mic", "system"):
                if self._source_seen[source]:
                    self._pad_source(source, duration)
            self._stopped = True
            if self._transcriber is not None:
                self._queue.put(_STOP)
        if self._transcriber is not None:
            self._queue.join()
            self._transcriber.join()
        try:
            self._writer.close()
        finally:
            self._worker.release_model()
            self._worker.shutdown()
        log.info(fmt_event("live", "stopped", duration_seconds=round(duration, 3)))

    def _check_system_availability(self) -> None:
        try:
            available, reason = self._system_capture.available()
        except Exception as exc:
            available, reason = False, str(exc)
        if not available:
            self._enabled["system"] = False
            self._reasons["system"] = reason or "system audio capture is unavailable"

    def _start_source(self, source: str) -> None:
        if self._active[source] or self._paused or self._stopped:
            return
        if source == "system" and self._system_capture is None:
            self._enabled[source] = False
            self._reasons[source] = (
                self._system_platform_reason or "system audio capture is unavailable"
            )
            return
        if source == "system":
            try:
                self._system_capture.stop()
                available, reason = self._system_capture.available()
            except Exception as exc:
                available, reason = False, str(exc)
            if not available:
                self._enabled[source] = False
                self._reasons[source] = reason or "system audio capture is unavailable"
                return
        try:
            self._pad_source(source, self.elapsed_seconds)
            segmenter = PhraseSegmenter(source, self._vad_model)
            with self._lock:
                self._segmenters[source] = segmenter
                self._segment_offsets[source] = self.elapsed_seconds
                self._active[source] = True
                self._reasons[source] = None
            if source == "mic":
                self._recorder.start()
            else:
                self._system_capture.start(self._on_system_block)
            with self._lock:
                self._source_seen[source] = True
            log.info(fmt_event("live", "source_started", source=source))
        except Exception as exc:
            with self._lock:
                self._active[source] = False
                self._enabled[source] = False
                self._segmenters[source] = None
                self._reasons[source] = str(exc)
            log_failure(
                log, logging.WARNING, "live: source_start_failed", exc, safe=True, source=source
            )

    def _stop_source(self, source: str) -> None:
        with self._lock:
            was_active = self._active[source]
        if source == "mic":
            try:
                self._recorder.stop()
            except Exception as exc:
                log_failure(log, logging.WARNING, "live: mic_stop_failed", exc, safe=True)
        else:
            try:
                self._system_capture.stop()
            except Exception as exc:
                log_failure(log, logging.WARNING, "live: system_stop_failed", exc, safe=True)
        with self._lock:
            self._active[source] = False
            segmenter = self._segmenters[source]
            self._segmenters[source] = None
        if segmenter is not None:
            self._enqueue_phrases(segmenter.flush(), self._segment_offsets[source])
        self._pad_source(source, self.elapsed_seconds)
        if was_active:
            log.info(fmt_event("live", "source_stopped", source=source))

    def _on_mic_block(self, block: np.ndarray, _rate: int, _epoch: int) -> None:
        self._accept_block("mic", block)

    def _on_system_block(self, block: np.ndarray | SystemAudioCaptureError) -> None:
        if isinstance(block, SystemAudioCaptureError):
            with self._lock:
                self._active["system"] = False
                self._enabled["system"] = False
                self._reasons["system"] = str(block)
                segmenter = self._segmenters["system"]
                self._segmenters["system"] = None
            if segmenter is not None:
                self._enqueue_phrases(segmenter.flush(), self._segment_offsets["system"])
            log_failure(log, logging.WARNING, "live: system_source_failed", block, safe=True)
            return
        self._accept_block("system", block)

    def _accept_block(self, source: str, block: np.ndarray) -> None:
        try:
            samples = np.asarray(block, dtype=np.float32).reshape(-1)
            with self._lock:
                if not self._active[source] or self._paused or self._stopped:
                    return
                segmenter = self._segmenters[source]
                if segmenter is None:
                    return
                self._source_seen[source] = True
                self._writer.write_audio(source, samples)
                self._source_samples[source] += samples.size
                rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
                self._levels[source] = 20 * math.log10(rms) if rms > 0 else float("-inf")
                phrases = segmenter.accept(samples)
                offset = self._segment_offsets[source]
                self._enqueue_phrases(phrases, offset)
        except Exception as exc:
            log_failure(
                log, logging.WARNING, "live: audio_block_failed", exc, safe=True, source=source
            )

    def _enqueue_phrases(self, phrases: list[Phrase], offset: float) -> None:
        for phrase in phrases:
            self._queue.put(replace(phrase, start=phrase.start + offset, end=phrase.end + offset))
        if phrases:
            log.debug(
                fmt_event(
                    "live",
                    "phrases_queued",
                    source=phrases[0].source,
                    phrase_count=len(phrases),
                    queue_depth=self._queue.qsize(),
                )
            )

    def _transcribe_queue(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                assert isinstance(item, Phrase)
                self._transcribe_phrase(item)
            except Exception as exc:
                log_failure(log, logging.WARNING, "live: phrase_failed", exc, safe=False)
            finally:
                self._queue.task_done()

    def _transcribe_phrase(self, phrase: Phrase) -> None:
        result: TranscriptionResult = self._worker.transcribe(phrase.samples)
        text = result.text.strip()
        if not text or (
            result.segments and all(segment.no_speech_prob >= 0.6 for segment in result.segments)
        ):
            return
        if phrase.source == "mic":
            speaker_id = "you"
            label = "You"
        else:
            with self._lock:
                speaker_id = self._speaker_tracker.assign(phrase.samples)
                label = self._speaker_tracker.label(speaker_id)
        with self._lock:
            if phrase.source == "system":
                label = self._speaker_tracker.label(speaker_id)
            wall = (self._writer.started_at + timedelta(seconds=phrase.start)).isoformat()
            line = TranscriptLine(
                start=phrase.start,
                end=phrase.end,
                wall=wall,
                source=phrase.source,
                speaker_id=speaker_id,
                label=label,
                text=text,
            )
            self._writer.append_line(line)
            self._lines.append(line)
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber(line)
            except Exception as exc:
                log_failure(log, logging.WARNING, "live: subscriber_failed", exc, safe=False)

    def _pad_source(self, source: str, duration: float) -> None:
        target_samples = max(0, round(duration * _SAMPLE_RATE))
        missing = target_samples - self._source_samples[source]
        if missing <= 0:
            return
        self._writer.write_silence(source, missing / _SAMPLE_RATE)
        self._source_samples[source] += missing

    def _freeze_clock(self) -> None:
        if self._run_started_at is None:
            return
        self._elapsed_before_run += max(0.0, self._monotonic() - self._run_started_at)
        self._run_started_at = None

    @staticmethod
    def _validate_source(source: str) -> None:
        if source not in {"mic", "system"}:
            raise ValueError(f"unknown live source: {source}")
