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

from stenographer.asr.streaming import StreamingTranscriber
from stenographer.asr.worker import CancelledError
from stenographer.errors import notify_failure
from stenographer.live import IncrementalDriver
from stenographer.output.formatter import HeuristicFormatter

if TYPE_CHECKING:
    from stenographer.asr.worker import Worker
    from stenographer.audio.capture import Recorder
    from stenographer.audio.feedback import Feedback
    from stenographer.capabilities import Capabilities
    from stenographer.config import Config
    from stenographer.hotkey.listener import HotkeyListener
    from stenographer.output.clipboard import ClipboardManager
    from stenographer.output.inject import Injector
    from stenographer.visualizer import StatusIndicator

log = logging.getLogger(__name__)

# A queued batch recording, optionally tagged with which hotkey triggered it
# (added by FTHR-004; the untagged 4-tuple form defaults to "dictate").
_BatchItem = tuple[np.ndarray, Literal["ptt", "toggle"], threading.Event, int]
_TaggedBatchItem = tuple[
    np.ndarray, Literal["ptt", "toggle"], threading.Event, int, Literal["dictate"]
]


@dataclass
class _LiveItem:
    """Utterance-queue entry for an incrementally decoded recording."""

    streamer: IncrementalDriver
    generation: int
    preview_generation: int


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
        notification: StatusIndicator | None = None,
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

        self._utterance_queue: queue.Queue[_BatchItem | _TaggedBatchItem | _LiveItem | None]
        self._utterance_queue = queue.Queue()
        self._processor: threading.Thread | None = None
        self._processing_times: collections.deque[float] = collections.deque(maxlen=10)
        self._sample_rate = cfg.audio.sample_rate
        self._formatter = HeuristicFormatter(
            cfg.formatting, append_trailing_space=cfg.output.append_trailing_space
        )
        self._preview_generation = 0
        # The incremental driver of the recording currently capturing audio. Popped by
        # the stop/discard path that ends that recording, so a following
        # recording can never be routed into a previous utterance's streamer
        # that is still finishing its final decode.
        self._recording_streamer: IncrementalDriver | None = None
        # The driver that has not yet finished processing (its final decode
        # may outlive the recording); cancel_all uses it to wake the driver.
        # Cleared by _run_incremental when the drive completes.
        self._live_streamer: IncrementalDriver | None = None

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
    def notification(self) -> StatusIndicator | None:
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
                        self._clear_preview(item.preview_generation)
                    continue
                self._active_abort = abort
            remaining = self._utterance_queue.qsize()
            if remaining > 0:
                log.info("session: processing utterance (%d queued)", remaining)
            t0 = time.monotonic()
            if isinstance(item, _LiveItem):
                self._run_incremental(item.streamer, item.preview_generation)
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
            streamer = self._recording_streamer
            self._recording_streamer = None
            try:
                samples = self._recorder.stop()
            except Exception as exc:
                log.error("session: recorder.stop during shutdown failed: %s", exc)
                if streamer is not None:
                    # Unblock the queued live item's driver so the processor
                    # thread can reach the sentinel and the join below can
                    # complete, rather than timing out after 60s.
                    streamer.abort.set()
                    streamer.signal_abort()
            else:
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
            self._preview_generation += 1
            preview_generation = self._preview_generation
            self._recording_source = source
            self._recording_abort = threading.Event()
            try:
                is_lazy_first = self._cfg.asr.mode == "lazy" and not self._worker.is_model_loaded()
                if is_lazy_first:
                    self._worker.ensure_model_loaded(
                        on_loaded=self._on_model_loaded,
                        on_unloaded=self._on_model_unloaded,
                    )
                    self._on_model_loading()
                if self._notification is not None:
                    self._notification.clear_preview()
                streamer = IncrementalDriver(
                    cfg=self._cfg,
                    recorder=self._recorder,
                    worker=self._worker,
                    transcriber=StreamingTranscriber(agreement_n=self._cfg.incremental.agreement_n),
                    formatter=HeuristicFormatter(
                        self._cfg.formatting,
                        append_trailing_space=self._cfg.output.append_trailing_space,
                    ),
                    abort=self._recording_abort,
                    on_preview=lambda stable, provisional: self._publish_preview(
                        preview_generation, stable, provisional
                    ),
                )
                self._recorder.start(
                    on_partial=streamer.signal_partial,
                    min_partial_seconds=self._cfg.incremental.min_chunk_seconds,
                )
                self._recording_streamer = streamer
                self._live_streamer = streamer
                self._utterance_queue.put(
                    _LiveItem(streamer, self._cancel_generation, preview_generation)
                )
                log.info("session: recording started")
                if not is_lazy_first and self._notification is not None:
                    self._notification.show_listening()
            except Exception as exc:
                self._recording = False
                self._preview_generation += 1
                log.error("session: recorder.start failed: %s", exc)
                # The failure may come after the recorder started and the live
                # item was queued (e.g. the indicator raised). Unwind both:
                # a stranded driver blocks the processor thread forever on its
                # signal queue -- no final can arrive, since on_recording_stop
                # early-returns while _recording is False -- and every later
                # utterance is then silently never transcribed.
                streamer = self._recording_streamer
                self._recording_streamer = None
                if streamer is not None:
                    streamer.abort.set()
                    streamer.signal_abort()
                if self._recorder.is_active:
                    try:
                        self._recorder.stop()
                    except Exception as stop_exc:
                        log.error("session: recorder.stop after failed start: %s", stop_exc)
                if self._notification is not None:
                    with contextlib.suppress(Exception):
                        self._notification.clear_preview()

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
                if streamer is not None:
                    # The live item for this recording is already queued and its
                    # driver is blocked on the signal queue. It was popped above,
                    # so nothing else can ever signal it -- without this the
                    # processor thread blocks forever and every later utterance
                    # is silently never transcribed.
                    streamer.abort.set()
                    streamer.signal_abort()
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

    def _run_incremental(self, streamer: IncrementalDriver, preview_generation: int) -> None:
        """Finalize one incremental utterance and deliver its transcript once."""
        text: str | None = None
        failed = False
        try:
            text = streamer.run()
        except Exception as exc:
            failed = True
            log.error("session: incremental driver failed: %s", exc)
            if not self._stop_event.is_set():
                with contextlib.suppress(Exception):
                    self._feedback.play("error")
        finally:
            with self._lock:
                if self._live_streamer is streamer:
                    self._live_streamer = None
            self._clear_preview(preview_generation)
        if streamer.abort.is_set() or failed:
            return
        if not text:
            log.info("session: incremental utterance produced no text")
            if not self._stop_event.is_set():
                with contextlib.suppress(Exception):
                    self._feedback.play("error")
            return
        delivered = self._deliver_final(text)
        if not delivered:
            if not self._stop_event.is_set():
                with contextlib.suppress(Exception):
                    self._feedback.play("error")
            return
        self._utterances_processed += 1
        if not self._stop_event.is_set():
            with contextlib.suppress(Exception):
                self._feedback.play("transcribe_done")

    def _publish_preview(self, generation: int, stable: str, provisional: str) -> None:
        """Publish only if this recording still owns the HUD preview."""
        with self._lock:
            if generation != self._preview_generation or self._notification is None:
                return
            try:
                self._notification.show_preview(stable, provisional)
            except Exception as exc:
                log.debug("session: preview update failed: %s", exc)

    def _clear_preview(self, generation: int) -> None:
        with self._lock:
            if generation != self._preview_generation or self._notification is None:
                return
            with contextlib.suppress(Exception):
                self._notification.clear_preview()

    def _refresh_notification(self) -> None:
        """Show the transcribing indicator if work remains queued, else hide it."""
        if self._notification is None:
            return
        if self._utterance_queue.qsize() > 0:
            self._notification.show_transcribing()
        else:
            self._notification.hide()

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
            self._preview_generation += 1
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
            if self._notification is not None:
                with contextlib.suppress(Exception):
                    self._notification.clear_preview()
            self._refresh_notification()

    def cancel_all(self) -> None:
        """Cancel everything: active recording, queued utterances, and the
        in-flight transcription. Already-delivered utterances are not undone.

        Wired to the cancel chord (main hotkey held + cancel key). Runs on
        the listener dispatch thread, which already holds ``_lock`` (RLock).
        """
        with self._lock:
            log.info("session: cancel requested")
            self._cancel_generation += 1
            self._preview_generation += 1
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
                # One suppress block per call: a raising clear_preview must not
                # skip hide(), which would leave 'Listening…' up forever.
                with contextlib.suppress(Exception):
                    self._notification.clear_preview()
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
        """Batch-decode a queued item and perform one final delivery.

        Daemon recordings use :class:`IncrementalDriver`; this path remains
        for explicit batch callers and deliberately shares the same delivery
        boundary.
        """
        log.info(
            "session: processing %d samples (mode=%s, source=%s)", samples.shape[0], mode, source
        )
        future = self._worker.submit(samples, cancel_event=abort)
        try:
            result = future.result()
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
        speech_segments = []
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
                # Drop probable-silence segments from final output.
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
        if result.segments:
            text = self._formatter.format_batch(speech_segments)
        if not self._deliver_final(text):
            if not self._stop_event.is_set():
                with contextlib.suppress(Exception):
                    self._feedback.play("error")
            return
        if not self._stop_event.is_set():
            with contextlib.suppress(Exception):
                self._feedback.play("transcribe_done")

    def _deliver_final(self, text: str) -> bool:
        """Apply the output cap once, then perform one focused-app delivery."""
        if not text:
            return False
        if self._cfg.output.injection_method == "clipboard_paste":
            # Uncapped on purpose: the cap bounds per-character wtype
            # synthesis, which pasting does not do. Here the clipboard is the
            # transport rather than a recovery copy, so capping before the copy
            # would drop the tail somewhere the user cannot reach it at all.
            return self._deliver_paste(text)

        max_chars = self._cfg.output.max_chars
        injected = text
        if len(text) > max_chars:
            log.warning("session: truncating transcript from %d to %d chars", len(text), max_chars)
            injected = text[:max_chars]

        delivered = False
        if self._caps.has_paste_trigger:
            try:
                # Incremental/batch formatters already applied whitespace and
                # trailing-space policy; raw avoids preparing it a second time.
                delivered = bool(self._injector.type_text(injected, raw=True))
            except Exception as exc:
                log.error("session: injector.type_text raised: %s", exc)
        if self._cfg.clipboard.enabled and self._caps.has_wl_copy:
            copied = False
            try:
                # The full transcript, not the capped one: the clipboard is the
                # recovery path for whatever the cap kept from being typed.
                # primary=True: this copy exists to be pasted by hand, and the
                # paste chord reads the primary selection in some clients --
                # populating only the regular clipboard would make Shift+Insert
                # paste the user's old mouse selection instead.
                copied = bool(self._clipboard.copy(text, primary=True))
            except Exception as exc:
                log.error("session: clipboard.copy raised: %s", exc)
            # Without a paste trigger the clipboard is the only transport left.
            # A successful copy still put the transcript within reach, so it is
            # a delivery -- otherwise every dictation on a machine without
            # wtype ends on the error cue.
            delivered = delivered or copied
        return delivered

    def _deliver_paste(self, text: str) -> bool:
        """Copy *text*, then fire the paste chord to deliver it at the cursor.

        The chord pastes whatever the clipboard currently holds, so it is
        fired only after a confirmed copy: on a failed copy it would paste
        the user's previous clipboard content into their document. Config
        validation guarantees clipboard.enabled in clipboard_paste mode, so
        there is no flag to honour here -- the clipboard is the transport.

        Returns True when the text reached the cursor. Callers must not play
        the success cue on a False: the clipboard is the only transport, so a
        failed copy means the utterance reached neither the cursor nor the
        clipboard and the user has nothing to recover.
        """
        if not self._caps.has_wl_copy:
            notify_failure("clipboard_paste mode requires wl-copy; nothing delivered")
            return False
        copied = False
        try:
            copied = self._clipboard.copy(text, primary=True)
        except Exception as exc:
            log.error("session: clipboard.copy raised: %s", exc)
        if not copied:
            notify_failure("clipboard copy failed; skipping paste to avoid pasting stale text")
            return False
        if not self._caps.has_paste_trigger:
            # The text is on the clipboard, so it is recoverable by hand, but
            # nothing reached the cursor -- not a success.
            log.error("session: no paste trigger available; transcript left on the clipboard")
            return False
        try:
            return bool(self._injector.paste())
        except Exception as exc:
            log.error("session: injector.paste raised: %s", exc)
            return False

    def _drain(self, samples: np.ndarray) -> None:
        log.info("session: draining in-flight utterance on shutdown")
        self._utterance_queue.put((samples, "ptt", threading.Event(), self._cancel_generation))
