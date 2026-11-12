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
from functools import partial
from pathlib import Path
from queue import Empty, Full, Queue
from typing import TYPE_CHECKING

import numpy as np

from stenographer.lib.audio.device_setting import capture_target
from stenographer.lib.live.models import vad_model_path
from stenographer.lib.live.phrase_segmenter import Phrase, PhraseSegmenter
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.source_watch import SILENT_SECONDS, SourceWatch
from stenographer.lib.live.speaker_lines import (
    Piece,
    SpeakerNames,
    StreamClock,
    decode_pieces,
    read_saved_audio,
    relabel_lines,
    speaker_pieces,
)
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.platform import current_platform
from stenographer.lib.platform.errors import (
    MicCaptureError,
    SpeakerDiarizerError,
    SystemAudioCaptureError,
    UnsupportedPlatformError,
)
from stenographer.lib.platform.speaker_diarizer import SpeakerSegment
from stenographer.lib.sessions import SessionStore
from stenographer.lib.transcribe.bark_download import MODEL_DIRNAME
from stenographer.lib.transcribe.results import TranscriptionResult
from stenographer.lib.transcribe.worker import Worker

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.config.models import Config
    from stenographer.lib.platform.platform import Platform
    from stenographer.lib.platform.speaker_diarizer import LiveDiarization

log = logging.getLogger(__name__)
_SAMPLE_RATE = 16000
_STOP = object()
_BLOCK_QUEUE_SIZE = 32
_BLOCK_STOP_WAIT_SECONDS = 0.5
# At stop a stream labels the audio it still holds; it holds at most a minute.
_FINISH_SECONDS = 120.0
_SOURCE_ORDER = {"mic": 0, "system": 1}
_WATCH_INTERVAL_SECONDS = 1.0


class LiveSession:
    """Run one session with a shared FIFO ASR queue and one worker thread."""

    def __init__(
        self,
        cfg: Config,
        *,
        mic: bool = True,
        system: bool = True,
        device: str | int | None = None,
        diarize_mic: bool = False,
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
        if diarize_mic:
            self._writer.mark_mic_diarized()
        vad_model = vad_model_path()
        self._worker = Worker(cfg.asr, transport=self._platform.asr_transport())
        # System speakers are always separated; mic speakers only with diarize_mic.
        self._separated = {"mic": diarize_mic, "system": True}
        self._diarizer = self._platform.speaker_diarizer()
        self._speaker_issue = self._diarizer.unavailable_reason()
        if self._speaker_issue is not None:
            log.warning(fmt_event("live", "speakers_unavailable", reason=self._speaker_issue))
        self._names = {source: SpeakerNames(source) for source in ("mic", "system")}
        self._streams: dict[str, LiveDiarization] = {}
        self._clocks = {source: StreamClock() for source in ("mic", "system")}
        self._pushed_seconds = {"mic": 0.0, "system": 0.0}
        self._segments: dict[str, list[SpeakerSegment]] = {"mic": [], "system": []}
        # Segments still open at the live edge, in session time.
        self._tails: dict[str, tuple[SpeakerSegment, ...]] = {"mic": (), "system": ()}
        self._final_until = {"mic": float("-inf"), "system": float("-inf")}
        self._waiting: dict[str, list[Phrase]] = {"mic": [], "system": []}
        self._overflowed: list[str] = []
        self._labelling = False
        self._stop_started = False
        try:
            self._system_capture = self._platform.system_audio_capture()
        except UnsupportedPlatformError as exc:
            self._system_capture = None
            log_failure(log, logging.WARNING, "live: system_source_unavailable", exc, safe=True)
        self._mic_capture = self._platform.mic_capture()
        self._mic_target = capture_target(cfg.audio.input_device if device is None else device)
        self._vad_model = vad_model
        self._monotonic = monotonic if monotonic is not None else time.monotonic
        self._watch = SourceWatch()
        # Sources that are off because their capture failed while enabled; a
        # toggle by the user and the session stop clear the mark.
        self._failed: set[str] = set()
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._queue: Queue[Phrase | object] = Queue()
        self._lock = threading.RLock()
        self._control_lock = threading.RLock()
        self._enabled = {"mic": mic, "system": system and self._system_capture is not None}
        self._active = {"mic": False, "system": False}
        self._levels = {"mic": float("-inf"), "system": float("-inf")}
        self._speech = {"mic": False, "system": False}
        self._block_listeners: list[Callable[[str, np.ndarray], None]] = []
        self._block_listener_lock = threading.Lock()
        self._blocks: Queue[tuple[str, np.ndarray] | object] = Queue(maxsize=_BLOCK_QUEUE_SIZE)
        self._blocks_closed = threading.Event()
        self._block_thread: threading.Thread | None = None
        self._dropped_blocks = 0
        self._segmenters: dict[str, PhraseSegmenter | None] = {"mic": None, "system": None}
        self._segment_offsets = {"mic": 0.0, "system": 0.0}
        self._source_samples = {"mic": 0, "system": 0}
        self._source_seen = {"mic": False, "system": False}
        self._lines: list[TranscriptLine] = []
        self._failed_phrase_count = 0
        self._audio_failed: list[str] = []
        self._subscribers: list[Callable[[TranscriptLine], None]] = []
        self._paused = False
        self._stopped = False
        self._started = False
        self._elapsed_before_run = 0.0
        self._run_started_at: float | None = None
        self._transcriber: threading.Thread | None = None
        if system and self._system_capture is not None:
            self._check_system_availability()

    def start(self) -> None:
        """Hold the ASR model, start its queue consumer, and start enabled sources."""
        with self._control_lock:
            if self._started:
                return
            self._worker.hold_model()
            self._worker.warmup()
            self._run_started_at = self._monotonic()
            self._transcriber = threading.Thread(
                target=self._transcribe_queue,
                name="stenographer-live-transcriber",
                daemon=True,
            )
            self._transcriber.start()
            self._watch_thread = threading.Thread(
                target=self._watch_sources,
                name="stenographer-live-source-watch",
                daemon=True,
            )
            self._watch_thread.start()
            self._started = True
            for source in ("mic", "system"):
                if self._enabled[source]:
                    self._start_source(source)

    def subscribe(self, callback: Callable[[TranscriptLine], None]) -> None:
        """Send each accepted transcript line to *callback*."""
        with self._lock:
            self._subscribers.append(callback)

    def add_block_listener(self, listener: Callable[[str, np.ndarray], None]) -> Callable[[], None]:
        """Send ``(source, samples)`` of each accepted block to *listener* on a delivery thread.

        Return a function that removes the listener.
        """
        with self._block_listener_lock:
            if self._blocks_closed.is_set():
                return lambda: None
            self._block_listeners.append(listener)
            if self._block_thread is None:
                self._block_thread = threading.Thread(
                    target=self._deliver_blocks,
                    name="stenographer-live-blocks",
                    daemon=True,
                )
                self._block_thread.start()

        def remove() -> None:
            with self._block_listener_lock:
                for index, registered in enumerate(self._block_listeners):
                    if registered is listener:
                        del self._block_listeners[index]
                        return

        return remove

    @property
    def dropped_blocks(self) -> int:
        """Return the count of blocks dropped because the delivery queue was full."""
        with self._block_listener_lock:
            return self._dropped_blocks

    @property
    def speech_detected(self) -> dict[str, bool]:
        """Return whether the voice detector of each running source hears speech."""
        with self._lock:
            states = self.source_states
            return {
                source: (
                    states[source] == "on"
                    and self._segmenters[source] is not None
                    and self._speech[source]
                )
                for source in ("mic", "system")
            }

    @property
    def path(self) -> Path:
        return self._writer.path

    @property
    def model_name(self) -> str:
        return MODEL_DIRNAME

    @property
    def process_ids(self) -> tuple[int, ...]:
        """Return the ASR worker child of this session, if it runs."""
        return self._worker.process_ids

    @property
    def idle_unload_deadline(self) -> float | None:
        """Return the monotonic time of the idle unload of its worker, or ``None``."""
        return self._worker.idle_unload_deadline

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def meter_floor_dbfs(self) -> float:
        floor = self._cfg.feedback.spectrum_floor_dbfs
        if isinstance(floor, tuple):
            floor = floor[0]
        return float(floor)

    @property
    def failed_phrase_count(self) -> int:
        with self._lock:
            return self._failed_phrase_count

    @property
    def audio_failed_sources(self) -> tuple[str, ...]:
        """Return the sources whose audio stopped saving; their phrases still transcribe."""
        with self._lock:
            return tuple(self._audio_failed)

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
    def levels_dbfs(self) -> dict[str, float]:
        with self._lock:
            return dict(self._levels)

    @property
    def lines(self) -> tuple[TranscriptLine, ...]:
        with self._lock:
            return tuple(self._lines)

    @property
    def speaker_notice(self) -> str | None:
        """A short reason why some lines get no speaker label, or ``None``."""
        with self._lock:
            if self._speaker_issue is not None:
                return "no speaker labels"
            if self._overflowed:
                return f"{' and '.join(self._overflowed)} speakers behind"
            return None

    @property
    def speaker_issue(self) -> str | None:
        """Why speaker separation is off for this session, or ``None``."""
        with self._lock:
            return self._speaker_issue

    @property
    def labelling_speakers(self) -> bool:
        """True while the stop labels the speakers of a source whose stream fell behind."""
        with self._lock:
            return self._labelling

    @property
    def speakers(self) -> tuple[tuple[str, str], ...]:
        """Return ``(speaker_id, label)`` of each separated speaker that has lines."""
        with self._lock:
            labels: dict[str, dict[str, str]] = {"system": {}, "mic": {}}
            for line in self._lines:
                if self._names[line.source].owns(line.speaker_id):
                    labels[line.source][line.speaker_id] = line.label
            return tuple(item for source in labels.values() for item in source.items())

    def toggle(self, source: str) -> None:
        """Toggle one source. An unavailable source stays off."""
        with self._control_lock:
            if self._stopped:
                return
            with self._lock:
                enabled = not self._enabled[source]
                self._enabled[source] = enabled
                self._failed.discard(source)
            if not enabled:
                self._stop_source(source)
            elif not self._paused:
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
                if self._enabled[source]:
                    self._start_source(source)
            log.info(fmt_event("live", "resumed", duration_seconds=round(self.elapsed_seconds, 3)))

    def rename(self, speaker_id: str, name: str) -> None:
        """Rename one system or room speaker and update its existing transcript lines."""
        with self._lock:
            source = "mic" if self._names["mic"].owns(speaker_id) else "system"
            names = self._names[source]
            label = names.checked_label(speaker_id, name)
            # A failed write, or the closed writer after a save, must change nothing here.
            self._writer.relabel({speaker_id: label})
            names.rename(speaker_id, label)
            self._lines = [
                replace(line, label=label) if line.speaker_id == speaker_id else line
                for line in self._lines
            ]
        log.info(fmt_event("live", "speaker_renamed", speaker_id=speaker_id))

    def stop(self) -> None:
        """Stop capture and save the session with the speaker labels shown live."""
        with self._control_lock:
            if self._stop_started:
                return
            self._stop_started = True
            self._watch_stop.set()
            self._close_block_delivery()
            self._freeze_clock()
            for source in ("mic", "system"):
                if self._active[source] or self._source_seen[source]:
                    self._stop_source(source)
            duration = self._elapsed_before_run
            for source in ("mic", "system"):
                if self._source_seen[source]:
                    self._pad_source(source, duration)
            with self._lock:
                self._stopped = True
                self._failed.clear()
            self._finish_streams()
            if self._transcriber is not None:
                self._queue.put(_STOP)
        if self._transcriber is not None:
            self._queue.join()
            self._transcriber.join()
        if self._watch_thread is not None:
            self._watch_thread.join()
        try:
            self._writer.close()
            self._label_overflowed_sources()
        finally:
            self._worker.release_model()
            self._worker.shutdown()
            self._diarizer.close()
        log.info(fmt_event("live", "stopped", duration_seconds=round(duration, 3)))

    def _finish_streams(self) -> None:
        """Label the audio each stream still holds and release every waiting phrase."""
        for source, stream in tuple(self._streams.items()):
            if source in self._overflowed:
                continue
            try:
                final = stream.finish(_FINISH_SECONDS)
            except SpeakerDiarizerError as exc:
                self._speakers_failed(source, exc)
                continue
            with self._lock:
                self._add_segments(source, final)
                self._tails[source] = ()
                self._final_until[source] = float("inf")
        for source in ("mic", "system"):
            self._release_phrases(source, everything=True)

    def _label_overflowed_sources(self) -> None:
        """Label each source whose live stream fell behind from its saved audio, by the
        line rule, and save the result as a revision."""
        with self._lock:
            sources = [s for s in self._overflowed if s not in self._audio_failed]
            if not sources:
                return
            self._labelling = True
        try:
            lines = list(self.lines)
            for source in sources:
                path = self._writer.path / f"{source}.flac"
                segments = self._diarizer.diarize_file(path)
                own = [line for line in lines if line.source == source]
                relabeled = relabel_lines(
                    own,
                    segments,
                    SpeakerNames(source),
                    read_audio=partial(read_saved_audio, path),
                    decode=lambda samples: self._worker.transcribe(samples).text,
                )
                others = [line for line in lines if line.source != source]
                lines = sorted(
                    [*others, *relabeled],
                    key=lambda line: (line.start, _SOURCE_ORDER.get(line.source, 2)),
                )
            SessionStore(self._writer.path.parent).write_revision(
                self._writer.path.name,
                lines,
                method="diarization",
                expected_revision="transcript.jsonl",
            )
            with self._lock:
                self._lines = lines
        except Exception as exc:
            # The live lines are saved; only their labels stay as they were.
            log_failure(log, logging.WARNING, "live: speaker_pass_failed", exc, safe=True)
        finally:
            with self._lock:
                self._labelling = False

    def _check_system_availability(self) -> None:
        try:
            available, reason = self._system_capture.available()
        except Exception as exc:
            available, reason = False, str(exc)
        if not available:
            self._enabled["system"] = False
            log.warning(fmt_event("live", "system_source_unavailable", reason=reason))

    def _start_source(self, source: str) -> None:
        if self._active[source] or self._paused or self._stopped:
            return
        if source == "system" and self._system_capture is None:
            self._enabled[source] = False
            return
        if source == "system":
            try:
                self._system_capture.stop()
                available, reason = self._system_capture.available()
            except Exception as exc:
                available, reason = False, str(exc)
            if not available:
                self._enabled[source] = False
                log.warning(fmt_event("live", "system_source_unavailable", reason=reason))
                return
        try:
            self._open_stream(source)
            self._pad_source(source, self.elapsed_seconds)
            segmenter = PhraseSegmenter(source, self._vad_model)
            with self._lock:
                self._segmenters[source] = segmenter
                self._segment_offsets[source] = self.elapsed_seconds
                self._clocks[source].start_run(
                    self._pushed_seconds[source], self._segment_offsets[source]
                )
                self._active[source] = True
                # Watched before the capture starts: a failure that the reader
                # reports before start returns takes the source out again.
                self._watch.started(source, self._monotonic())
            if source == "mic":
                self._mic_capture.stop()
                self._mic_capture.start(self._mic_target, self._on_mic_block)
            else:
                self._system_capture.start(self._on_system_block)
            with self._lock:
                self._source_seen[source] = True
                started = self._active[source]
            if started:
                log.info(fmt_event("live", "source_started", source=source))
        except Exception as exc:
            with self._lock:
                if self._enabled[source]:
                    self._failed.add(source)
                self._active[source] = False
                self._enabled[source] = False
                self._segmenters[source] = None
                self._watch.stopped(source)
            log_failure(
                log, logging.WARNING, "live: source_start_failed", exc, safe=True, source=source
            )

    def _open_stream(self, source: str) -> None:
        if not self._separated[source] or source in self._streams:
            return
        with self._lock:
            if self._speaker_issue is not None:
                return
        try:
            stream = self._diarizer.open_live(source)
        except SpeakerDiarizerError as exc:
            with self._lock:
                self._speaker_issue = str(exc)
            log_failure(log, logging.WARNING, "live: speakers_unavailable", exc, safe=True)
            return
        with self._lock:
            self._streams[source] = stream

    def _stop_source(self, source: str) -> None:
        with self._lock:
            was_active = self._active[source]
        if source == "mic":
            try:
                self._mic_capture.stop()
            except Exception as exc:
                log_failure(log, logging.WARNING, "live: mic_stop_failed", exc, safe=True)
        else:
            try:
                self._system_capture.stop()
            except Exception as exc:
                log_failure(log, logging.WARNING, "live: system_stop_failed", exc, safe=True)
        with self._lock:
            self._active[source] = False
            self._speech[source] = False
            self._watch.stopped(source)
            segmenter = self._segmenters[source]
            self._segmenters[source] = None
        if segmenter is not None:
            self._enqueue_phrases(segmenter.flush(), self._segment_offsets[source])
        self._pad_source(source, self.elapsed_seconds)
        if was_active:
            log.info(fmt_event("live", "source_stopped", source=source))

    def _on_mic_block(self, block: np.ndarray | MicCaptureError) -> None:
        if isinstance(block, MicCaptureError):
            self._source_failed("mic", block)
            return
        self._accept_block("mic", block)

    def _on_system_block(self, block: np.ndarray | SystemAudioCaptureError) -> None:
        if isinstance(block, SystemAudioCaptureError):
            self._source_failed("system", block)
            return
        self._accept_block("system", block)

    def _source_failed(self, source: str, error: Exception) -> None:
        with self._lock:
            # A failure of a source that the user already turned off is dropped.
            if self._enabled[source]:
                self._failed.add(source)
            self._active[source] = False
            self._enabled[source] = False
            self._speech[source] = False
            self._watch.stopped(source)
            segmenter = self._segmenters[source]
            self._segmenters[source] = None
        if segmenter is not None:
            self._enqueue_phrases(segmenter.flush(), self._segment_offsets[source])
        if source == "mic":
            log_failure(log, logging.WARNING, "live: mic_source_failed", error, safe=True)
        else:
            log_failure(log, logging.WARNING, "live: system_source_failed", error, safe=True)

    def _watch_sources(self) -> None:
        """Log one WARNING when an active source stops delivering, and INFO when it returns."""
        while not self._watch_stop.wait(_WATCH_INTERVAL_SECONDS):
            with self._lock:
                silent, resumed = self._watch.check(self._monotonic())
            for source in silent:
                log.warning(
                    fmt_event("live", "source_silent", source=source, seconds=SILENT_SECONDS)
                )
            for source in resumed:
                log.info(fmt_event("live", "source_resumed", source=source))

    @property
    def failed_sources(self) -> tuple[str, ...]:
        """Return the sources that are off because their capture failed."""
        with self._lock:
            return tuple(source for source in ("mic", "system") if source in self._failed)

    @property
    def silent_sources(self) -> tuple[str, ...]:
        """Return the active sources that delivered no audio for ``SILENT_SECONDS``."""
        with self._lock:
            return self._watch.silent(self._monotonic())

    def _accept_block(self, source: str, block: np.ndarray) -> None:
        try:
            samples = np.asarray(block, dtype=np.float32).reshape(-1)
            with self._lock:
                if not self._active[source] or self._paused or self._stopped:
                    return
                segmenter = self._segmenters[source]
                self._source_seen[source] = True
                self._watch.block(source, self._monotonic())
                self._write_audio(source, samples)
                rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
                self._levels[source] = 20 * math.log10(rms) if rms > 0 else float("-inf")
                phrases = segmenter.accept(samples)
                self._speech[source] = segmenter.speech_detected
                offset = self._segment_offsets[source]
                stream = self._streams.get(source)
                if stream is not None and samples.size:
                    stream.push(samples)
                    self._pushed_seconds[source] += samples.size / _SAMPLE_RATE
                self._enqueue_phrases(phrases, offset)
            for each in ("mic", "system"):
                self._release_phrases(each)
            self._offer_block(source, samples)
        except Exception as exc:
            log_failure(
                log, logging.WARNING, "live: audio_block_failed", exc, safe=True, source=source
            )

    def _offer_block(self, source: str, samples: np.ndarray) -> None:
        with self._block_listener_lock:
            if not self._block_listeners:
                return
            copy = samples.copy()
            copy.flags.writeable = False
            try:
                self._blocks.put_nowait((source, copy))
            except Full:
                self._dropped_blocks += 1

    def _close_block_delivery(self) -> None:
        with self._block_listener_lock:
            self._blocks_closed.set()
            self._block_listeners.clear()
            thread = self._block_thread
        while True:
            try:
                self._blocks.get_nowait()
            except Empty:
                break
        self._blocks.put_nowait(_STOP)
        if thread is not None:
            thread.join(_BLOCK_STOP_WAIT_SECONDS)

    def _deliver_blocks(self) -> None:
        while True:
            item = self._blocks.get()
            if item is _STOP or self._blocks_closed.is_set():
                return
            source, samples = item
            with self._block_listener_lock:
                listeners = tuple(self._block_listeners)
            for listener in listeners:
                if self._blocks_closed.is_set():
                    return
                try:
                    listener(source, samples)
                except Exception as exc:
                    log_failure(
                        log,
                        logging.WARNING,
                        "live: block_listener_failed",
                        exc,
                        safe=False,
                        source=source,
                    )

    def _enqueue_phrases(self, phrases: list[Phrase], offset: float) -> None:
        """Queue phrases for recognition; a source with a live stream holds them until
        its speaker labels are final up to their end."""
        for phrase in phrases:
            phrase = replace(phrase, start=phrase.start + offset, end=phrase.end + offset)
            with self._lock:
                if phrase.source in self._streams:
                    self._waiting[phrase.source].append(phrase)
                    continue
            self._queue.put((phrase, None))
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

    def _release_phrases(self, source: str, *, everything: bool = False) -> None:
        """Cut the held phrases whose speakers are final at each speaker change and
        queue the parts for recognition."""
        # Both capture threads call this; the lock keeps segments and their final
        # time together, so no phrase is cut with segments that are still missing.
        with self._lock:
            stream = self._streams.get(source)
            if stream is not None:
                try:
                    view = stream.poll()
                except SpeakerDiarizerError as exc:
                    self._speakers_failed(source, exc)
                    return
                self._add_segments(source, view.final)
                self._tails[source] = self._session_segments(source, view.tail)
                if stream.overflowed():
                    self._stream_overflowed(source)
                    return
                self._final_until[source] = max(
                    self._final_until[source],
                    self._clocks[source].session_time(view.final_until),
                )
            waiting = self._waiting[source]
            limit = float("inf") if everything else self._final_until[source]
            ready = [phrase for phrase in waiting if phrase.end <= limit]
            if not ready:
                return
            self._waiting[source] = waiting[len(ready) :]
            # An open segment keeps its start and speaker; only its end can still move,
            # and it holds at least the final time up to the final edge.
            segments = (
                *self._segments[source],
                *(
                    replace(s, end=min(s.end, limit))
                    for s in self._tails[source]
                    if s.start < limit
                ),
            )
            for phrase in ready:
                self._queue.put((phrase, speaker_pieces(phrase.start, phrase.end, segments)))

    def _add_segments(self, source: str, segments) -> None:
        self._segments[source].extend(self._session_segments(source, segments))

    def _session_segments(self, source: str, segments) -> tuple[SpeakerSegment, ...]:
        clock = self._clocks[source]
        return tuple(
            SpeakerSegment(s.speaker, clock.session_time(s.start), clock.session_time(s.end))
            for s in segments
        )

    def _stream_overflowed(self, source: str) -> None:
        """Stop live labels of *source*: its held phrases and new ones get no speaker."""
        with self._lock:
            stream = self._streams.pop(source)
            self._overflowed.append(source)
            waiting, self._waiting[source] = self._waiting[source], []
        stream.close()
        log.warning(fmt_event("live", "speakers_behind", source=source))
        for phrase in waiting:
            self._queue.put((phrase, None))

    def _speakers_failed(self, source: str, exc: Exception) -> None:
        with self._lock:
            stream = self._streams.pop(source, None)
            self._speaker_issue = str(exc)
            waiting, self._waiting[source] = self._waiting[source], []
        if stream is not None:
            stream.close()
        log_failure(log, logging.WARNING, "live: speakers_failed", exc, safe=True, source=source)
        for phrase in waiting:
            self._queue.put((phrase, None))

    def _transcribe_queue(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                phrase, pieces = item
                self._transcribe_phrase(phrase, pieces)
            except Exception as exc:
                with self._lock:
                    self._failed_phrase_count += 1
                log_failure(log, logging.WARNING, "live: phrase_failed", exc, safe=False)
            finally:
                self._queue.task_done()

    def _transcribe_phrase(self, phrase: Phrase, pieces: tuple[Piece, ...] | None) -> None:
        """Decode *phrase* by the line rule: one line per piece with text.

        ``None`` *pieces* means the phrase has no speaker labels.
        """
        if pieces is None:
            pieces = (Piece(phrase.start, phrase.end, None),)
        parts = decode_pieces(
            pieces, phrase.start, phrase.samples, lambda samples: self._transcribe(samples)
        )
        for piece, text in parts:
            with self._lock:
                # Numbers follow the first line of each speaker, so they are given here.
                speaker_id, label = self._names[phrase.source].speaker(piece.speaker)
                wall = (self._writer.started_at + timedelta(seconds=piece.start)).isoformat()
                line = TranscriptLine(
                    start=piece.start,
                    end=piece.end,
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

    def _transcribe(self, samples: np.ndarray) -> str:
        result: TranscriptionResult = self._worker.transcribe(samples)
        return result.text

    def _write_audio(self, source: str, samples: np.ndarray) -> None:
        if source in self._audio_failed:
            return
        try:
            self._writer.write_audio(source, samples)
        except Exception as exc:
            self._mark_audio_failed(source, exc)
        else:
            self._source_samples[source] += samples.size

    def _pad_source(self, source: str, duration: float) -> None:
        if source in self._audio_failed:
            return
        target_samples = max(0, round(duration * _SAMPLE_RATE))
        missing = target_samples - self._source_samples[source]
        if missing <= 0:
            return
        try:
            self._writer.write_silence(source, missing / _SAMPLE_RATE)
        except Exception as exc:
            self._mark_audio_failed(source, exc)
        else:
            self._source_samples[source] += missing

    def _mark_audio_failed(self, source: str, exc: Exception) -> None:
        """Stop saving this source: a later write would put its audio out of step."""
        with self._lock:
            self._audio_failed.append(source)
        log_failure(log, logging.WARNING, "live: audio_save_failed", exc, safe=True, source=source)

    def _freeze_clock(self) -> None:
        if self._run_started_at is None:
            return
        self._elapsed_before_run += max(0.0, self._monotonic() - self._run_started_at)
        self._run_started_at = None
