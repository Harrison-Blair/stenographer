# SPDX-License-Identifier: GPL-3.0-or-later
"""The single owner of recording, utterance lifecycle, and synchronization."""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from typing import TYPE_CHECKING

from stenographer.lib.audio.recorder import Recorder
from stenographer.lib.contracts.null_status_sink import NullStatusSink
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.contracts.publication import should_publish_state
from stenographer.lib.contracts.status_sink import StatusSink
from stenographer.lib.daemon.feedback import _play_cue, _publish_loading_activity, _publish_status
from stenographer.lib.daemon.outcome import Outcome
from stenographer.lib.daemon.pipeline import UtterancePipeline
from stenographer.lib.daemon.policy import (
    can_start,
    cancel_action,
    cancel_state,
    edge_handlers,
    hybrid_release_action,
    ignored_edge_reason,
    max_duration_applies,
    toggle_action,
)
from stenographer.lib.daemon.telemetry import UtteranceTelemetry
from stenographer.lib.delivery.deliverer import Deliverer
from stenographer.lib.logging.pipeline import fmt_event, log_failure, set_utterance
from stenographer.lib.platform import current_platform
from stenographer.lib.sounds.feedback import Feedback
from stenographer.lib.transcribe.errors import WorkerError
from stenographer.lib.transcribe.pipeline import apply_capture, log_summary
from stenographer.lib.transcribe.utterance_record import UtteranceRecord
from stenographer.lib.transcribe.worker import Worker

if TYPE_CHECKING:
    import numpy as np

    from stenographer.lib.audio.records import CaptureStats
    from stenographer.lib.config.models import Config
    from stenographer.lib.platform.notifier import Notifier
    from stenographer.lib.platform.platform import Platform

log = logging.getLogger("stenographer.lib.daemon")

_PIPELINE_JOIN_SECONDS = 30.0


class Daemon:
    """Holds the cross-component PTT state and runs the utterance pipeline.

    Built via :meth:`build`, which resolves the listener↔deliverer cycle by
    constructing the listener (whose ``wait_binding_released`` the deliverer
    needs) before the deliverer.
    """

    def __init__(
        self,
        *,
        cfg: Config,
        feedback: Feedback,
        notifier: Notifier,
        worker: Worker,
        recorder: Recorder,
        status: StatusSink | None = None,
    ) -> None:
        self._cfg = cfg
        self._feedback = feedback
        self._notifier = notifier
        self._worker = worker
        self._recorder = recorder
        self._status = status if status is not None else NullStatusSink()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._recording = False
        self._busy = False
        self._overlay_state = OverlayState.HIDDEN
        # Also the stale-timer generation: a max-duration timer applies only to
        # the utterance it was armed for, and each accepted start is a new one.
        self._utterance_id = 0
        self._cancelled_utterance: int | None = None
        self._record: UtteranceRecord | None = None
        self._max_timer: threading.Timer | None = None
        self._warmup_thread: threading.Thread | None = None
        self._pipeline_thread: threading.Thread | None = None
        self._listener = None
        self._deliverer: Deliverer | None = None
        self._platform: Platform | None = None
        self._telemetry = UtteranceTelemetry()
        self._pipeline: UtterancePipeline | None = None
        self._capture_lock = threading.Lock()
        self._model_load_started_at: float | None = None
        self._model_load_utterance: int | None = None

    @classmethod
    def build(
        cls,
        cfg: Config,
        *,
        clipboard_backend: str,
        status: StatusSink | None = None,
        platform: Platform | None = None,
    ) -> Daemon:
        from stenographer.lib.config.paths import resolve_config_path
        from stenographer.lib.hotkey.binding import parse_binding

        plat = platform if platform is not None else current_platform()
        feedback = Feedback(
            cfg=cfg.feedback,
            player=plat.cue_player(),
            config_dir=resolve_config_path(create_parent=False).parent,
        )
        notifier = plat.notifier()
        status = status if status is not None else NullStatusSink()
        daemon_ref: Daemon | None = None

        def on_model_loading() -> None:
            if daemon_ref is not None:
                daemon_ref._on_model_loading()

        def on_model_loading_finished() -> None:
            if daemon_ref is not None:
                daemon_ref._on_model_loading_finished()

        def on_transcribing() -> None:
            if daemon_ref is not None:
                daemon_ref._publish_state(OverlayState.TRANSCRIBING)

        worker = Worker(
            cfg.asr,
            transport=plat.asr_transport(),
            on_model_loading=on_model_loading,
            on_model_loading_finished=on_model_loading_finished,
            on_transcribing=on_transcribing,
        )
        recorder = Recorder(
            device=cfg.audio.input_device,
            max_seconds=cfg.audio.max_recording_seconds,
            on_block=status.audio_block,
        )
        daemon = cls(
            cfg=cfg,
            feedback=feedback,
            notifier=notifier,
            worker=worker,
            recorder=recorder,
            status=status,
        )
        daemon_ref = daemon
        on_start, on_stop = edge_handlers(daemon, cfg.hotkey.mode)
        keys = plat.keys()
        cancel = (
            parse_binding(cfg.hotkey.cancel_binding, keys)
            if cfg.hotkey.cancel_binding is not None
            else frozenset()
        )
        log.info("hotkey: configured mode=%s", cfg.hotkey.mode)
        listener = plat.hotkey_listener(
            chord=parse_binding(cfg.hotkey.binding, keys),
            device=cfg.hotkey.device,
            on_start=on_start,
            on_stop=on_stop,
            lock=threading.RLock(),
            cancel=cancel,
            on_cancel=daemon.on_cancel,
        )
        deliverer = Deliverer(
            keyboard=plat.key_injector(),
            wait_released=listener.wait_binding_released,
            copy=plat.clipboard_writer(clipboard_backend),
        )
        daemon._platform = plat
        daemon._listener = listener
        daemon._deliverer = deliverer
        daemon._pipeline = UtterancePipeline(
            min_speech_rms=cfg.audio.min_speech_rms,
            worker=worker,
            deliverer=deliverer,
            telemetry=daemon._telemetry,
            publish_state=daemon._publish_state,
            fail=daemon._fail,
            play_cue=lambda name: _play_cue(feedback, name),
            cancelled=daemon._cancel_pending,
            cancel_state=lambda: cancel_state(shutting_down=daemon._stop_event.is_set()),
        )
        return daemon

    def _publish_state(self, state: OverlayState) -> None:
        """Serialize display state and suppress duplicate helper updates."""
        with self._lock:
            if not should_publish_state(self._overlay_state, state):
                return
            self._overlay_state = state
            _publish_status(self._status, state)

    def _fail(self, notify_msg: str) -> None:
        """Announce a failed phase on every user-facing channel at once.

        The error pill, the error cue and the notification always travel
        together; each call site keeps its own log line, since the level and
        the recorded event differ per phase.
        """
        self._publish_state(OverlayState.ERROR)
        _play_cue(self._feedback, "error")
        self._notifier.error(notify_msg)

    def _publish_cancelled(self) -> None:
        """Show an immediate cancellation result without treating it as a failure."""
        self._publish_state(cancel_state(shutting_down=self._stop_event.is_set()))
        _play_cue(self._feedback, "error")

    def _cancel_pending(self) -> bool:
        """Return whether the current utterance has been cancelled or shutdown began."""
        return self._stop_event.is_set() or self._cancelled_utterance == self._utterance_id

    def _on_model_loading(self) -> None:
        """Publish cold-load activity without replacing the current pill."""
        with self._lock:
            if self._stop_event.is_set():
                return
            self._model_load_started_at = time.perf_counter()
            self._model_load_utterance = self._utterance_id
            _publish_loading_activity(self._status, True)

    def _on_model_loading_finished(self) -> None:
        """Remove display activity after either model-ready or load failure."""
        with self._lock:
            if (
                self._record is not None
                and self._record.utt == self._model_load_utterance
                and self._model_load_started_at is not None
            ):
                self._record.load_ms = (time.perf_counter() - self._model_load_started_at) * 1000
            self._model_load_started_at = None
            self._model_load_utterance = None
            _publish_loading_activity(self._status, False)

    def _warm_model(self, utterance: int) -> None:
        try:
            self._worker.warmup(utterance)
        except WorkerError as exc:
            if not self._stop_event.is_set():
                # safe=False: a WorkerError round-trips the ASR child's own
                # ``classify_error`` detail, whose inference branch can quote
                # decoder text derived from the audio.
                log_failure(log, logging.WARNING, "worker: warmup_failed", exc, safe=False)

    def _start_model_warmup(self, utterance: int) -> None:
        thread = threading.Thread(
            target=self._warm_model,
            args=(utterance,),
            name="stenographer-model-warmup",
            daemon=True,
        )
        try:
            thread.start()
        except RuntimeError as exc:
            log_failure(log, logging.WARNING, "worker: warmup_start_failed", exc, safe=True)
            return
        self._warmup_thread = thread

    def on_toggle_press(self) -> None:
        """Toggle and hybrid modes: one press starts a recording, the next press stops it."""
        with self._lock:
            action = toggle_action(
                recording=self._recording,
                busy=self._busy,
                stopping=self._stop_event.is_set(),
            )
            if action is None and self._busy and self._record is not None:
                self._record.ignored_busy_presses += 1
        if action == "start":
            self.on_key_down()
        elif action == "stop":
            self.on_key_up()

    def on_hybrid_release(self) -> None:
        """Hybrid mode: a tap latches the recording, a held press ends it.

        The press already ran through ``on_toggle_press``; only a live
        recording's own release decides anything, so the release that follows
        the stopping press — or a refused one — is ignored. The max-duration
        timer is armed here rather than at the press, for the remainder of the
        window, because a latched recording is the only hybrid state with no
        key held to end it; a long hold behaves exactly like ``hold`` mode.
        """
        with self._lock:
            record = self._record
            if not self._recording or record is None:
                log.debug(fmt_event("hotkey", "hybrid_release_ignored", reason="not_recording"))
                return
            held = time.perf_counter() - record.started_at
            action = hybrid_release_action(
                held_seconds=held,
                threshold=self._cfg.hotkey.hybrid_threshold_seconds,
            )
            log.debug(
                fmt_event("hotkey", "hybrid_release", action=action, held_ms=round(held * 1000))
            )
            generation = self._utterance_id
            if action != "stop":
                self._arm_max_timer(record.started_at)
        if action == "stop":
            self.on_key_up(generation=generation)

    def _on_max_duration(self, generation: int) -> None:
        """Timer thread: end a toggle or latched-hybrid recording exactly as a
        second press would."""
        with self._lock:
            if not max_duration_applies(generation, self._utterance_id, self._recording):
                log.debug(fmt_event("hotkey", "max_duration_ignored", reason="stale_or_idle"))
                return
            log.info(
                "recorder: max_duration_stop seconds=%d",
                self._cfg.audio.max_recording_seconds,
            )
        self.on_key_up(generation=generation)

    def _arm_max_timer(self, started_at: float) -> None:
        """Arm the cap timer for what is left of this utterance's window.

        The window runs from the press in every mode, so a hybrid tap that
        latched gets ``max_recording_seconds`` minus the time it was already
        held: this timer and the recorder's own sample cap then end the
        recording at the same instant. Called with the state lock held; the
        press instant is passed in rather than read off ``self._record``, which
        is optional only in the type, never at these call sites.
        """
        remaining = self._cfg.audio.max_recording_seconds - (time.perf_counter() - started_at)
        timer = threading.Timer(
            max(0.0, remaining), self._on_max_duration, args=(self._utterance_id,)
        )
        timer.name = "stenographer-max-duration"
        timer.daemon = True
        timer.start()
        self._max_timer = timer

    def _cancel_max_timer(self) -> None:
        timer = self._max_timer
        if timer is not None:
            timer.cancel()
            self._max_timer = None

    def on_key_down(self) -> None:
        with self._lock:
            if not can_start(self._recording, self._busy, self._stop_event.is_set()):
                if self._busy and self._record is not None:
                    self._record.ignored_busy_presses += 1
                log.debug(
                    fmt_event(
                        "hotkey",
                        "key_down_ignored",
                        reason=ignored_edge_reason(
                            self._recording, self._busy, self._stop_event.is_set()
                        ),
                    )
                )
                return
            self._utterance_id += 1
            set_utterance(self._utterance_id)
            started_at = time.perf_counter()
            self._record = UtteranceRecord(
                utt=self._utterance_id,
                started_at=started_at,
                mode=self._cfg.hotkey.mode,
                source="hotkey",
            )
            self._telemetry.start(self._record)
            self._worker.hold_model()
            try:
                self._recorder.start()
            except Exception as exc:
                log_failure(log, logging.ERROR, "recorder: failed", exc, safe=True, phase="start")
                self._recorder.close()
                self._worker.release_model()
                self._record.failure = "start_failed"
                self._emit_summary(self._take_record(Outcome.ERROR.name))
                self._fail("could not start recording")
                return
            self._recording = True
            if self._cfg.hotkey.mode == "toggle":
                self._arm_max_timer(started_at)
            self._publish_state(OverlayState.RECORDING)
            _play_cue(self._feedback, "record_start")
            self._start_model_warmup(self._utterance_id)

    def on_cancel(self) -> None:
        """Abandon the active recording or pipeline at the next safe boundary."""
        with self._lock:
            action = cancel_action(recording=self._recording, busy=self._busy)
            if action is None:
                log.debug(fmt_event("hotkey", "cancel_ignored"))
                return
            generation = self._utterance_id
            self._cancelled_utterance = generation
            if action == "pipeline":
                self._publish_cancelled()
        if action == "recording":
            self._cancel_recording(generation)

    def _cancel_recording(self, generation: int) -> None:
        """Finalize a live capture as cancelled while retaining the recorder."""
        with self._capture_lock:
            with self._lock:
                if generation != self._utterance_id or not self._recording:
                    return
                self._recording = False
                self._busy = False
                if self._record is not None:
                    self._record.stopped_at = time.perf_counter()
                self._cancel_max_timer()
            try:
                self._recorder.stop()
            except Exception as exc:
                log_failure(log, logging.DEBUG, "recorder: cancel_finalize_failed", exc, safe=True)
            with self._lock:
                self._apply_capture(self._recorder.last_capture)
                self._telemetry.checkpoint(self._record, "secured_capture")
                self._worker.release_model()
                self._publish_cancelled()
                self._emit_summary(self._take_record("CANCELLED"))

    def on_key_up(self, *, generation: int | None = None) -> None:
        with self._lock:
            if generation is not None and generation != self._utterance_id:
                return
            if not self._recording:
                log.debug(fmt_event("hotkey", "key_up_ignored", reason="not_recording"))
                return
            self._recording = False
            self._busy = True
            if self._record is not None:
                self._record.stopped_at = time.perf_counter()
            self._cancel_max_timer()
            # The pill stays up across the release: it is the only sign that
            # the tool is still working until the paste lands, so the release
            # moves it to TRANSCRIBING rather than hiding it. Every exit from
            # the pipeline below publishes HIDDEN or ERROR itself.
            if not self._cancel_pending():
                self._publish_state(OverlayState.TRANSCRIBING)
        # Callback-clock reduction and sample finalization are outside lifecycle locks.
        with self._capture_lock:
            try:
                samples = self._recorder.stop()
            except Exception as exc:
                log_failure(log, logging.ERROR, "recorder: failed", exc, safe=True, phase="stop")
                self._recorder.close()
                with self._lock:
                    self._busy = False
                    if self._record is not None:
                        self._record.failure = "stop_failed"
                    self._fail("recording failed; audio was discarded")
                    self._worker.release_model()
                    self._emit_summary(self._take_record(Outcome.ERROR.name))
                return
            with self._lock:
                self._apply_capture(self._recorder.last_capture)
                self._telemetry.checkpoint(self._record, "secured_capture")
                if self._cancel_pending():
                    self._busy = False
                    self._worker.release_model()
                    expected_state = cancel_state(shutting_down=self._stop_event.is_set())
                    if self._overlay_state is not expected_state:
                        self._publish_cancelled()
                    self._emit_summary(self._take_record("CANCELLED"))
                    return
                _play_cue(self._feedback, "record_stop")
                thread = threading.Thread(
                    target=self._run_pipeline,
                    args=(samples,),
                    name="stenographer-pipeline",
                    daemon=True,
                )
                self._pipeline_thread = thread
                thread.start()

    def _apply_capture(self, stats: CaptureStats | None) -> None:
        """Fold the recorder's own numbers into the utterance record."""
        apply_capture(self._record, stats)

    def _take_record(self, outcome: str) -> UtteranceRecord | None:
        """Detach the in-flight record and stamp its outcome."""
        record, self._record = self._record, None
        if record is not None:
            record.outcome = outcome
        return record

    def _emit_summary(self, record: UtteranceRecord | None) -> None:
        """Close out one utterance: its single INFO line, then clear ``utt``.

        Called with the state lock held. Logging is a queue put, not process
        I/O — the listener thread owns the sinks — and holding the lock is what
        keeps a fast re-press from allocating the next id and clearing the
        stamp between this line and the record it belongs to.
        """
        if record is None:
            return
        record.total_ms = (time.perf_counter() - record.started_at) * 1000.0
        self._telemetry.finish(record)
        log_summary(record)
        set_utterance(None)

    def _run_pipeline(self, samples: np.ndarray) -> None:
        """Run one utterance and finalize it under the lifecycle lock."""
        record = self._record
        outcome_name = Outcome.ERROR.name
        try:
            assert self._pipeline is not None
            outcome_name = self._pipeline.run(samples, utterance=self._utterance_id, record=record)
        finally:
            with self._lock:
                self._worker.release_model()
                self._busy = False
                outcome = record.outcome if record is not None else None
                self._emit_summary(self._take_record(outcome or outcome_name))

    def run(self) -> None:
        """Start the listener and block until stopped."""
        if self._listener is None:
            raise RuntimeError("daemon.run() before build()")
        self._telemetry.open(self._cfg, self._platform, pids=lambda: self._worker.process_ids)
        self._listener.start()
        log.info("daemon: running pid=%d", os.getpid())
        self._stop_event.wait()

    def request_stop(self) -> None:
        """Signal-safe stop request: set the stop event only."""
        self._stop_event.set()

    def stop(self) -> None:
        """Idempotent teardown. Safe before ``run`` and safe to call twice."""
        self._stop_event.set()
        if self._listener is not None:
            with contextlib.suppress(Exception):
                self._listener.stop()
        with self._capture_lock:
            with self._lock:
                was_recording = self._recording
                self._recording = False
                self._cancel_max_timer()
                if was_recording and self._record is not None:
                    self._record.stopped_at = time.perf_counter()
            if was_recording:
                try:
                    self._recorder.stop()
                except Exception as exc:
                    log_failure(
                        log, logging.DEBUG, "recorder: cancel_finalize_failed", exc, safe=True
                    )
                else:
                    with self._lock:
                        self._apply_capture(self._recorder.last_capture)
                        self._telemetry.checkpoint(self._record, "secured_capture")
            self._recorder.close()
        with contextlib.suppress(Exception):
            self._worker.shutdown()
        warmup = self._warmup_thread
        if warmup is not None:
            warmup.join(timeout=_PIPELINE_JOIN_SECONDS)
        thread = self._pipeline_thread
        if thread is not None:
            thread.join(timeout=_PIPELINE_JOIN_SECONDS)
        if self._deliverer is not None:
            with contextlib.suppress(Exception):
                self._deliverer.close()
        with contextlib.suppress(Exception):
            self._feedback.close()
        with self._lock:
            # A recording torn down mid-flight still owes the log its one line;
            # without this a press-then-stop leaves an utterance unaccounted for.
            self._emit_summary(self._take_record("CANCELLED"))
        self._publish_state(OverlayState.HIDDEN)
        self._telemetry.close()
        set_utterance(None)
