# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-utterance orchestrator that wires all components together."""

from __future__ import annotations

import collections
import contextlib
import logging
import queue
import threading
import time
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from stenographer.asr.model import SegmentInfo
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
        self._utterances_processed = 0

        self._utterance_queue: queue.Queue[tuple[np.ndarray, Literal["ptt", "toggle"]] | None]
        self._utterance_queue = queue.Queue()
        self._processor: threading.Thread | None = None
        self._processing_times: collections.deque[float] = collections.deque(maxlen=10)
        self._sample_rate = cfg.audio.sample_rate
        # Mid-recording silence flushing only applies to the PTT/toggle daemon.
        # In one-shot mode the processor tears the session down after the first
        # queued item, which would truncate dictation at the first pause.
        self._silence_detection = cfg.audio.silence_detection and not one_shot

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
            samples, mode = item
            remaining = self._utterance_queue.qsize()
            if remaining > 0:
                log.info("session: processing utterance (%d queued)", remaining)
            t0 = time.monotonic()
            self._process(samples, mode)
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

    def on_recording_start(self) -> None:
        with self._lock:
            if self._stop_event.is_set():
                return
            if self._recording:
                log.warning("session: on_recording_start while already recording")
                return
            self._recording = True
            try:
                is_lazy_first = self._cfg.asr.mode == "lazy" and not self._worker.is_model_loaded()
                if is_lazy_first:
                    self._worker.ensure_model_loaded(
                        on_loaded=self._on_model_loaded,
                        on_unloaded=self._on_model_unloaded,
                    )
                    self._on_model_loading()
                self._recorder.start(
                    on_segment=self._enqueue_flush_segment if self._silence_detection else None
                )
                log.info("session: recording started")
                if not is_lazy_first and self._notification is not None:
                    self._notification.show_listening()
            except Exception as exc:
                self._recording = False
                log.error("session: recorder.start failed: %s", exc)

    def on_recording_stop(self, mode: Literal["ptt", "toggle"]) -> None:
        with self._lock:
            if not self._recording:
                log.warning("session: on_recording_stop with no active recording")
                return
            self._recording = False
            try:
                samples = self._recorder.stop()
            except Exception as exc:
                log.error("session: recorder.stop failed: %s", exc)
                if self._one_shot:
                    self._stop_event.set()
                return
        log.info("session: recording stopped, %d samples captured", samples.shape[0])
        if self._silence_detection and samples.shape[0] == 0:
            # Nothing left after the final flush; the spoken chunks were already
            # enqueued mid-recording. Skip the empty tail to avoid a stray cue.
            log.info("session: no trailing audio after final flush, nothing to queue")
            if self._notification is not None:
                if self._utterance_queue.qsize() > 0:
                    self._notification.show_transcribing()
                else:
                    self._notification.hide()
            return
        self._utterance_queue.put((samples, mode))
        if self._notification is not None:
            self._notification.show_transcribing()
        queue_depth = self._utterance_queue.qsize()
        if queue_depth > 1:
            log.info("session: %d utterance(s) queued for transcription", queue_depth)
        if self._one_shot:
            pass  # processor thread sets _stop_event after processing

    def _enqueue_flush_segment(self, samples: np.ndarray) -> None:
        """Enqueue a segment flushed mid-recording on a silence gap.

        Called from the recorder's PortAudio callback thread; it only touches
        the thread-safe utterance queue, so it takes no lock. ``mode`` is inert
        (logging only) and cannot be known before key release, so flushes are
        tagged ``"ptt"``.
        """
        self._utterance_queue.put((samples, "ptt"))

    def on_toggle_off(self) -> None:
        self.on_recording_stop("toggle")

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

    def _process(self, samples: np.ndarray, mode: Literal["ptt", "toggle"]) -> None:
        log.info("session: processing %d samples (mode=%s)", samples.shape[0], mode)

        segment_queue: queue.Queue[SegmentInfo | None] = queue.Queue()
        future = self._worker.submit(samples, on_segment=segment_queue.put)
        # The None sentinel unblocks the loop when transcription finishes
        # (all segments are emitted before the future resolves).
        future.add_done_callback(lambda _f: segment_queue.put(None))

        paste_mode = self._cfg.output.injection_method == "paste"

        injected_text = ""
        while True:
            seg = segment_queue.get()
            if seg is None:
                break
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
        except Exception as exc:
            log.error("session: transcription failed: %s", exc)
            if not self._stop_event.is_set():
                with contextlib.suppress(Exception):
                    self._feedback.play("error")
            return
        self._utterances_processed += 1
        text = result.text
        # Full transcripts go to the log file only at DEBUG (privacy).
        log.info("session: transcript received (%d chars)", len(text))
        log.debug("session: transcript %r", text)
        if result.segments and all(
            seg.no_speech_prob >= self._cfg.asr.silence_threshold for seg in result.segments
        ):
            log.info("session: silence detected, skipping output")
            if not self._stop_event.is_set():
                with contextlib.suppress(Exception):
                    self._feedback.play("error")
            return
        if not text or not text.strip():
            log.info("session: empty transcript, skipping output")
            if not self._stop_event.is_set():
                with contextlib.suppress(Exception):
                    self._feedback.play("error")
            return
        if paste_mode:
            # Copy to clipboard, then simulate Ctrl+V
            if self._cfg.clipboard.enabled and self._caps.has_wl_copy:
                try:
                    self._clipboard.copy(text)
                except Exception as exc:
                    log.error("session: clipboard.copy raised: %s", exc)
            if self._caps.has_wtype:
                try:
                    self._injector.paste()
                except Exception as exc:
                    log.error("session: injector.paste raised: %s", exc)
        else:
            if self._caps.has_wtype and not injected_text.strip():
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

    def _drain(self, samples: np.ndarray) -> None:
        log.info("session: draining in-flight utterance on shutdown")
        self._utterance_queue.put((samples, "ptt"))
