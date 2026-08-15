# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated lifecycle-overlay helper supervision and backend selection.

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

from stenographer.status import (
    ERROR_DISPLAY_SECONDS,
    MAX_MESSAGE_BYTES,
    Command,
    CommandMessage,
    LifecycleEvent,
    LifecycleMessage,
    OverlayState,
    ProtocolError,
    ProtocolMessage,
    ReadyMessage,
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


class OutboundMailbox:
    """Bounded, generation-ordered metadata mailbox.

    Adjacent state updates coalesce to the newest generation.  Lifecycle
    records form ordering barriers, while the hard capacity always discards
    the oldest metadata.  Shutdown clears metadata and occupies the sole
    command slot.
    """

    def __init__(self, capacity: int = _MAILBOX_CAPACITY) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("mailbox capacity must be a positive integer")
        self._capacity = capacity
        self._pending: deque[StateMessage | LifecycleMessage] = deque()
        self._next_generation = 0
        self._closed = False
        self._shutdown_pending = False
        self._current_state = StateMessage(0, OverlayState.HIDDEN)
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

    def _append(self, message: StateMessage | LifecycleMessage) -> None:
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
            if self._closed:
                return self._current_state.generation
            message = StateMessage(self._generation(), state)
            self._append(message)
            self._current_state = message
            self._error_deadline = (
                time.monotonic() + ERROR_DISPLAY_SECONDS if state is OverlayState.ERROR else None
            )
            self._condition.notify()
            return message.generation

    def lifecycle(self, event: LifecycleEvent) -> int:
        if not isinstance(event, LifecycleEvent):
            raise TypeError("event must be a LifecycleEvent")
        with self._condition:
            if self._closed:
                return max(0, self._next_generation - 1)
            message = LifecycleMessage(self._generation(), event)
            self._append(message)
            self._condition.notify()
            return message.generation

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
            self._error_deadline = None
            self._shutdown_pending = True
            self._condition.notify_all()

    def take_nowait(self) -> ProtocolMessage | None:
        with self._condition:
            return self._take_locked()

    def take(self, timeout: float | None = None) -> ProtocolMessage | None:
        with self._condition:
            if not self._shutdown_pending and not self._pending:
                self._condition.wait(timeout)
            return self._take_locked()

    def _take_locked(self) -> ProtocolMessage | None:
        if self._shutdown_pending:
            self._shutdown_pending = False
            return CommandMessage(Command.SHUTDOWN)
        if self._pending:
            return self._pending.popleft()
        return None


class _LineReader:
    """Bounded incremental NDJSON framing shared by pipe and display loops."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        if not chunk:
            return []
        self._buffer.extend(chunk)
        records = []
        while (newline := self._buffer.find(b"\n")) >= 0:
            record = bytes(self._buffer[: newline + 1])
            del self._buffer[: newline + 1]
            if len(record) > MAX_MESSAGE_BYTES:
                raise ProtocolError("protocol record is too large")
            records.append(record)
        if len(self._buffer) >= MAX_MESSAGE_BYTES:
            raise ProtocolError("protocol record is too large")
        return records

    def finish(self) -> None:
        if self._buffer:
            raise ProtocolError("protocol stream ended mid-record")


@dataclass(frozen=True, slots=True)
class _ProcessOutcome:
    expected: bool
    unavailable: bool = False


class OverlaySupervisor:
    """Nonblocking daemon-side sink backed by one isolated helper process."""

    def __init__(self) -> None:
        self._mailbox = OutboundMailbox()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="stenographer-overlay-supervisor",
            daemon=True,
        )
        self._thread.start()

    def publish(self, state: OverlayState) -> None:
        self._mailbox.publish(state)

    def lifecycle(self, event: LifecycleEvent) -> None:
        self._mailbox.lifecycle(event)

    def close(self) -> None:
        self._mailbox.close()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=_THREAD_JOIN_SECONDS)

    def _thread_main(self) -> None:
        budget = RestartBudget(1)
        command = helper_command(sys.executable, frozen=bool(getattr(sys, "frozen", False)))
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

    def _serve(self, process: subprocess.Popen[bytes]) -> _ProcessOutcome:
        assert process.stdin is not None
        assert process.stdout is not None
        reader = _LineReader()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        ready = False
        started_at = time.monotonic()
        expected_exit = False
        unavailable = False

        # A restarted helper needs the current state even when its original
        # mailbox record was already consumed by the previous process.
        replay = self._mailbox.current_state
        if replay.state is not OverlayState.HIDDEN and not self._write(process.stdin, replay):
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
                if helper_ready_timed_out(started_at=started_at, now=time.monotonic(), ready=ready):
                    log.warning("overlay: helper_ready_timeout")
                    break
                self._mailbox.expire_error()
                message = self._mailbox.take_nowait()
                if message is not None:
                    if not self._write(process.stdin, message):
                        break
                    if isinstance(message, CommandMessage):
                        expected_exit = True
                        with contextlib.suppress(OSError):
                            process.stdin.close()

                for key, _events in selector.select(_POLL_SECONDS):
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
        from stenographer.overlay_wayland import LayerShellBackend

        return LayerShellBackend()
    except Exception:
        pass

    try:
        from stenographer.overlay_x11 import X11OverlayBackend

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
