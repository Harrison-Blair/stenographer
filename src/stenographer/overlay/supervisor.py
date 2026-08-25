# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated lifecycle/spectrum helper supervision and backend selection.

The daemon-facing methods only update a small in-memory mailbox.  Child
process creation and every pipe operation live on the supervisor thread, and
all display work lives in the helper process.

Spawning, polling, and killing that child are host concerns: this module owns
the policy and reaches the OS only through ``HelperTransport`` /
``HelperProcess`` (see ``platform/base.py``), so nothing here imports
``subprocess``, ``selectors``, or raw-fd I/O.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from stenographer.overlay.entry import OVERLAY_ENTRY_ARG
from stenographer.overlay.spectrum import (
    DEFAULT_SPECTRUM_FLOOR_DBFS,
    SPECTRUM_FPS,
    SpectrumAnalyzer,
)
from stenographer.platform import current_platform
from stenographer.platform.base import UnsupportedPlatformError
from stenographer.status import (
    ERROR_DISPLAY_SECONDS,
    Command,
    CommandMessage,
    LineReader,
    LoadingActivityMessage,
    OverlayState,
    ProtocolError,
    ProtocolMessage,
    ReadyMessage,
    SpectrumMessage,
    StateMessage,
    UnavailableMessage,
    UnavailableReason,
    decode_message,
    encode_message,
    error_timeout_applies,
    selected_unavailable_reason,
)
from stenographer.utils.logging_setup import (
    cap_helper_log,
    fmt_event,
    helper_log_path,
    log_failure,
    setup_helper_logging,
)

if TYPE_CHECKING:
    from stenographer.platform.base import HelperProcess

log = logging.getLogger(__name__)

_MAILBOX_CAPACITY = 8
_POLL_SECONDS = 0.05
_READY_TIMEOUT_SECONDS = 3.0
_SHUTDOWN_GRACE_SECONDS = 0.75
_THREAD_JOIN_SECONDS = 2.0
_READ_SIZE = 4096
_SPECTRUM_INTERVAL = 1.0 / SPECTRUM_FPS


def helper_command(executable: str, *, frozen: bool) -> tuple[str, ...]:
    """Return the private helper re-exec command without inspecting process state."""
    if frozen:
        return executable, OVERLAY_ENTRY_ARG
    return executable, "-m", "stenographer.cli", OVERLAY_ENTRY_ARG


def helper_ready_timed_out(
    *, started_at: float, now: float, ready: bool, timeout: float = _READY_TIMEOUT_SECONDS
) -> bool:
    """Pure readiness deadline policy for a started helper process."""
    return not ready and now - started_at >= timeout


def schedule_spectrum(
    recording: bool, next_spectrum_at: float | None, now: float
) -> tuple[float | None, bool]:
    """Return (new_deadline, run_produce). Cadence only while recording;
    exactly one cleanup produce on leaving recording."""
    if not recording:
        return None, next_spectrum_at is not None
    if next_spectrum_at is None or now >= next_spectrum_at:
        return now + _SPECTRUM_INTERVAL, True
    return next_spectrum_at, False


def serve_timeout(
    now: float, next_spectrum_at: float | None, poll_seconds: float = _POLL_SECONDS
) -> float:
    if next_spectrum_at is None:
        return poll_seconds
    return min(poll_seconds, max(0.0, next_spectrum_at - now))


@dataclass(slots=True)
class RestartBudget:
    """Pure one-way retry budget for unexpected helper exits."""

    remaining: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.remaining, bool) or self.remaining < 0:
            raise ValueError("restart budget must be a non-negative integer")

    def on_exit(self, *, unexpected: bool) -> bool:
        if not unexpected or self.remaining == 0:
            return False
        self.remaining -= 1
        return True


@dataclass(frozen=True, slots=True)
class _AudioBlock:
    """One copied block tagged with daemon-only recording and stream identities."""

    generation: int
    samples: object
    sample_rate: int
    stream_epoch: int


class OutboundMailbox:
    """Bounded metadata queue plus latest-only audio and spectrum slots.

    Adjacent state updates coalesce to the newest generation. Loading-activity
    records form ordering barriers and take priority over spectrum frames.
    State transitions discard raw/spectrum slots from the prior recording.
    Shutdown clears everything and occupies the sole command slot.
    """

    def __init__(self, capacity: int = _MAILBOX_CAPACITY) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("mailbox capacity must be a positive integer")
        self._capacity = capacity
        self._pending: deque[StateMessage | LoadingActivityMessage] = deque()
        self._spectrum_pending: SpectrumMessage | None = None
        self._audio_pending: _AudioBlock | None = None
        self._next_generation = 0
        self._next_sequence = 0
        self._closed = False
        self._disabled = False
        self._shutdown_pending = False
        self._current_state = StateMessage(0, OverlayState.HIDDEN)
        self._loading_active = False
        self._recording_generation: int | None = None
        self._error_deadline: float | None = None
        self._condition = threading.Condition()

    @property
    def current_state(self) -> StateMessage:
        with self._condition:
            return self._current_state

    @property
    def error_deadline(self) -> float | None:
        with self._condition:
            return self._error_deadline

    def _append(self, message: StateMessage | LoadingActivityMessage) -> None:
        if (
            isinstance(message, StateMessage)
            and self._pending
            and isinstance(self._pending[-1], StateMessage)
        ):
            self._pending[-1] = message
        else:
            if len(self._pending) == self._capacity:
                self._pending.popleft()
            self._pending.append(message)
        while len(self._pending) > self._capacity:
            self._pending.popleft()

    def _generation(self) -> int:
        generation = self._next_generation
        self._next_generation += 1
        return generation

    def publish(self, state: OverlayState) -> int:
        if not isinstance(state, OverlayState):
            raise TypeError("state must be an OverlayState")
        with self._condition:
            if self._closed or self._disabled:
                return self._current_state.generation
            message = StateMessage(self._generation(), state)
            self._audio_pending = None
            self._spectrum_pending = None
            self._recording_generation = (
                message.generation if state is OverlayState.RECORDING else None
            )
            self._next_sequence = 0
            self._append(message)
            self._current_state = message
            self._error_deadline = (
                time.monotonic() + ERROR_DISPLAY_SECONDS if state is OverlayState.ERROR else None
            )
            self._condition.notify()
            return message.generation

    def loading_activity(self, active: bool) -> None:
        """Queue a boolean activity edge without disturbing recording slots."""
        if not isinstance(active, bool):
            raise TypeError("loading activity must be a boolean")
        with self._condition:
            if self._closed or self._disabled or active == self._loading_active:
                return
            message = LoadingActivityMessage(active)
            encode_message(message)
            self._append(message)
            self._loading_active = active
            self._condition.notify()

    def audio_block(self, samples: object, sample_rate: int, stream_epoch: int) -> None:
        """Replace the raw block slot without copying, locking, or performing I/O."""
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
            return
        if isinstance(stream_epoch, bool) or not isinstance(stream_epoch, int) or stream_epoch < 0:
            return
        generation = self._recording_generation
        if self._closed or self._disabled or generation is None:
            return
        # CPython reference assignment is atomic.  A racing transition may
        # leave one old tagged block, which the generation check discards.
        self._audio_pending = _AudioBlock(generation, samples, sample_rate, stream_epoch)

    def take_audio_nowait(self) -> _AudioBlock | None:
        with self._condition:
            block, self._audio_pending = self._audio_pending, None
            return block

    def publish_spectrum(self, generation: int, levels: tuple[int, ...]) -> int | None:
        """Replace the latest frame only when its recording is still current."""
        with self._condition:
            if (
                self._closed
                or self._disabled
                or generation != self._recording_generation
                or self._current_state.state is not OverlayState.RECORDING
            ):
                return None
            message = SpectrumMessage(generation, self._next_sequence, levels)
            encode_message(message)
            self._next_sequence += 1
            self._spectrum_pending = message
            self._condition.notify()
            return message.sequence

    def expire_error(self, now: float | None = None) -> int | None:
        """Queue a guarded hide when the current error's fixed timeout expires."""
        if now is None:
            now = time.monotonic()
        with self._condition:
            deadline = self._error_deadline
            current = self._current_state
            if (
                self._closed
                or deadline is None
                or now < deadline
                or not error_timeout_applies(current.generation, current)
            ):
                return None
            message = StateMessage(self._generation(), OverlayState.HIDDEN)
            self._audio_pending = None
            self._spectrum_pending = None
            self._recording_generation = None
            self._next_sequence = 0
            self._append(message)
            self._current_state = message
            self._error_deadline = None
            self._condition.notify()
            return message.generation

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._pending.clear()
            self._audio_pending = None
            self._spectrum_pending = None
            self._error_deadline = None
            self._shutdown_pending = True
            self._condition.notify_all()

    def disable(self) -> None:
        """Discard optional work after the helper has permanently stopped."""
        with self._condition:
            self._disabled = True
            self._pending.clear()
            self._audio_pending = None
            self._spectrum_pending = None
            self._recording_generation = None
            self._loading_active = False
            self._condition.notify_all()

    def replay_for_helper(self) -> tuple[StateMessage | LoadingActivityMessage, ...]:
        """Return one atomic current snapshot and discard superseded metadata.

        A restarted helper has no useful history.  Clearing queued metadata in
        the same critical section prevents an ungenerated loading edge from
        replaying out of order after the current snapshot.
        """
        with self._condition:
            replay: list[StateMessage | LoadingActivityMessage] = []
            if self._loading_active:
                replay.append(LoadingActivityMessage(True))
            if self._current_state.state is not OverlayState.HIDDEN:
                replay.append(self._current_state)
            self._pending.clear()
            self._spectrum_pending = None
            return tuple(replay)

    def take_nowait(self) -> ProtocolMessage | None:
        with self._condition:
            return self._take_locked()

    def take(self, timeout: float | None = None) -> ProtocolMessage | None:
        with self._condition:
            if not self._shutdown_pending and not self._pending and self._spectrum_pending is None:
                self._condition.wait(timeout)
            return self._take_locked()

    def _take_locked(self) -> ProtocolMessage | None:
        if self._shutdown_pending:
            self._shutdown_pending = False
            return CommandMessage(Command.SHUTDOWN)
        if self._pending:
            return self._pending.popleft()
        if self._spectrum_pending is not None:
            message, self._spectrum_pending = self._spectrum_pending, None
            return message
        return None


@dataclass(frozen=True, slots=True)
class _ProcessOutcome:
    expected: bool
    unavailable: bool = False


class OverlaySupervisor:
    """Nonblocking daemon-side sink backed by one isolated helper process."""

    def __init__(self, spectrum_floor_dbfs: object = DEFAULT_SPECTRUM_FLOOR_DBFS) -> None:
        self._mailbox = OutboundMailbox()
        self._analyzer = SpectrumAnalyzer(spectrum_floor_dbfs)
        self._analyzer_generation: int | None = None
        self._last_analysis_at: float | None = None
        self._thread = threading.Thread(
            target=self._thread_main,
            name="stenographer-overlay-supervisor",
            daemon=True,
        )
        self._thread.start()

    def publish(self, state: OverlayState) -> None:
        self._mailbox.publish(state)

    def loading_activity(self, active: bool) -> None:
        self._mailbox.loading_activity(active)

    def audio_block(self, samples: object, sample_rate: int, stream_epoch: int) -> None:
        self._mailbox.audio_block(samples, sample_rate, stream_epoch)

    def close(self) -> None:
        self._mailbox.close()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=_THREAD_JOIN_SECONDS)

    def _thread_main(self) -> None:
        budget = RestartBudget(1)
        command = helper_command(sys.executable, frozen=bool(getattr(sys, "frozen", False)))
        try:
            try:
                transport = current_platform().helper_transport()
            except UnsupportedPlatformError:
                log.info("overlay: helper_unavailable reason=unsupported_platform")
                return
            while True:
                self._mailbox.expire_error()
                try:
                    helper = transport.spawn(command, stderr_path=_helper_stderr_path())
                except (OSError, ValueError) as exc:
                    log.warning("overlay: helper_start_failed error_type=%s", type(exc).__name__)
                    if not budget.on_exit(unexpected=True):
                        return
                    continue

                try:
                    outcome = self._serve(helper)
                except Exception as exc:
                    log.warning("overlay: supervisor_failed error_type=%s", type(exc).__name__)
                    helper.close()
                    self._reap(helper, expected=False)
                    outcome = _ProcessOutcome(False)
                if outcome.unavailable or outcome.expected:
                    return
                if not budget.on_exit(unexpected=True):
                    log.warning("overlay: helper_disabled reason=restart_budget_exhausted")
                    return
                log.warning("overlay: helper_restarting")
        finally:
            self._mailbox.disable()
            self._analyzer.reset()

    def _produce_spectrum(self, now: float) -> None:
        current = self._mailbox.current_state
        if current.state is not OverlayState.RECORDING:
            if self._analyzer_generation is not None:
                self._analyzer_generation = None
                self._last_analysis_at = None
            self._mailbox.take_audio_nowait()
            return
        if self._analyzer_generation != current.generation:
            self._analyzer.begin_recording()
            self._analyzer_generation = current.generation
            self._last_analysis_at = None
        block = self._mailbox.take_audio_nowait()
        if block is None or block.generation != current.generation:
            return
        elapsed = (
            _SPECTRUM_INTERVAL
            if self._last_analysis_at is None
            else max(0.0, now - self._last_analysis_at)
        )
        levels = self._analyzer.update(
            block.samples,
            block.sample_rate,
            stream_epoch=block.stream_epoch,
            elapsed=elapsed,
        )
        self._last_analysis_at = now
        self._mailbox.publish_spectrum(current.generation, levels)

    def _serve(self, helper: HelperProcess) -> _ProcessOutcome:
        reader = LineReader()
        ready = False
        started_at = time.monotonic()
        expected_exit = False
        unavailable = False
        next_spectrum_at: float | None = None

        # A restarted helper needs an atomic snapshot even when the original
        # records were already consumed by the previous process.
        for replay in self._mailbox.replay_for_helper():
            if not self._write(helper, replay):
                helper.close()
                self._reap(helper, expected=False)
                return _ProcessOutcome(False)

        try:
            stream_failed = False
            while helper.is_running():
                now = time.monotonic()
                if helper_ready_timed_out(started_at=started_at, now=now, ready=ready):
                    log.warning("overlay: helper_ready_timeout")
                    break
                self._mailbox.expire_error()
                recording = self._mailbox.current_state.state is OverlayState.RECORDING
                next_spectrum_at, produce = schedule_spectrum(recording, next_spectrum_at, now)
                if produce:
                    self._produce_spectrum(now)
                message = self._mailbox.take_nowait()
                if message is not None:
                    if not self._write(helper, message):
                        break
                    if isinstance(message, CommandMessage):
                        expected_exit = True
                        helper.close_input()

                timeout = serve_timeout(time.monotonic(), next_spectrum_at)
                if helper.wait_readable(timeout):
                    chunk = helper.read(_READ_SIZE)
                    if not chunk:
                        try:
                            reader.finish()
                        except ProtocolError as exc:
                            log_failure(
                                log,
                                logging.WARNING,
                                "overlay: helper_protocol_error",
                                exc,
                                safe=True,
                                phase="finish",
                            )
                        stream_failed = True
                    else:
                        try:
                            records = reader.feed(chunk)
                            for record in records:
                                control = decode_message(record)
                                if (
                                    isinstance(control, ReadyMessage)
                                    and not ready
                                    and not unavailable
                                ):
                                    ready = True
                                    log.info("overlay: ready backend=%s", control.backend.value)
                                elif isinstance(control, UnavailableMessage):
                                    if ready:
                                        log.warning(
                                            "overlay: backend_lost reason=%s", control.reason.value
                                        )
                                        stream_failed = True
                                    elif not unavailable:
                                        unavailable = True
                                        expected_exit = True
                                        log.info(
                                            "overlay: unavailable reason=%s", control.reason.value
                                        )
                                    else:
                                        raise ProtocolError("duplicate helper terminal message")
                                else:
                                    raise ProtocolError("unexpected helper protocol message")
                        except ProtocolError as exc:
                            log_failure(
                                log,
                                logging.WARNING,
                                "overlay: helper_protocol_error",
                                exc,
                                safe=True,
                                phase="feed",
                            )
                            stream_failed = True
                if stream_failed:
                    break
                if expected_exit and helper.is_running():
                    break
        finally:
            helper.close()
            self._reap(helper, expected=expected_exit)
        return _ProcessOutcome(expected_exit, unavailable)

    @staticmethod
    def _write(helper: HelperProcess, message: ProtocolMessage) -> bool:
        try:
            helper.write(encode_message(message).encode("ascii"))
        except (BrokenPipeError, OSError, ProtocolError):
            return False
        return True

    @staticmethod
    def _reap(helper: HelperProcess, *, expected: bool) -> None:
        """Give an expected exit its grace period, then let the host escalate."""
        if expected and helper.is_running():
            helper.wait(_SHUTDOWN_GRACE_SECONDS)
        helper.terminate(_SHUTDOWN_GRACE_SECONDS)


def _helper_stderr_path() -> Path | None:
    """The file a spawned helper's stderr appends to, capped before it is opened.

    The parent caps it so the child, which caps the same path before installing
    its own handler, finds it already small and leaves the inode alone — one
    file, two append-mode descriptors, and no rotation while either is open.
    """
    try:
        path = helper_log_path(os.environ, Path.home())
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.debug(fmt_event("overlay", "helper_log_unavailable", error=type(exc).__name__))
        return None
    cap_helper_log(path)
    return path


def _write_helper_message(stream: BinaryIO, message: ReadyMessage | UnavailableMessage) -> None:
    stream.write(encode_message(message).encode("ascii"))
    stream.flush()


class _NoBackendError(Exception):
    """Every registered backend refused; *reason* is what the parent is told."""

    def __init__(self, reason: UnavailableReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def _reported_reason(exc: BaseException) -> UnavailableReason | None:
    """The fixed reason a backend attached to its refusal, if it attached one.

    Read by attribute rather than by exception class: ``BackendUnavailableError``
    lives with the backends inside the platform package, and this module is core.
    """
    reason = getattr(exc, "reason", None)
    return reason if isinstance(reason, UnavailableReason) else None


def _select_backend():
    """Construct the first available platform backend; imports stay helper-local."""
    reasons: list[UnavailableReason | None] = []
    for spec in current_platform().overlay_backends():
        try:
            backend = spec.construct()
        except Exception as exc:
            reason = _reported_reason(exc)
            if reason is None and isinstance(exc, ImportError):
                # A backend module that fails to import before it can raise its
                # own classified error is still a missing dependency.
                reason = UnavailableReason.BACKEND_DEPENDENCY_MISSING
            reasons.append(reason)
            log_failure(
                log,
                logging.INFO,
                "overlay_helper: backend_rejected",
                exc,
                safe=True,
                backend=spec.backend.value,
                reason=reason.value if reason is not None else "unreported",
            )
            continue
        log.info(fmt_event("overlay_helper", "backend_selected", backend=spec.backend.value))
        return backend
    raise _NoBackendError(selected_unavailable_reason(reasons))


def run_overlay_helper(
    input_stream: BinaryIO | None = None,
    output_stream: BinaryIO | None = None,
) -> int:
    """Run the private display helper protocol endpoint.

    In the child only the module logger is used, but its records land in the
    helper's own ``overlay-helper.log``: ``setup_helper_logging`` is what
    reconfigures the shared ``stenographer`` logger this one propagates to.

    Every exit writes exactly one reply. The parent blocks on the readiness
    deadline, so a helper that dies without a record costs it three seconds and
    tells it nothing about why.
    """
    input_stream = input_stream if input_stream is not None else sys.stdin.buffer
    output_stream = output_stream if output_stream is not None else sys.stdout.buffer
    setup_helper_logging()
    try:
        backend = _select_backend()
    except _NoBackendError as exc:
        log.info(fmt_event("overlay_helper", "unavailable", reason=exc.reason.value))
        _write_helper_message(output_stream, UnavailableMessage(exc.reason))
        return 0
    except Exception as exc:
        # The host itself refused (no platform support, no backend registry):
        # not a backend's fixed reason, so the unspecific one is the honest one.
        log_failure(log, logging.WARNING, "overlay_helper: selection_failed", exc, safe=True)
        with contextlib.suppress(Exception):
            _write_helper_message(
                output_stream, UnavailableMessage(UnavailableReason.BACKENDS_UNAVAILABLE)
            )
        return 1

    try:
        _write_helper_message(output_stream, ReadyMessage(backend.backend))
        log.info(fmt_event("overlay_helper", "ready", backend=backend.backend.value))
        backend.run(input_stream)
    except ProtocolError as exc:
        log_failure(log, logging.WARNING, "overlay_helper: protocol_error", exc, safe=True)
        with contextlib.suppress(Exception):
            _write_helper_message(
                output_stream, UnavailableMessage(UnavailableReason.PROTOCOL_ERROR)
            )
        return 1
    except Exception as exc:
        log_failure(log, logging.WARNING, "overlay_helper: backend_lost", exc, safe=True)
        with contextlib.suppress(Exception):
            _write_helper_message(output_stream, UnavailableMessage(UnavailableReason.BACKEND_LOST))
        return 1
    finally:
        try:
            backend.close()
        except Exception as exc:
            log_failure(log, logging.DEBUG, "overlay_helper: close_failed", exc, safe=True)
        log.info(fmt_event("overlay_helper", "closed"))
    return 0
