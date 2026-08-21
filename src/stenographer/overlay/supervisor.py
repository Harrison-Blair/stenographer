# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated lifecycle/spectrum helper supervision and backend selection.

The daemon-facing methods only update a small in-memory mailbox.  Child
process creation and every pipe operation live on the supervisor thread, and
all display work lives in the helper process.
"""

from __future__ import annotations

import contextlib
import logging
import os
import selectors
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import BinaryIO

from stenographer.overlay.spectrum import (
    DEFAULT_SPECTRUM_FLOOR_DBFS,
    SPECTRUM_FPS,
    SpectrumAnalyzer,
)
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
)

log = logging.getLogger(__name__)

_MAILBOX_CAPACITY = 8
_POLL_SECONDS = 0.05
_READY_TIMEOUT_SECONDS = 3.0
_SHUTDOWN_GRACE_SECONDS = 0.75
_THREAD_JOIN_SECONDS = 2.0
_SPECTRUM_INTERVAL = 1.0 / SPECTRUM_FPS


def helper_command(executable: str, *, frozen: bool) -> tuple[str, ...]:
    """Return the private helper re-exec command without inspecting process state."""
    if frozen:
        return executable, "_overlay"
    return executable, "-m", "stenographer.cli", "_overlay"


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
            while True:
                self._mailbox.expire_error()
                try:
                    process = subprocess.Popen(
                        command,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        bufsize=0,
                    )
                except (OSError, ValueError) as exc:
                    log.warning("overlay: helper_start_failed error_type=%s", type(exc).__name__)
                    if not budget.on_exit(unexpected=True):
                        return
                    continue

                try:
                    outcome = self._serve(process)
                except Exception as exc:
                    log.warning("overlay: supervisor_failed error_type=%s", type(exc).__name__)
                    self._reap(process, expected=False)
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

    def _serve(self, process: subprocess.Popen[bytes]) -> _ProcessOutcome:
        assert process.stdin is not None
        assert process.stdout is not None
        reader = LineReader()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        ready = False
        started_at = time.monotonic()
        expected_exit = False
        unavailable = False
        next_spectrum_at: float | None = None

        # A restarted helper needs an atomic snapshot even when the original
        # records were already consumed by the previous process.
        for replay in self._mailbox.replay_for_helper():
            if not self._write(process.stdin, replay):
                selector.close()
                with contextlib.suppress(OSError):
                    process.stdin.close()
                with contextlib.suppress(OSError):
                    process.stdout.close()
                self._reap(process, expected=False)
                return _ProcessOutcome(False)

        try:
            stream_failed = False
            while process.poll() is None:
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
                    if not self._write(process.stdin, message):
                        break
                    if isinstance(message, CommandMessage):
                        expected_exit = True
                        with contextlib.suppress(OSError):
                            process.stdin.close()

                timeout = serve_timeout(time.monotonic(), next_spectrum_at)
                for key, _events in selector.select(timeout):
                    try:
                        chunk = os.read(key.fd, 4096)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        try:
                            reader.finish()
                        except ProtocolError:
                            log.warning("overlay: helper_protocol_error")
                        stream_failed = True
                        break
                    try:
                        records = reader.feed(chunk)
                        for record in records:
                            control = decode_message(record)
                            if isinstance(control, ReadyMessage) and not ready and not unavailable:
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
                                    log.info("overlay: unavailable reason=%s", control.reason.value)
                                else:
                                    raise ProtocolError("duplicate helper terminal message")
                            else:
                                raise ProtocolError("unexpected helper protocol message")
                    except ProtocolError:
                        log.warning("overlay: helper_protocol_error")
                        stream_failed = True
                        break
                if stream_failed:
                    break
                if expected_exit and process.poll() is None:
                    break
        finally:
            selector.close()
            with contextlib.suppress(OSError):
                process.stdin.close()
            with contextlib.suppress(OSError):
                process.stdout.close()
            self._reap(process, expected=expected_exit)
        return _ProcessOutcome(expected_exit, unavailable)

    @staticmethod
    def _write(stream: BinaryIO, message: ProtocolMessage) -> bool:
        try:
            stream.write(encode_message(message).encode("ascii"))
            stream.flush()
        except (BrokenPipeError, OSError, ProtocolError):
            return False
        return True

    @staticmethod
    def _reap(process: subprocess.Popen[bytes], *, expected: bool) -> None:
        if process.poll() is not None:
            with contextlib.suppress(OSError):
                process.wait(timeout=0)
            return
        if expected:
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=_SHUTDOWN_GRACE_SECONDS)
        if process.poll() is None:
            with contextlib.suppress(OSError):
                process.terminate()
            try:
                process.wait(timeout=_SHUTDOWN_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):
                    process.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=_SHUTDOWN_GRACE_SECONDS)


def _write_helper_message(stream: BinaryIO, message: ReadyMessage | UnavailableMessage) -> None:
    stream.write(encode_message(message).encode("ascii"))
    stream.flush()


def _select_backend():
    """Construct the preferred available backend; imports stay helper-local."""
    try:
        from stenographer.overlay.wayland import LayerShellBackend

        return LayerShellBackend()
    except Exception:
        pass

    try:
        from stenographer.overlay.x11 import X11OverlayBackend

        return X11OverlayBackend()
    except Exception:
        raise RuntimeError("overlay backends unavailable") from None


def run_overlay_helper(
    input_stream: BinaryIO | None = None,
    output_stream: BinaryIO | None = None,
) -> int:
    """Run the private display helper protocol endpoint."""
    input_stream = input_stream if input_stream is not None else sys.stdin.buffer
    output_stream = output_stream if output_stream is not None else sys.stdout.buffer
    try:
        backend = _select_backend()
    except Exception:
        _write_helper_message(
            output_stream, UnavailableMessage(UnavailableReason.BACKENDS_UNAVAILABLE)
        )
        return 0

    try:
        _write_helper_message(output_stream, ReadyMessage(backend.backend))
        backend.run(input_stream)
    except ProtocolError:
        with contextlib.suppress(Exception):
            _write_helper_message(
                output_stream, UnavailableMessage(UnavailableReason.PROTOCOL_ERROR)
            )
        return 1
    except Exception:
        with contextlib.suppress(Exception):
            _write_helper_message(output_stream, UnavailableMessage(UnavailableReason.BACKEND_LOST))
        return 1
    finally:
        with contextlib.suppress(Exception):
            backend.close()
    return 0


def private_entry_requested(argv: Sequence[str]) -> bool:
    """Recognize the exact non-argparse helper entry path."""
    return tuple(argv) == ("_overlay",)
