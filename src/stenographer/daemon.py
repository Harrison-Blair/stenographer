# SPDX-License-Identifier: GPL-3.0-or-later
"""The orchestrator: hotkey → record → transcribe → deliver.

The single module holding cross-component state. One utterance at a time, no
queue: a start press during transcription is ignored. Two hotkey modes:
``hold`` (push-to-talk, the default) maps key-down/key-up straight to
start/stop; ``toggle`` maps each press through ``toggle_action`` and ends a
forgotten recording via a generation-guarded ``audio.max_recording_seconds``
timer. An accepted start also warms the ASR model on a background thread while
capture remains authoritative. All state transitions are guarded by one lock so
a key event, a timer firing, and a pipeline completion cannot race. Pure policy
(``classify_pipeline``, ``can_start``, ``toggle_action``,
``max_duration_applies``) is the unit-testable surface; the single-instance
lock and stop handling come from the current :class:`~stenographer.platform.base.Platform`
(which names the stop — ``"SIGTERM"``, later ``"CTRL_CLOSE"`` — so the core
holds no POSIX vocabulary); the wired daemon is exercised by real dictation
(the M5 manual acceptance procedure).
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
import time
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from stenographer.audio import Recorder, speech_gate_stats
from stenographer.constants import SAMPLE_RATE
from stenographer.delivery.deliver import Deliverer
from stenographer.delivery.feedback import Feedback
from stenographer.platform import current_platform
from stenographer.platform.base import SingleInstanceLockError
from stenographer.status import NullStatusSink, OverlayState, StatusSink, should_publish_state
from stenographer.transcribe.pipeline import (
    UtteranceRecord,
    log_gate,
    log_summary,
    transcript_text,
)
from stenographer.transcribe.worker import Worker, WorkerError, WorkerPathologicalError
from stenographer.utils.logging_setup import fmt_event, log_failure, set_utterance

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

    from stenographer.audio import CaptureStats
    from stenographer.capabilities import Capabilities, OverlayCapability
    from stenographer.config import Config
    from stenographer.platform.base import Notifier, Platform
    from stenographer.transcribe.model import TranscriptionResult

log = logging.getLogger(__name__)

_PIPELINE_JOIN_SECONDS = 30.0


def _ignore_edge() -> None:
    """Falling-edge sink for toggle mode: only presses drive the session."""


def edge_handlers(daemon: Daemon, mode: str) -> tuple[Callable[[], None], Callable[[], None]]:
    """Map ``hotkey.mode`` onto the (rising, falling) edge callbacks.

    In toggle mode only presses drive the session, so the falling edge is inert.
    PURE given *daemon*: it reads no config and touches no platform surface.
    """
    if mode == "toggle":
        return daemon.on_toggle_press, _ignore_edge
    return daemon.on_key_down, daemon.on_key_up


def _play_cue(feedback: Feedback, name: str) -> None:
    """Launch a cue without allowing player failure to break daemon state."""
    try:
        feedback.play(name)
    except Exception as exc:
        log_failure(log, logging.WARNING, "feedback: cue_failed", exc, safe=True, cue=name)


def _publish_status(status: StatusSink, state: OverlayState) -> None:
    """Enqueue fixed lifecycle metadata without allowing overlay failure through."""
    try:
        status.publish(state)
    except Exception as exc:
        log_failure(
            log, logging.WARNING, "overlay: publish_failed", exc, safe=True, state=state.value
        )


def _publish_loading_activity(status: StatusSink, active: bool) -> None:
    try:
        status.loading_activity(active)
    except Exception as exc:
        log_failure(
            log,
            logging.WARNING,
            "overlay: loading_activity_failed",
            exc,
            safe=True,
            active=int(active),
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
    error cue. Otherwise the delivery result decides: a False deliver on
    non-empty text is an error (deliver already withheld the chord on copy
    failure), never treated as silent.
    """
    if not gate_passed:
        return (Outcome.SILENT, None)
    if not transcript_nonempty:
        return (Outcome.SILENT, None)
    if deliver_result:
        return (Outcome.DELIVERED, None)
    return (Outcome.ERROR, "could not copy transcript to clipboard")


def can_start(recording: bool, busy: bool, stopping: bool) -> bool:
    """Admit a new utterance only when idle — one utterance at a time. PURE."""
    return not (recording or busy or stopping)


def ignored_edge_reason(recording: bool, busy: bool, stopping: bool) -> str:
    """Name why an edge was refused, most specific state first. PURE.

    "recording_or_busy" was true of every refusal and therefore explained none
    of them; a press that vanished during shutdown looked exactly like one that
    vanished mid-decode.
    """
    if recording:
        return "recording"
    if busy:
        return "busy"
    if stopping:
        return "stopping"
    return "none"


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
    """Gate daemon startup on the capability requirements and reuse its backend name. PURE."""
    from stenographer.capabilities import missing_required

    if missing_required(caps):
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
        # Also the stale-timer generation: a max-duration timer applies only to
        # the utterance it was armed for, and each accepted start is a new one.
        self._utterance_id = 0
        self._record: UtteranceRecord | None = None
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
        from stenographer.config import resolve_config_path
        from stenographer.hotkey import parse_binding

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
        log.info("hotkey: configured mode=%s", cfg.hotkey.mode)
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

    def _fail(self, notify_msg: str) -> None:
        """Announce a failed phase on every user-facing channel at once.

        The error pill, the error cue and the notification always travel
        together; each call site keeps its own log line, since the level and
        the recorded event differ per phase.
        """
        self._publish_state(OverlayState.ERROR)
        _play_cue(self._feedback, "error")
        self._notifier.error(notify_msg)

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
            else:
                log.debug(
                    fmt_event(
                        "hotkey",
                        "toggle_press_ignored",
                        reason=ignored_edge_reason(
                            self._recording, self._busy, self._stop_event.is_set()
                        ),
                    )
                )

    def _on_max_duration(self, generation: int) -> None:
        """Timer thread: end a toggle recording exactly as a second press would."""
        with self._lock:
            if not max_duration_applies(generation, self._utterance_id, self._recording):
                log.debug(fmt_event("hotkey", "max_duration_ignored", reason="stale_or_idle"))
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
            self._worker.hold_model()
            started_at = time.perf_counter()
            try:
                self._recorder.start()
            except Exception as exc:
                log_failure(log, logging.ERROR, "recorder: failed", exc, safe=True, phase="start")
                self._recorder.close()
                self._worker.release_model()
                self._fail("could not start recording")
                self._recording = False
                return
            self._recording = True
            self._utterance_id += 1
            set_utterance(self._utterance_id)
            self._record = UtteranceRecord(
                utt=self._utterance_id, started_at=started_at, mode=self._cfg.hotkey.mode
            )
            if self._cfg.hotkey.mode == "toggle":
                timer = threading.Timer(
                    self._cfg.audio.max_recording_seconds,
                    self._on_max_duration,
                    args=(self._utterance_id,),
                )
                timer.name = "stenographer-max-duration"
                timer.daemon = True
                timer.start()
                self._max_timer = timer
            self._publish_state(OverlayState.RECORDING)
            _play_cue(self._feedback, "record_start")
            self._start_model_warmup(self._utterance_id)

    def on_key_up(self) -> None:
        with self._lock:
            if not self._recording:
                log.debug(fmt_event("hotkey", "key_up_ignored", reason="not_recording"))
                return
            self._recording = False
            self._cancel_max_timer()
            # Deactivate visualization before waiting for PortAudio to quiesce,
            # so no recording frame can survive into later lifecycle states.
            self._publish_state(OverlayState.HIDDEN)
            try:
                samples = self._recorder.stop()
            except Exception as exc:
                log_failure(log, logging.ERROR, "recorder: failed", exc, safe=True, phase="stop")
                self._recorder.close()
                self._fail("recording failed; audio was discarded")
                self._worker.release_model()
                self._emit_summary(self._take_record(Outcome.ERROR.name))
            else:
                self._apply_capture(self._recorder.last_capture)
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

    def _apply_capture(self, stats: CaptureStats | None) -> None:
        """Fold the recorder's own numbers into the utterance record."""
        record = self._record
        if record is None or stats is None:
            return
        record.activate_ms = stats.activate_ms
        record.capture_s = stats.capture_seconds
        record.in_frames = stats.input_frames
        record.out_frames = stats.output_frames
        record.overflow = stats.overflow
        record.capped = stats.capped

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
        log_summary(record)
        set_utterance(None)

    def _run_pipeline(self, samples: np.ndarray) -> None:
        record = self._record
        outcome_name = Outcome.ERROR.name
        try:
            # The gate runs here, on the pipeline thread, and never in the
            # PortAudio callback or under the state lock.
            stats = speech_gate_stats(samples, SAMPLE_RATE, self._cfg.audio.min_speech_rms)
            log_gate(stats)
            if record is not None:
                record.gate = "pass" if stats.passed else "fail"
                record.peak_rms = stats.peak_rms
                record.frames_above = stats.frames_above
            if not stats.passed:
                outcome_name = Outcome.SILENT.name
                self._publish_state(OverlayState.HIDDEN)
                return
            cold = not self._worker.is_model_ready
            if record is not None:
                record.cold = cold
            if cold:
                self._publish_state(OverlayState.TRANSCRIBING)
            try:
                result = self._worker.transcribe(samples, self._utterance_id)
            except WorkerPathologicalError as exc:
                if self._stop_event.is_set():
                    outcome_name = "CANCELLED"
                    self._publish_state(OverlayState.HIDDEN)
                    return
                # Caught before ``WorkerError``, which it subclasses: this
                # detail is the audited counts-only rejection reason, and it is
                # the only thing that explains a silently discarded decode.
                log_failure(log, logging.WARNING, "pipeline: transcription_failed", exc, safe=True)
                self._fail("transcription failed")
                return
            except WorkerError as exc:
                if self._stop_event.is_set():
                    outcome_name = "CANCELLED"
                    self._publish_state(OverlayState.HIDDEN)
                    return
                # safe=False: the message is the ASR child's serialised detail,
                # which its inference branch can build from decoder output.
                log_failure(log, logging.WARNING, "pipeline: transcription_failed", exc, safe=False)
                self._fail("transcription failed")
                return
            self._apply_decode(record, result)
            if self._stop_event.is_set():
                outcome_name = "CANCELLED"
                self._publish_state(OverlayState.HIDDEN)
                return
            transcript_nonempty = bool(result.text.strip())
            text = transcript_text(result)
            if record is not None:
                record.chars_out = len(text)
            if not transcript_nonempty:
                self._publish_state(OverlayState.HIDDEN)
            else:
                self._publish_state(OverlayState.DELIVERING)
            try:
                deliver_result = self._deliverer.deliver(text) if transcript_nonempty else None
            except Exception as exc:
                log_failure(log, logging.WARNING, "pipeline: delivery_failed", exc, safe=True)
                self._fail("delivery failed")
                return
            self._apply_delivery(record, attempted=transcript_nonempty)
            outcome, message = classify_pipeline(
                gate_passed=True,
                transcript_nonempty=transcript_nonempty,
                deliver_result=deliver_result,
            )
            outcome_name = outcome.name
            if outcome is Outcome.DELIVERED:
                self._publish_state(OverlayState.HIDDEN)
                _play_cue(self._feedback, "delivered")
            elif outcome is Outcome.ERROR:
                self._fail(message or "delivery failed")
        finally:
            with self._lock:
                self._worker.release_model()
                self._busy = False
                self._emit_summary(self._take_record(outcome_name))

    def _apply_decode(self, record: UtteranceRecord | None, result: TranscriptionResult) -> None:
        """Fold the worker's timings and the decode's shape into the record."""
        if record is None:
            return
        timings = self._worker.last_timings
        if timings is not None:
            record.lock_wait_ms = timings.lock_wait_ms
            record.load_ms = timings.load_ms
            record.decode_ms = timings.decode_ms
        record.vad_frames = round(result.vad_seconds * SAMPLE_RATE)
        record.segments = len(result.segments)
        record.words = sum(len(segment.words) for segment in result.segments)
        record.chars_raw = len(result.text)

    def _apply_delivery(self, record: UtteranceRecord | None, *, attempted: bool) -> None:
        """Fold the delivery's cost in — ``attempted`` says a copy was tried at all."""
        if record is None or not attempted:
            return
        timings = self._deliverer.last_timings
        if timings is None:
            return
        record.copy_ms = timings.copy_ms
        record.release_wait_ms = timings.release_wait_ms
        record.release_timeout = timings.release_timeout

    def run(self) -> None:
        """Start the listener and block until stopped."""
        if self._listener is None:
            raise RuntimeError("daemon.run() before build()")
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
            # A recording torn down mid-flight still owes the log its one line;
            # without this a press-then-stop leaves an utterance unaccounted for.
            self._emit_summary(self._take_record("CANCELLED"))
        self._publish_state(OverlayState.HIDDEN)
        set_utterance(None)


def _overlay_backend_name(overlay: OverlayCapability) -> str:
    """Name the overlay backend the daemon will actually get. PURE."""
    if not overlay.enabled:
        return "disabled"
    if overlay.backend is not None:
        return overlay.backend.value
    if overlay.reason is not None:
        return f"unavailable_{overlay.reason.value}"
    return "unknown"


def _shown(value: object) -> object:
    """Render an unset optional visibly: a banner key must never go missing."""
    if value is None:
        return "<unset>"
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, tuple):
        return ",".join(f"{item:g}" for item in value)
    return value


def _log_banner(cfg: Config, plat: Platform, caps: Capabilities, config_path: Path) -> None:
    """Record the whole effective configuration once, at INFO.

    A report that does not say what the daemon was actually configured with
    forces every question back to the reporter, so this is written before the
    startup gate can refuse — a refused start is exactly when it is wanted.

    ``asr.hotwords`` and ``asr.initial_prompt`` are the only config values that
    hold arbitrary user prose; they are reported as sizes. Everything else is
    the user's own settings, which rule 6 does not restrict.
    """
    from stenographer._version import __version__
    from stenographer.transcribe.model import resolve_cpu_threads

    version = sys.version_info
    log.info(
        fmt_event(
            "banner",
            "build",
            version=__version__,
            python=f"{version.major}.{version.minor}.{version.micro}",
            platform=plat.name,
            config=config_path,
        )
    )
    log.info(
        fmt_event(
            "banner",
            "backends",
            clipboard=_shown(caps.clipboard_backend),
            overlay=_overlay_backend_name(caps.overlay),
            cue_player=_shown(caps.cue_player),
        )
    )
    log.info(
        fmt_event(
            "banner",
            "config_hotkey",
            binding=cfg.hotkey.binding,
            device=_shown(cfg.hotkey.device),
            mode=cfg.hotkey.mode,
        )
    )
    log.info(
        fmt_event(
            "banner",
            "config_audio",
            input_device=_shown(cfg.audio.input_device),
            min_speech_rms=cfg.audio.min_speech_rms,
            max_recording_seconds=cfg.audio.max_recording_seconds,
        )
    )
    asr = cfg.asr
    log.info(
        fmt_event(
            "banner",
            "config_asr",
            model=asr.model,
            compute_type=asr.compute_type,
            beam_size=asr.beam_size,
            hotwords_words=len((asr.hotwords or "").split()),
            initial_prompt_chars=len(asr.initial_prompt or ""),
            vad_filter=_shown(asr.vad_filter),
            silence_threshold=asr.silence_threshold,
            idle_unload_seconds=asr.idle_unload_seconds,
            cpu_threads=asr.cpu_threads,
            resolved_cpu_threads=resolve_cpu_threads(asr.cpu_threads, plat.physical_core_count()),
        )
    )
    feedback = cfg.feedback
    log.info(
        fmt_event(
            "banner",
            "config_feedback",
            volume=feedback.volume,
            mute=_shown(feedback.mute),
            overlay=_shown(feedback.overlay),
            update_check=_shown(feedback.update_check),
            spectrum_floor_dbfs=_shown(feedback.spectrum_floor_dbfs),
            sound_pack=feedback.sound_pack,
            log_level=feedback.log_level,
        )
    )


def _startup_failure(status: StatusSink, message: str, code: int) -> int:
    """Report a startup bail-out on stderr and hand back its exit code.

    Any overlay opened before the failure is closed first, so a rejected start
    never strands a helper process.
    """
    with contextlib.suppress(Exception):
        status.close()
    print(f"stenographer: {message}", file=sys.stderr)
    return code


def run(cfg: Config) -> int:
    """Build and run the daemon. Returns the process exit code."""
    from stenographer.capabilities import probe
    from stenographer.config import resolve_config_path
    from stenographer.hotkey import BindingError

    plat = current_platform()
    status: StatusSink = NullStatusSink()
    caps = probe(cfg)
    _log_banner(cfg, plat, caps, resolve_config_path(create_parent=False))
    clipboard_backend = startup_clipboard_backend(caps)
    if clipboard_backend is None:
        return _startup_failure(
            status, "required capabilities unavailable; run `stenographer doctor`", 78
        )

    if cfg.feedback.overlay:
        try:
            from stenographer.overlay import OverlaySupervisor

            status = OverlaySupervisor(cfg.feedback.spectrum_floor_dbfs)
        except Exception as exc:
            log_failure(log, logging.WARNING, "overlay: unavailable", exc, safe=True)

    log.info("deliver: configured clipboard_backend=%s", clipboard_backend)
    try:
        daemon = Daemon.build(
            cfg, clipboard_backend=clipboard_backend, status=status, platform=plat
        )
    except BindingError as exc:
        return _startup_failure(status, str(exc), 78)

    lock = plat.single_instance_lock()
    try:
        acquired = lock.acquire()
    except SingleInstanceLockError as exc:
        return _startup_failure(status, str(exc), 78)
    if not acquired:
        return _startup_failure(status, "another instance is already running.", 1)

    def _handler(reason: str) -> None:
        log.info("stop: requested reason=%s", reason)
        daemon.request_stop()

    plat.install_stop_handlers(_handler)

    try:
        try:
            daemon._recorder.prepare()
        except Exception as exc:
            log_failure(
                log,
                logging.WARNING,
                "recorder: startup_prepare_failed",
                exc,
                safe=True,
                recovery="next_keypress",
            )
        if cfg.feedback.update_check:
            try:
                from stenographer._version import __version__
                from stenographer.update_check import start_background_check

                log.debug("update_check: enabled")
                start_background_check(
                    __version__,
                    plat.state_dir(os.environ, Path.home()),
                    daemon._notifier,
                )
            except Exception as exc:
                log_failure(log, logging.DEBUG, "update_check: not_started", exc, safe=True)
        daemon.run()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()
        with contextlib.suppress(Exception):
            status.close()
        lock.release()
    return 0
