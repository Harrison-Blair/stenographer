# SPDX-License-Identifier: GPL-3.0-or-later
"""The orchestrator: hotkey → record → transcribe → deliver (spec §5).

The single module holding cross-component state. One utterance at a time, PTT
only, no queue: a key-down during transcription is ignored (§5). All state
transitions are guarded by one lock so a key event and a pipeline completion
cannot race. Pure policy (``classify_pipeline``, ``can_start``) and the
single-instance lock helpers are the unit-testable surface; the wired daemon is
exercised by real dictation (the M5 manual acceptance procedure).
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import pathlib
import signal
import sys
import threading
from enum import Enum, auto
from typing import TYPE_CHECKING

from stenographer.audio import Recorder, speech_gate_passes
from stenographer.deliver import Deliverer, UinputKeyboard, copy_both_selections
from stenographer.feedback import Feedback
from stenographer.format import format_transcript
from stenographer.notify import Notifier
from stenographer.status import LifecycleEvent, NullStatusSink, OverlayState, StatusSink
from stenographer.worker import Worker, WorkerError

if TYPE_CHECKING:
    import numpy as np

    from stenographer.config import Config

log = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_PIPELINE_JOIN_SECONDS = 30.0


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


def _publish_lifecycle(status: StatusSink, event: LifecycleEvent) -> None:
    try:
        status.lifecycle(event)
    except Exception as exc:
        log.warning(
            "overlay: lifecycle_failed event=%s error_type=%s",
            event.value,
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


def _default_lock_path() -> pathlib.Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return pathlib.Path(runtime) / "stenographer.lock"


LOCK_PATH = _default_lock_path()


def acquire_single_instance_lock(path: pathlib.Path = LOCK_PATH) -> int:
    """Take the single-instance flock. Return the held fd, or -1 if another
    open file description already holds it. The PID is written into the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return -1
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def release_single_instance_lock(path: pathlib.Path = LOCK_PATH) -> None:
    """Remove the lock file, suppressing OSError."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


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
        self._pipeline_thread: threading.Thread | None = None
        self._listener = None
        self._deliverer: Deliverer | None = None

    @classmethod
    def build(cls, cfg: Config, *, status: StatusSink | None = None) -> Daemon:
        from stenographer.hotkey import HotkeyListener, parse_binding

        feedback = Feedback(cfg=cfg.feedback)
        notifier = Notifier()
        status = status if status is not None else NullStatusSink()

        def on_model_loading() -> None:
            _publish_status(status, OverlayState.MODEL_LOADING)
            _play_cue(feedback, "model_loading")

        def on_model_ready() -> None:
            _publish_lifecycle(status, LifecycleEvent.MODEL_READY)

        def on_transcribing() -> None:
            _publish_status(status, OverlayState.TRANSCRIBING)

        worker = Worker(
            cfg.asr,
            on_model_loading=on_model_loading,
            on_model_ready=on_model_ready,
            on_transcribing=on_transcribing,
        )
        recorder = Recorder(
            device=cfg.audio.input_device, max_seconds=cfg.audio.max_recording_seconds
        )
        daemon = cls(
            cfg=cfg,
            feedback=feedback,
            notifier=notifier,
            worker=worker,
            recorder=recorder,
            status=status,
        )
        listener = HotkeyListener(
            chord=parse_binding(cfg.hotkey.binding),
            device_path=cfg.hotkey.device,
            on_start=daemon.on_key_down,
            on_stop=daemon.on_key_up,
            lock=daemon._lock,
        )
        deliverer = Deliverer(
            keyboard=UinputKeyboard(),
            wait_released=listener.wait_binding_released,
            copy=copy_both_selections,
        )
        daemon._listener = listener
        daemon._deliverer = deliverer
        return daemon

    def on_key_down(self) -> None:
        with self._lock:
            if not can_start(self._recording, self._busy, self._stop_event.is_set()):
                log.debug("hotkey: key-down ignored (recording/busy/stopping)")
                return
            try:
                self._recorder.start()
            except Exception as exc:
                log.error("recorder: failed phase=start error_type=%s", type(exc).__name__)
                self._recorder.close()
                _publish_status(self._status, OverlayState.ERROR)
                _play_cue(self._feedback, "error")
                self._notifier.error("could not start recording")
                self._recording = False
                return
            self._recording = True
            _publish_status(self._status, OverlayState.RECORDING)
            _play_cue(self._feedback, "record_start")

    def on_key_up(self) -> None:
        with self._lock:
            if not self._recording:
                return
            self._recording = False
            try:
                samples = self._recorder.stop()
            except Exception as exc:
                log.error("recorder: failed phase=stop error_type=%s", type(exc).__name__)
                self._recorder.close()
                _publish_status(self._status, OverlayState.ERROR)
                _play_cue(self._feedback, "error")
                self._notifier.error("recording failed; audio was discarded")
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
                _publish_status(self._status, OverlayState.HIDDEN)
                return
            try:
                result = self._worker.transcribe(samples)
            except WorkerError as exc:
                log.warning("pipeline: transcription_failed error_type=%s", type(exc).__name__)
                _publish_status(self._status, OverlayState.ERROR)
                _play_cue(self._feedback, "error")
                self._notifier.error("transcription failed")
                return
            transcript_nonempty = bool(result.text.strip())
            text = format_transcript(result.text)
            if not transcript_nonempty:
                _publish_status(self._status, OverlayState.HIDDEN)
            else:
                _publish_status(self._status, OverlayState.DELIVERING)
            try:
                deliver_result = self._deliverer.deliver(text) if transcript_nonempty else None
            except Exception as exc:
                log.warning("pipeline: delivery_failed error_type=%s", type(exc).__name__)
                _publish_status(self._status, OverlayState.ERROR)
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
                _publish_status(self._status, OverlayState.HIDDEN)
                _play_cue(self._feedback, "delivered")
            elif outcome is Outcome.ERROR:
                _publish_status(self._status, OverlayState.ERROR)
                _play_cue(self._feedback, "error")
                self._notifier.error(message or "delivery failed")
        finally:
            with self._lock:
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
        thread = self._pipeline_thread
        if thread is not None:
            thread.join(timeout=_PIPELINE_JOIN_SECONDS)
        if self._deliverer is not None:
            with contextlib.suppress(Exception):
                self._deliverer.close()
        with contextlib.suppress(Exception):
            self._feedback.close()
        with self._lock:
            self._recorder.close()
            self._recording = False
        _publish_status(self._status, OverlayState.HIDDEN)


def run(cfg: Config) -> int:
    """Build and run the daemon. Returns the process exit code."""
    from stenographer import model
    from stenographer.hotkey import BindingError

    if not model.is_model_cached(cfg.asr.model):
        print(
            "stenographer: ASR model not found; run `stenographer model download`",
            file=sys.stderr,
        )
        return 78

    status: StatusSink = NullStatusSink()
    if cfg.feedback.overlay:
        try:
            from stenographer.overlay import OverlaySupervisor

            status = OverlaySupervisor()
        except Exception as exc:
            log.warning("overlay: unavailable error_type=%s", type(exc).__name__)

    try:
        daemon = Daemon.build(cfg, status=status)
    except BindingError as exc:
        with contextlib.suppress(Exception):
            status.close()
        print(f"stenographer: {exc}", file=sys.stderr)
        return 78

    fd = acquire_single_instance_lock()
    if fd < 0:
        with contextlib.suppress(Exception):
            status.close()
        print("stenographer: another instance is already running.", file=sys.stderr)
        return 1

    def _handler(signum: int, frame: object) -> None:
        log.info("signal: received %s, stopping", signal.Signals(signum).name)
        daemon.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handler)

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
        os.close(fd)
        release_single_instance_lock()
    return 0
