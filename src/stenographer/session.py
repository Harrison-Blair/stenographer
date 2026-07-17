# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-utterance orchestrator that wires all components together."""

from __future__ import annotations

import collections
import contextlib
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

from stenographer.asr.model import SegmentInfo
from stenographer.asr.streaming import StreamingTranscriber
from stenographer.asr.worker import CancelledError
from stenographer.live import LiveStreamer
from stenographer.output.formatter import HeuristicFormatter

if TYPE_CHECKING:
    from stenographer.asr.worker import Worker
    from stenographer.audio.capture import Recorder
    from stenographer.audio.feedback import Feedback
    from stenographer.capabilities import Capabilities
    from stenographer.config import Config
    from stenographer.hotkey.listener import HotkeyListener
    from stenographer.notification import DesktopNotification
    from stenographer.output.clipboard import ClipboardManager
    from stenographer.output.inject import Injector

log = logging.getLogger(__name__)

# A queued batch recording, optionally tagged with which hotkey triggered it
# (added by FTHR-004; the untagged 4-tuple form defaults to "dictate").
_BatchItem = tuple[np.ndarray, Literal["ptt", "toggle"], threading.Event, int]
_TaggedBatchItem = tuple[
    np.ndarray, Literal["ptt", "toggle"], threading.Event, int, Literal["dictate"]
]


@dataclass
class _LiveItem:
    """Utterance-queue entry for a streamed recording (see LiveStreamer)."""

    streamer: LiveStreamer
    generation: int


@dataclass
class _ChunkItem:
    """Utterance-queue entry for one chunk of an aggregated paste-mode
    recording: silence-flushed chunks are decoded as they arrive (decoding
    overlaps recording) but nothing reaches the cursor until the final chunk
    assembles the whole utterance and pastes once. ``offset_seconds`` is the
    chunk's position in the recording, so segment timestamps can be restored
    to absolute recording time for the paragraph-pause heuristic."""

    samples: np.ndarray
    abort: threading.Event
    generation: int
    offset_seconds: float
    final: bool
    mode: Literal["ptt", "toggle"] = "ptt"
    source: Literal["dictate"] = "dictate"


class Session:
    """Orchestrates one utterance: hotkey -> record -> transcribe -> output.

    The session is the single point of state transitions. All
    callbacks from the hotkey listener, the recorder, and the worker
    funnel through session methods protected by ``_lock`` so that a
    key event arriving concurrently with a shutdown signal does not
    race.
    """

    def __init__(
        self,
        *,
        cfg: Config,
        capabilities: Capabilities,
        listener: HotkeyListener | None,
        recorder: Recorder,
        worker: Worker,
        feedback: Feedback,
        injector: Injector,
        clipboard: ClipboardManager,
        notification: DesktopNotification | None = None,
        one_shot: bool = False,
    ) -> None:
        self._cfg = cfg
        self._caps = capabilities
        self._listener = listener
        self._recorder = recorder
        self._worker = worker
        self._feedback = feedback
        self._injector = injector
        self._clipboard = clipboard
        self._notification = notification
        self._one_shot = one_shot

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._recording = False
        # Which hotkey owns the active recording (meaningful only while
        # _recording is True).
        self._recording_source: Literal["dictate"] = "dictate"
        self._utterances_processed = 0
        # Abort event for the recording currently in progress (fresh per
        # recording; shared by that recording's flush segments and tail).
        self._recording_abort = threading.Event()
        # Abort event of the utterance the processor thread is running now,
        # so cancel_all() can reach in-flight transcription.
        self._active_abort: threading.Event | None = None
        # Bumped by cancel_all(); queue items stamped with an older
        # generation are dropped by the processor. This closes the race
        # where an item is dequeued but not yet processing when a cancel
        # drains the queue.
        self._cancel_generation = 0

        self._utterance_queue: queue.Queue[
            _BatchItem | _TaggedBatchItem | _LiveItem | _ChunkItem | None
        ]
        self._utterance_queue = queue.Queue()
        self._processor: threading.Thread | None = None
        self._processing_times: collections.deque[float] = collections.deque(maxlen=10)
        self._sample_rate = cfg.audio.sample_rate
        self._formatter = HeuristicFormatter(
            cfg.formatting, append_trailing_space=cfg.output.append_trailing_space
        )
        # Mid-recording silence flushing only applies to the PTT/toggle daemon.
        # In one-shot mode the processor tears the session down after the first
        # queued item, which would truncate dictation at the first pause.
        self._silence_detection = cfg.audio.silence_detection and not one_shot
        # In paste mode, flushed chunks are still decoded as they arrive so
        # transcription overlaps recording, but they are aggregated: nothing
        # reaches the cursor until the final chunk assembles the utterance and
        # pastes once. Pasting per flush would interrupt dictation and split
        # the recording into separate utterances, destroying the segment-
        # timestamp gaps the formatter's paragraph-pause heuristic needs.
        self._aggregate_chunks = self._silence_detection and cfg.output.injection_method == "paste"
        # Seconds of audio already flushed for the active recording — the next
        # chunk's offset into the recording. Written on the PortAudio callback
        # thread; read by the stop path after the stream has stopped.
        self._flushed_seconds = 0.0
        # Chunk aggregation state (processor thread only): segments decoded so
        # far for the recording identified by _chunk_abort.
        self._chunk_abort: threading.Event | None = None
        self._chunk_segments: list[SegmentInfo] = []
        # Live word-level streaming pastes each committed delta as it is
        # confirmed; text mode assembles the utterance and types it.
        self._streaming = bool(cfg.streaming.enabled and cfg.output.injection_method == "paste")
        # The streamer of the recording currently capturing audio. Popped by
        # the stop/discard path that ends that recording, so a following
        # recording can never be routed into a previous utterance's streamer
        # that is still finishing its final decode.
        self._recording_streamer: LiveStreamer | None = None
        # The streamer that has not yet finished processing (its final decode
        # may outlive the recording); cancel_all uses it to wake the driver.
        # Cleared by _run_live when the drive completes.
        self._live_streamer: LiveStreamer | None = None

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    @property
    def is_one_shot(self) -> bool:
        return self._one_shot

    @property
    def lock(self) -> threading.RLock:
        """The lock shared with the hotkey listener's dispatch path."""
        return self._lock

    @property
    def notification(self) -> DesktopNotification | None:
        return self._notification

    def attach_listener(self, listener: HotkeyListener) -> None:
        """Late-bind the hotkey listener.

        The listener is constructed after the session because it shares
        the session's lock and callbacks.
        """
        self._listener = listener

    def start_listener(self) -> None:
        if self._listener is not None:
            self._listener.start()

    def start(self) -> None:
        """Launch the processor thread that dequeues and processes utterances."""
        self._processor = threading.Thread(
            target=self._process_utterance_queue, name="session-processor", daemon=True
        )
        self._processor.start()

    def _process_utterance_queue(self) -> None:
        """Consumer loop: dequeue utterances and transcribe + output each in order."""
        log.debug("session: processor thread started")
        while True:
            item = self._utterance_queue.get()
            if item is None:
                log.debug("session: processor thread exiting")
                break
            if isinstance(item, _LiveItem):
                generation = item.generation
                abort = item.streamer.abort
            elif isinstance(item, _ChunkItem):
                generation = item.generation
                abort = item.abort
            else:
                # Batch item: (samples, mode, abort, generation[, source]).
                # The trailing source element is optional so directly-queued
                # test items (and other legacy 4-tuples) keep working.
                abort, generation = item[2], item[3]
            with self._lock:
                if generation < self._cancel_generation:
                    log.info("session: dropping cancelled utterance")
                    if isinstance(item, _LiveItem) and self._live_streamer is item.streamer:
                        self._live_streamer = None
                    continue
                self._active_abort = abort
            remaining = self._utterance_queue.qsize()
            if remaining > 0:
                log.info("session: processing utterance (%d queued)", remaining)
            t0 = time.monotonic()
            if isinstance(item, _LiveItem):
                self._run_live(item.streamer)
            elif isinstance(item, _ChunkItem):
                self._process_chunk(item)
            else:
                samples, mode, abort, generation, *rest = item
                source = rest[0] if rest else "dictate"
                self._process(samples, mode, abort, source)
            with self._lock:
                self._active_abort = None
            elapsed = time.monotonic() - t0
            self._processing_times.append(elapsed)
            if self._one_shot:
                self._stop_event.set()
            if self._utterance_queue.qsize() == 0 and self._notification is not None:
                # Queue drained; clear 'Transcribing…' unless a new recording
                # has already replaced it with 'Listening…'.
                with self._lock:
                    if not self._recording:
                        self._notification.hide()
            remaining_after = self._utterance_queue.qsize()
            if remaining_after > 0 and self._processing_times:
                avg_rt = sum(self._processing_times) / len(self._processing_times)
                eta = avg_rt * remaining_after
                log.info(
                    "session: %d utterance(s) remaining, est. %.0fs",
                    remaining_after,
                    eta,
                )

    def run(self) -> None:
        """Block until stop() is called (e.g. by SIGTERM)."""
        try:
            self._stop_event.wait()
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        if not self._stop_event.is_set():
            log.info("session: stop requested")
        self._stop_event.set()
        if self._recorder.is_active:
            try:
                samples = self._recorder.stop()
            except Exception as exc:
                log.error("session: recorder.stop during shutdown failed: %s", exc)
            else:
                streamer = self._recording_streamer
                self._recording_streamer = None
                if streamer is not None:
                    # Streamed recording: the queued live item finishes the
                    # utterance once it sees the final signal.
                    streamer.signal_final(samples)
                else:
                    self._drain(samples)
        try:
            if self._listener is not None:
                self._listener.stop(timeout=2.0)
        except Exception as exc:
            log.error("session: listener.stop failed: %s", exc)
        self._worker.cancel()
        self._utterance_queue.put(None)
        if self._processor is not None and self._processor.is_alive():
            self._processor.join(timeout=60.0)
        try:
            self._worker.stop(timeout=10.0)
        except Exception as exc:
            log.error("session: worker.stop failed: %s", exc)
        try:
            self._feedback.close()
        except Exception as exc:
            log.error("session: feedback.close failed: %s", exc)
        try:
            self._injector.close()
        except Exception as exc:
            log.error("session: injector.close failed: %s", exc)
        try:
            self._clipboard.close()
        except Exception as exc:
            log.error("session: clipboard.close failed: %s", exc)
        try:
            if self._notification is not None:
                self._notification.hide()
                self._notification.flush(timeout=2.0)
        except Exception as exc:
            log.error("session: notification.hide failed: %s", exc)

    def on_recording_start(self, source: Literal["dictate"] = "dictate") -> None:
        with self._lock:
            if self._stop_event.is_set():
                return
            if self._recording:
                log.warning("session: on_recording_start while already recording")
                return
            self._recording = True
            self._recording_source = source
            self._recording_abort = threading.Event()
            self._flushed_seconds = 0.0
            try:
                is_lazy_first = self._cfg.asr.mode == "lazy" and not self._worker.is_model_loaded()
                if is_lazy_first:
                    self._worker.ensure_model_loaded(
                        on_loaded=self._on_model_loaded,
                        on_unloaded=self._on_model_unloaded,
                    )
                    self._on_model_loading()
                if self._streaming:
                    # Live streaming replaces the silence-flush path: the
                    # driver's tail-silence guard covers hallucination-over-
                    # silence, and words are typed as they stabilise.
                    streamer = LiveStreamer(
                        cfg=self._cfg,
                        recorder=self._recorder,
                        worker=self._worker,
                        injector=self._injector,
                        transcriber=StreamingTranscriber(
                            agreement_n=self._cfg.streaming.agreement_n
                        ),
                        formatter=HeuristicFormatter(
                            self._cfg.formatting,
                            append_trailing_space=self._cfg.output.append_trailing_space,
                        ),
                        clipboard=self._clipboard,
                        caps=self._caps,
                        abort=self._recording_abort,
                    )
                    self._recorder.start(
                        on_partial=streamer.signal_partial,
                        min_partial_seconds=self._cfg.streaming.min_chunk_seconds,
                    )
                    self._recording_streamer = streamer
                    self._live_streamer = streamer
                    self._utterance_queue.put(_LiveItem(streamer, self._cancel_generation))
                else:
                    self._recorder.start(
                        on_segment=self._enqueue_flush_segment if self._silence_detection else None
                    )
                log.info("session: recording started")
                if not is_lazy_first and self._notification is not None:
                    self._notification.show_listening()
            except Exception as exc:
                self._recording = False
                log.error("session: recorder.start failed: %s", exc)

    def on_recording_stop(
        self, mode: Literal["ptt", "toggle"], source: Literal["dictate"] = "dictate"
    ) -> None:
        with self._lock:
            if not self._recording:
                log.warning("session: on_recording_stop with no active recording")
                return
            if source != self._recording_source:
                # The other hotkey's state machine went through a press/release
                # cycle whose start was ignored (a recording was already
                # active). Its stop must not end — or re-route — a recording
                # it does not own.
                log.warning(
                    "session: ignoring %s-mode stop for a %s-mode recording",
                    source,
                    self._recording_source,
                )
                return
            self._recording = False
            # Pop under the lock: only the streamer created for *this*
            # recording may receive its final signal. A previous utterance's
            # streamer still running its final decode must not capture it.
            streamer = self._recording_streamer
            self._recording_streamer = None
            try:
                samples = self._recorder.stop()
            except Exception as exc:
                log.error("session: recorder.stop failed: %s", exc)
                if self._one_shot:
                    self._stop_event.set()
                return
        log.info("session: recording stopped, %d samples captured", samples.shape[0])
        if streamer is not None:
            # Streamed recording: hand the finalized tail to the driver, which
            # runs the final decode + flush. The live item is already queued.
            streamer.signal_final(samples)
            if self._notification is not None:
                self._notification.show_transcribing()
            return
        if self._aggregate_chunks:
            # Even an empty tail must be queued: the final item is what
            # assembles the flushed chunks and pastes the utterance.
            self._utterance_queue.put(
                _ChunkItem(
                    samples,
                    self._recording_abort,
                    self._cancel_generation,
                    self._flushed_seconds,
                    final=True,
                    mode=mode,
                    source=source,
                )
            )
            if self._notification is not None:
                self._notification.show_transcribing()
            return
        if self._silence_detection and samples.shape[0] == 0:
            # Nothing left after the final flush; the spoken chunks were already
            # enqueued mid-recording. Skip the empty tail to avoid a stray cue.
            log.info("session: no trailing audio after final flush, nothing to queue")
            self._refresh_notification()
            return
        self._utterance_queue.put(
            (samples, mode, self._recording_abort, self._cancel_generation, source)
        )
        if self._notification is not None:
            self._notification.show_transcribing()
        queue_depth = self._utterance_queue.qsize()
        if queue_depth > 1:
            log.info("session: %d utterance(s) queued for transcription", queue_depth)
        if self._one_shot:
            pass  # processor thread sets _stop_event after processing

    def _run_live(self, streamer: LiveStreamer) -> None:
        """Drive one streamed utterance to completion on the processor thread."""
        typed = ""
        try:
            typed = streamer.run()
        except Exception as exc:
            log.error("session: live streamer failed: %s", exc)
            if not self._stop_event.is_set():
                with contextlib.suppress(Exception):
                    self._feedback.play("error")
        finally:
            with self._lock:
                if self._live_streamer is streamer:
                    self._live_streamer = None
        if streamer.abort.is_set() or not typed:
            return
        self._utterances_processed += 1
        if not self._stop_event.is_set():
            with contextlib.suppress(Exception):
                self._feedback.play("transcribe_done")

    def _refresh_notification(self) -> None:
        """Show the transcribing indicator if work remains queued, else hide it."""
        if self._notification is None:
            return
        if self._utterance_queue.qsize() > 0:
            self._notification.show_transcribing()
        else:
            self._notification.hide()

    def _enqueue_flush_segment(self, samples: np.ndarray) -> None:
        """Enqueue a segment flushed mid-recording on a silence gap.

        Called from the recorder's PortAudio callback thread; it only touches
        the thread-safe utterance queue, so it takes no lock. ``mode`` is inert
        (logging only) and cannot be known before key release, so flushes are
        tagged ``"ptt"``. The abort event and generation are plain attribute
        reads; a stale generation read around a concurrent cancel only makes
        the flush item eligible for dropping, which is the desired outcome.

        In paste mode the flush becomes an aggregated chunk (decoded now,
        pasted with the rest of the utterance at the end); in text mode it is
        a standalone utterance typed as soon as it is transcribed.
        """
        if self._aggregate_chunks:
            offset = self._flushed_seconds
            self._flushed_seconds += samples.shape[0] / self._sample_rate
            self._utterance_queue.put(
                _ChunkItem(
                    samples, self._recording_abort, self._cancel_generation, offset, final=False
                )
            )
            return
        self._utterance_queue.put((samples, "ptt", self._recording_abort, self._cancel_generation))

    def on_toggle_off(self, source: Literal["dictate"] = "dictate") -> None:
        self.on_recording_stop("toggle", source=source)

    def discard_recording(self, source: Literal["dictate"] = "dictate") -> None:
        """Stop the active recording and drop its samples (no transcription).

        Wired to the listener's double-tap-window expiry: a lone short tap
        of the chord starts a recording that is thrown away here. Only the
        hotkey that owns the active recording may discard it — a stray tap
        of the other hotkey mid-recording must not destroy the utterance.
        """
        with self._lock:
            if not self._recording:
                log.warning("session: discard_recording with no active recording")
                return
            if source != self._recording_source:
                log.warning(
                    "session: ignoring %s-mode discard for a %s-mode recording",
                    source,
                    self._recording_source,
                )
                return
            self._recording = False
            self._recording_abort.set()
            # Only the discarded recording's own streamer is aborted; a
            # previous utterance's streamer still finishing its final decode
            # must complete normally.
            streamer = self._recording_streamer
            self._recording_streamer = None
            if streamer is not None:
                streamer.signal_abort()
            try:
                self._recorder.stop()
            except Exception as exc:
                log.error("session: recorder.stop during discard failed: %s", exc)
            log.info("session: recording discarded")
            self._refresh_notification()

    def cancel_all(self) -> None:
        """Cancel everything: active recording, queued utterances, and the
        in-flight transcription. Already-typed text is not undone.

        Wired to the cancel chord (main hotkey held + cancel key). Runs on
        the listener dispatch thread, which already holds ``_lock`` (RLock).
        """
        with self._lock:
            log.info("session: cancel requested")
            self._cancel_generation += 1
            if self._recording:
                self._recording = False
                self._recording_abort.set()
                # _live_streamer below wakes the driver; the recording
                # reference just needs to be dropped so nothing routes a
                # later stop/discard into this cancelled streamer.
                self._recording_streamer = None
                try:
                    self._recorder.stop()
                except Exception as exc:
                    log.error("session: recorder.stop during cancel failed: %s", exc)
            while True:
                try:
                    item = self._utterance_queue.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    # Shutdown sentinel; keep it for the processor thread.
                    self._utterance_queue.put(None)
                    break
            if self._active_abort is not None:
                self._active_abort.set()
            if self._live_streamer is not None:
                self._live_streamer.signal_abort()
            if self._notification is not None:
                with contextlib.suppress(Exception):
                    self._notification.hide()

    # -- lazy-mode model lifecycle callbacks (called from loader / timer threads) --

    def _on_model_loading(self) -> None:
        try:
            self._feedback.play("model_loading")
        except Exception as exc:
            log.error("session: model_loading cue failed: %s", exc)
        if self._notification is not None:
            try:
                self._notification.show_model_loading()
            except Exception as exc:
                log.error("session: show_model_loading failed: %s", exc)

    def _on_model_loaded(self) -> None:
        try:
            self._feedback.play("model_ready")
        except Exception as exc:
            log.error("session: model_ready cue failed: %s", exc)
        if self._notification is not None:
            # Replace 'Loading speech model — listening…' with 'Listening…' if
            # still recording; otherwise the stop path already set the status.
            with self._lock:
                if self._recording:
                    try:
                        self._notification.show_listening()
                    except Exception as exc:
                        log.error("session: show_listening failed: %s", exc)

    def _on_model_unloaded(self) -> None:
        if self._notification is not None:
            try:
                self._notification.show_model_unloaded()
            except Exception as exc:
                log.error("session: show_model_unloaded failed: %s", exc)

    def _process(
        self,
        samples: np.ndarray,
        mode: Literal["ptt", "toggle"],
        abort: threading.Event,
        source: Literal["dictate"] = "dictate",
    ) -> None:
        log.info(
            "session: processing %d samples (mode=%s, source=%s)", samples.shape[0], mode, source
        )

        segment_queue: queue.Queue[SegmentInfo | None] = queue.Queue()
        future = self._worker.submit(samples, on_segment=segment_queue.put, cancel_event=abort)
        # The None sentinel unblocks the loop when transcription finishes
        # (all segments are emitted before the future resolves).
        future.add_done_callback(lambda _f: segment_queue.put(None))

        paste_mode = self._cfg.output.injection_method == "paste"

        injected_text = ""
        while True:
            seg = segment_queue.get()
            if seg is None:
                break
            if abort.is_set():
                # Cancelled: keep draining until the sentinel, but stop
                # injecting. Text already typed at the cursor stays.
                continue
            if seg.no_speech_prob >= self._cfg.asr.silence_threshold:
                # Likely a hallucination over silence (e.g. "Thank you.");
                # never send it to the cursor. The post-transcription check
                # below handles the all-silence case for clipboard/paste.
                log.info("session: skipping probable-silence segment")
                log.debug("session: silence segment %r", seg.text)
                continue
            if seg.text.strip():
                if paste_mode:
                    injected_text += seg.text
                    try:
                        self._feedback.play("segment")
                    except Exception as exc:
                        log.error("session: segment cue failed: %s", exc)
                else:
                    typed = False
                    try:
                        typed = bool(self._injector.type_text(seg.text, raw=True))
                    except Exception as exc:
                        log.error("session: injector partial failed: %s", exc)
                    if typed:
                        injected_text += seg.text

        try:
            result = future.result(timeout=5.0)  # done already; timeout is defensive
        except CancelledError:
            log.info("session: transcription cancelled")
            return
        except Exception as exc:
            log.error("session: transcription failed: %s", exc)
            if not self._stop_event.is_set():
                with contextlib.suppress(Exception):
                    self._feedback.play("error")
            return
        if abort.is_set():
            # Cancelled after transcription completed; drop the output.
            log.info("session: transcription result discarded after cancel")
            return
        self._utterances_processed += 1
        text = result.text
        # Full transcripts go to the log file only at DEBUG (privacy).
        log.info("session: transcript received (%d chars)", len(text))
        log.debug("session: transcript %r", text)
        if result.segments:
            speech_segments = [
                seg
                for seg in result.segments
                if seg.no_speech_prob < self._cfg.asr.silence_threshold
            ]
            if not speech_segments:
                log.info("session: silence detected, skipping output")
                if not self._stop_event.is_set():
                    with contextlib.suppress(Exception):
                        self._feedback.play("error")
                return
            if len(speech_segments) != len(result.segments):
                # Drop probable-silence segments from the clipboard/paste text
                # too, matching what the segment loop sent to the cursor.
                text = "".join(seg.text for seg in speech_segments).strip()
                log.info(
                    "session: dropped %d probable-silence segment(s) from output",
                    len(result.segments) - len(speech_segments),
                )
        if not text or not text.strip():
            log.info("session: empty transcript, skipping output")
            if not self._stop_event.is_set():
                with contextlib.suppress(Exception):
                    self._feedback.play("error")
            return
        if paste_mode:
            if result.segments:
                # Paste output goes through the heuristic formatter (spacing,
                # capitalisation, pause-based paragraphs at segment granularity).
                text = self._formatter.format_batch(speech_segments)
            # Copy to clipboard, then fire the paste chord
            if self._cfg.clipboard.enabled and self._caps.has_wl_copy:
                try:
                    self._clipboard.copy(text)
                except Exception as exc:
                    log.error("session: clipboard.copy raised: %s", exc)
            if self._caps.has_paste_trigger:
                try:
                    self._injector.paste()
                except Exception as exc:
                    log.error("session: injector.paste raised: %s", exc)
        else:
            if self._caps.has_paste_trigger and not injected_text.strip():
                # No partial segment made it to the cursor; type the full text.
                try:
                    self._injector.type_text(text)
                except Exception as exc:
                    log.error("session: injector.type_text raised: %s", exc)
            elif injected_text.strip() != text.strip():
                # Some segments were typed and some were not. Re-typing the
                # full transcript would duplicate what is already at the
                # cursor; the clipboard below holds the complete text.
                log.warning("session: partial injection incomplete; full transcript on clipboard")
            if self._cfg.clipboard.enabled and self._caps.has_wl_copy:
                try:
                    self._clipboard.copy(text)
                except Exception as exc:
                    log.error("session: clipboard.copy raised: %s", exc)
        if not self._stop_event.is_set():
            with contextlib.suppress(Exception):
                self._feedback.play("transcribe_done")

    def _process_chunk(self, item: _ChunkItem) -> None:
        """Decode one chunk of an aggregated paste-mode recording.

        Flush chunks (``final=False``) are transcribed as they arrive so
        decoding overlaps the recording, but their segments are only
        accumulated — nothing reaches the cursor. The final chunk (the tail
        captured at key release) restores every segment's absolute position
        in the recording via ``offset_seconds``, formats the whole utterance,
        and pastes once.
        """
        if self._chunk_abort is not item.abort:
            # First chunk of a new recording. Any leftover segments belong to
            # a recording whose final item never arrived (cancelled while
            # queued); drop them.
            self._chunk_abort = item.abort
            self._chunk_segments = []
        if item.abort.is_set():
            self._chunk_segments = []
            return
        accumulated = len(self._chunk_segments)
        if item.samples.shape[0] > 0:
            log.info(
                "session: processing %s chunk (%d samples, offset %.1fs)",
                "final" if item.final else "flush",
                item.samples.shape[0],
                item.offset_seconds,
            )
            future = self._worker.submit(item.samples, cancel_event=item.abort)
            try:
                result = future.result()
            except CancelledError:
                log.info("session: chunk transcription cancelled")
                self._chunk_segments = []
                return
            except Exception as exc:
                # Best effort: keep what already decoded; the final assembly
                # pastes whatever survived.
                log.error("session: chunk transcription failed: %s", exc)
                result = None
            if result is not None:
                for seg in result.segments:
                    if seg.no_speech_prob >= self._cfg.asr.silence_threshold:
                        log.info("session: skipping probable-silence segment")
                        log.debug("session: silence segment %r", seg.text)
                        continue
                    if not seg.text.strip():
                        continue
                    self._chunk_segments.append(
                        SegmentInfo(
                            start=seg.start + item.offset_seconds,
                            end=seg.end + item.offset_seconds,
                            text=seg.text,
                            no_speech_prob=seg.no_speech_prob,
                        )
                    )
        if not item.final:
            if len(self._chunk_segments) > accumulated and not self._stop_event.is_set():
                with contextlib.suppress(Exception):
                    self._feedback.play("segment")
            return
        segments = self._chunk_segments
        self._chunk_segments = []
        self._chunk_abort = None
        if item.abort.is_set():
            log.info("session: aggregated utterance discarded after cancel")
            return
        if not segments:
            log.info("session: silence detected, skipping output")
            if not self._stop_event.is_set():
                with contextlib.suppress(Exception):
                    self._feedback.play("error")
            return
        self._utterances_processed += 1
        text = self._formatter.format_batch(segments)
        # Full transcripts go to the log file only at DEBUG (privacy).
        log.info("session: transcript received (%d chars)", len(text))
        log.debug("session: transcript %r", text)
        if self._cfg.clipboard.enabled and self._caps.has_wl_copy:
            try:
                self._clipboard.copy(text)
            except Exception as exc:
                log.error("session: clipboard.copy raised: %s", exc)
        if self._caps.has_paste_trigger:
            try:
                self._injector.paste()
            except Exception as exc:
                log.error("session: injector.paste raised: %s", exc)
        if not self._stop_event.is_set():
            with contextlib.suppress(Exception):
                self._feedback.play("transcribe_done")

    def _drain(self, samples: np.ndarray) -> None:
        log.info("session: draining in-flight utterance on shutdown")
        if self._aggregate_chunks:
            # The recording's flushed chunks are already queued under
            # _recording_abort; the tail must join them so the shutdown paste
            # covers the whole utterance.
            self._utterance_queue.put(
                _ChunkItem(
                    samples,
                    self._recording_abort,
                    self._cancel_generation,
                    self._flushed_seconds,
                    final=True,
                )
            )
            return
        self._utterance_queue.put((samples, "ptt", threading.Event(), self._cancel_generation))
