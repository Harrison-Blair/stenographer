# SPDX-License-Identifier: GPL-3.0-or-later
"""The orchestrator: hotkey → record → transcribe → deliver (spec §5).

The single module holding cross-component state. One utterance at a time, no
queue: a start press during transcription is ignored (§5). Two hotkey modes:
``hold`` (push-to-talk, the default) maps key-down/key-up straight to
start/stop; ``toggle`` maps each press through ``toggle_action`` and ends a
forgotten recording via a generation-guarded ``audio.max_recording_seconds``
timer. An accepted start also warms the ASR model on a background thread while
capture remains authoritative. All state transitions are guarded by one lock so
a key event, a timer firing, and a pipeline completion cannot race. Pure policy
(``classify_pipeline``, ``can_start``, ``toggle_action``,
``max_duration_applies``) is the unit-testable surface; the single-instance
lock and signal handling come from the current :class:`~stenographer.platform.base.Platform`;
the wired daemon is exercised by real dictation (the M5 manual acceptance procedure).
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import sys
import threading
from enum import Enum, auto
from typing import TYPE_CHECKING, Literal

from stenographer.audio import Recorder, speech_gate_passes
from stenographer.delivery.deliver import Deliverer
from stenographer.delivery.feedback import Feedback
from stenographer.platform import current_platform
from stenographer.platform.base import SingleInstanceLockError
from stenographer.status import NullStatusSink, OverlayState, StatusSink, should_publish_state
from stenographer.transcribe.format import format_transcript
from stenographer.transcribe.worker import Worker, WorkerError

if TYPE_CHECKING:
    import numpy as np

    from stenographer.cli.doctor import Capabilities
    from stenographer.config import Config
    from stenographer.platform.base import Notifier, Platform

log = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_PIPELINE_JOIN_SECONDS = 30.0


def _ignore_edge() -> None:
    """Falling-edge sink for toggle mode: only presses drive the session."""


def _play_cue(feedback: Feedback, name: str) -> None:
    """Launch a cue without allowing player failure to break daemon state."""
    try:
        feedback.play(name)
    except Exception as exc:
        log.warning("feedback: cue_failed cue=%s error_type=%s", name, type(exc).__name__)


def _publish_status(status: StatusSink, state: OverlayState) -> None:
    """Enqueue fixed lifecycle metadata without allowing overlay failure through."""
    try:
        status.publish(state)
    except Exception as exc:
        log.warning(
            "overlay: publish_failed state=%s error_type=%s", state.value, type(exc).__name__
        )


def _publish_loading_activity(status: StatusSink, active: bool) -> None:
    try:
        status.loading_activity(active)
    except Exception as exc:
        log.warning(
            "overlay: loading_activity_failed active=%s error_type=%s",
            active,
            type(exc).__name__,
        )


class Outcome(Enum):
    SILENT = auto()
    DELIVERED = auto()
    ERROR = auto()


def classify_pipeline(
    *, gate_passed: bool, transcript_nonempty: bool, deliver_result: bool | None
) -> tuple[Outcome, str | None]:
    """Map a pipeline run to its outcome and optional error message. PURE.

    A failed energy gate or an empty transcript is success-shaped — no paste, no
    error cue (§4.7). Otherwise the delivery result decides: a False deliver on
    non-empty text is an error (deliver already withheld the chord on copy
    failure, §4.3), never treated as silent.
    """
    if not gate_passed:
        return (Outcome.SILENT, None)
    if not transcript_nonempty:
        return (Outcome.SILENT, None)
    if deliver_result:
        return (Outcome.DELIVERED, None)
    return (Outcome.ERROR, "could not copy transcript to clipboard")


def can_start(recording: bool, busy: bool, stopping: bool) -> bool:
    """Admit a new utterance only when idle (§5, one at a time). PURE."""
    return not (recording or busy or stopping)


def toggle_action(
    *, recording: bool, busy: bool, stopping: bool
) -> Literal["start", "stop"] | None:
    """Map a toggle-mode press edge to a session action. PURE.

    A press while recording always stops — even during shutdown, so a live
    capture is never stranded. Otherwise it starts only when fully idle
    (``can_start``); a press during transcription neither starts nor queues.
    """
    if recording:
        return "stop"
    if can_start(recording, busy, stopping):
        return "start"
    return None


def max_duration_applies(armed_generation: int, current_generation: int, recording: bool) -> bool:
    """Guard a fired max-duration timer against stale delivery. PURE.

    ``Timer.cancel()`` cannot stop a callback that already fired and is
    blocked on the state lock, so a timer armed for recording N could
    otherwise stop recording N+1. The timer only applies to the very
    recording it was armed for, and only while that recording is live.
    """
    return armed_generation == current_generation and recording


def startup_clipboard_backend(caps: Capabilities) -> str | None:
    """Gate daemon startup on doctor requirements and reuse its backend name. PURE."""
    from stenographer.cli import doctor

    if doctor.missing_required(caps):
        return None
    return caps.clipboard_backend


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
        self._session_generation = 0
        self._max_timer: threading.Timer | None = None
        self._warmup_thread: threading.Thread | None = None
        self._pipeline_thread: threading.Thread | None = None
        self._listener = None
        self._deliverer: Deliverer | None = None

    @classmethod
    def build(
        cls,
        cfg: Config,
        *,
        clipboard_backend: str,
        status: StatusSink | None = None,
        platform: Platform | None = None,
    ) -> Daemon:
        from stenographer.hotkey import parse_binding

        plat = platform if platform is not None else current_platform()
        feedback = Feedback(cfg=cfg.feedback, player=plat.cue_player())
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
        if cfg.hotkey.mode == "toggle":
            on_start, on_stop = daemon.on_toggle_press, _ignore_edge
        else:
            on_start, on_stop = daemon.on_key_down, daemon.on_key_up
        log.info("hotkey: mode=%s", cfg.hotkey.mode)
        listener = plat.hotkey_listener(
            chord=parse_binding(cfg.hotkey.binding, plat.keys()),
            device=cfg.hotkey.device,
            on_start=on_start,
            on_stop=on_stop,
            lock=daemon._lock,
        )
        deliverer = Deliverer(
            keyboard=plat.key_injector(),
            wait_released=listener.wait_binding_released,
            copy=plat.clipboard_writer(clipboard_backend),
        )
        daemon._listener = listener
        daemon._deliverer = deliverer
        return daemon

    def _publish_state(self, state: OverlayState) -> None:
        """Serialize display state and suppress duplicate helper updates."""
        with self._lock:
            if not should_publish_state(self._overlay_state, state):
                return
            self._overlay_state = state
            _publish_status(self._status, state)

    def _on_model_loading(self) -> None:
        """Publish cold-load activity without replacing the current pill."""
        with self._lock:
            if self._stop_event.is_set():
                return
            _publish_loading_activity(self._status, True)

    def _on_model_loading_finished(self) -> None:
        """Remove display activity after either model-ready or load failure."""
        with self._lock:
            _publish_loading_activity(self._status, False)

    def _warm_model(self) -> None:
        try:
            self._worker.warmup()
        except WorkerError as exc:
            if not self._stop_event.is_set():
                log.warning("worker: warmup_failed error_type=%s", type(exc).__name__)

    def _start_model_warmup(self) -> None:
        thread = threading.Thread(
            target=self._warm_model,
            name="stenographer-model-warmup",
            daemon=True,
        )
        try:
            thread.start()
        except RuntimeError as exc:
            log.warning("worker: warmup_start_failed error_type=%s", type(exc).__name__)
            return
        self._warmup_thread = thread

    def on_toggle_press(self) -> None:
        """Toggle mode: one press starts a recording, the next press stops it."""
        with self._lock:
            action = toggle_action(
                recording=self._recording,
                busy=self._busy,
                stopping=self._stop_event.is_set(),
            )
            if action == "start":
                self.on_key_down()
            elif action == "stop":
                self.on_key_up()

    def _on_max_duration(self, generation: int) -> None:
        """Timer thread: end a toggle recording exactly as a second press would."""
        with self._lock:
            if not max_duration_applies(generation, self._session_generation, self._recording):
                return
            log.info(
                "recorder: max_duration_stop seconds=%d",
                self._cfg.audio.max_recording_seconds,
            )
            self.on_key_up()

    def _cancel_max_timer(self) -> None:
        timer = self._max_timer
        if timer is not None:
            timer.cancel()
            self._max_timer = None

    def on_key_down(self) -> None:
        with self._lock:
            if not can_start(self._recording, self._busy, self._stop_event.is_set()):
                log.debug("hotkey: key-down ignored (recording/busy/stopping)")
                return
            self._worker.hold_model()
            try:
                self._recorder.start()
            except Exception as exc:
                log.error("recorder: failed phase=start error_type=%s", type(exc).__name__)
                self._recorder.close()
                self._worker.release_model()
                self._publish_state(OverlayState.ERROR)
                _play_cue(self._feedback, "error")
                self._notifier.error("could not start recording")
                self._recording = False
                return
            self._recording = True
            self._session_generation += 1
            if self._cfg.hotkey.mode == "toggle":
                timer = threading.Timer(
                    self._cfg.audio.max_recording_seconds,
                    self._on_max_duration,
                    args=(self._session_generation,),
                )
                timer.name = "stenographer-max-duration"
                timer.daemon = True
                timer.start()
                self._max_timer = timer
            self._publish_state(OverlayState.RECORDING)
            _play_cue(self._feedback, "record_start")
            self._start_model_warmup()

    def on_key_up(self) -> None:
        with self._lock:
            if not self._recording:
                return
            self._recording = False
            self._cancel_max_timer()
            # Deactivate visualization before waiting for PortAudio to quiesce,
            # so no recording frame can survive into later lifecycle states.
            self._publish_state(OverlayState.HIDDEN)
            try:
                samples = self._recorder.stop()
            except Exception as exc:
                log.error("recorder: failed phase=stop error_type=%s", type(exc).__name__)
                self._recorder.close()
                self._publish_state(OverlayState.ERROR)
                _play_cue(self._feedback, "error")
                self._notifier.error("recording failed; audio was discarded")
                self._worker.release_model()
                return
            self._busy = True
            _play_cue(self._feedback, "record_stop")
            thread = threading.Thread(
                target=self._run_pipeline,
                args=(samples,),
                name="stenographer-pipeline",
                daemon=True,
            )
            self._pipeline_thread = thread
            thread.start()

    def _run_pipeline(self, samples: np.ndarray) -> None:
        try:
            gate_passed = speech_gate_passes(samples, _SAMPLE_RATE, self._cfg.audio.min_speech_rms)
            if not gate_passed:
                log.info("pipeline: outcome=SILENT (gate)")
                self._publish_state(OverlayState.HIDDEN)
                return
            if not self._worker.is_model_ready:
                self._publish_state(OverlayState.TRANSCRIBING)
            try:
                result = self._worker.transcribe(samples)
            except WorkerError as exc:
                if self._stop_event.is_set():
                    log.info("pipeline: outcome=CANCELLED phase=transcribe")
                    self._publish_state(OverlayState.HIDDEN)
                    return
                log.warning("pipeline: transcription_failed error_type=%s", type(exc).__name__)
                self._publish_state(OverlayState.ERROR)
                _play_cue(self._feedback, "error")
                self._notifier.error("transcription failed")
                return
            if self._stop_event.is_set():
                log.info("pipeline: outcome=CANCELLED phase=post_transcribe")
                self._publish_state(OverlayState.HIDDEN)
                return
            transcript_nonempty = bool(result.text.strip())
            text = format_transcript(result.text, trailing_space=True)
            if not transcript_nonempty:
                self._publish_state(OverlayState.HIDDEN)
            else:
                self._publish_state(OverlayState.DELIVERING)
            try:
                deliver_result = self._deliverer.deliver(text) if transcript_nonempty else None
            except Exception as exc:
                log.warning("pipeline: delivery_failed error_type=%s", type(exc).__name__)
                self._publish_state(OverlayState.ERROR)
                _play_cue(self._feedback, "error")
                self._notifier.error("delivery failed")
                return
            outcome, message = classify_pipeline(
                gate_passed=True,
                transcript_nonempty=transcript_nonempty,
                deliver_result=deliver_result,
            )
            log.info("pipeline: outcome=%s chars=%d", outcome.name, len(text))
            if outcome is Outcome.DELIVERED:
                self._publish_state(OverlayState.HIDDEN)
                _play_cue(self._feedback, "delivered")
            elif outcome is Outcome.ERROR:
                self._publish_state(OverlayState.ERROR)
                _play_cue(self._feedback, "error")
                self._notifier.error(message or "delivery failed")
        finally:
            with self._lock:
                self._worker.release_model()
                self._busy = False

    def run(self) -> None:
        """Start the listener and block until stopped."""
        if self._listener is None:
            raise RuntimeError("daemon.run() before build()")
        self._listener.start()
        log.info("daemon: running (pid=%d)", os.getpid())
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
            self._cancel_max_timer()
            self._recorder.close()
            self._recording = False
        self._publish_state(OverlayState.HIDDEN)


def run(cfg: Config) -> int:
    """Build and run the daemon. Returns the process exit code."""
    from stenographer.cli import doctor
    from stenographer.hotkey import BindingError

    plat = current_platform()
    caps = doctor.probe(cfg)
    clipboard_backend = startup_clipboard_backend(caps)
    if clipboard_backend is None:
        print(
            "stenographer: required capabilities unavailable; run `stenographer doctor`",
            file=sys.stderr,
        )
        return 78

    status: StatusSink = NullStatusSink()
    if cfg.feedback.overlay:
        try:
            from stenographer.overlay import OverlaySupervisor

            status = OverlaySupervisor(cfg.feedback.spectrum_floor_dbfs)
        except Exception as exc:
            log.warning("overlay: unavailable error_type=%s", type(exc).__name__)

    log.info("deliver: clipboard_backend=%s", clipboard_backend)
    try:
        daemon = Daemon.build(
            cfg, clipboard_backend=clipboard_backend, status=status, platform=plat
        )
    except BindingError as exc:
        with contextlib.suppress(Exception):
            status.close()
        print(f"stenographer: {exc}", file=sys.stderr)
        return 78

    lock = plat.single_instance_lock()
    try:
        acquired = lock.acquire()
    except SingleInstanceLockError as exc:
        with contextlib.suppress(Exception):
            status.close()
        print(f"stenographer: {exc}", file=sys.stderr)
        return 78
    if not acquired:
        with contextlib.suppress(Exception):
            status.close()
        print("stenographer: another instance is already running.", file=sys.stderr)
        return 1

    def _handler(signum: int, frame: object) -> None:
        log.info("signal: received %s, stopping", signal.Signals(signum).name)
        daemon.request_stop()

    plat.install_stop_signal_handlers(_handler)

    try:
        try:
            daemon._recorder.prepare()
        except Exception as exc:
            log.warning(
                "recorder: startup_prepare_failed error_type=%s recovery=next_keypress",
                type(exc).__name__,
            )
        daemon.run()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()
        with contextlib.suppress(Exception):
            status.close()
        lock.release()
    return 0
