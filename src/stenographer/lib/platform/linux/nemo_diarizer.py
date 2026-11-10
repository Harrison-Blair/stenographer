# SPDX-License-Identifier: GPL-3.0-or-later
"""``SpeakerDiarizer`` over NeMo-Speech.cpp, run in a helper process.

The helper isolates the library's own libstdc++ and OpenMP from the app, caps
its threads, and keeps a native crash out of the app. One helper serves every
stream opened from one ``NemoSpeakerDiarizer``; the library runs their work one
after the other.
"""

from __future__ import annotations

import collections
import contextlib
import itertools
import multiprocessing
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from stenographer.lib.platform.errors import SpeakerDiarizerError
from stenographer.lib.platform.linux.nemo_diarizer_child import child_main
from stenographer.lib.platform.linux.nemo_speech import (
    LIVE,
    OFFLINE,
    Geometry,
    host_unavailable_reason,
)
from stenographer.lib.platform.speaker_diarizer import (
    LIVE_QUEUE_SECONDS,
    SAMPLE_RATE,
    THREADS,
    LivePoll,
    SpeakerSegment,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from multiprocessing.connection import Connection

# The helper loads only the C library before it reports ready; the model loads
# on the first stream.
_START_SECONDS = 30.0
_OPEN_SECONDS = 60.0
# Saved audio goes to the helper in blocks of this length, one block in flight.
FILE_BLOCK_SECONDS = 30.0
_POLL_SECONDS = 0.05


def file_blocks(
    source: Path | np.ndarray | Iterable[np.ndarray], block_seconds: float
) -> Iterator[tuple[np.ndarray, int, float | None]]:
    """Yield ``(mono float32 block, rate, share done)`` of a file, of samples, or of
    blocks of samples; the share is ``None`` for blocks, whose length is unknown."""
    if not isinstance(source, (np.ndarray, str, Path)):
        step = int(block_seconds * SAMPLE_RATE)
        pending: list[np.ndarray] = []
        held = 0
        for block in source:
            pending.append(np.asarray(block, np.float32))
            held += len(block)
            if held >= step:
                yield np.concatenate(pending), SAMPLE_RATE, None
                pending, held = [], 0
        if pending:
            yield np.concatenate(pending), SAMPLE_RATE, None
        return
    if isinstance(source, np.ndarray):
        total = max(len(source), 1)
        step = int(block_seconds * SAMPLE_RATE)
        for start in range(0, len(source), step):
            block = source[start : start + step]
            yield block.astype(np.float32, copy=False), SAMPLE_RATE, (start + len(block)) / total
        return
    import soundfile

    with soundfile.SoundFile(str(source)) as sound:
        total = max(sound.frames, 1)
        done = 0
        for block in sound.blocks(blocksize=int(block_seconds * sound.samplerate), dtype="float32"):
            if block.ndim == 2:
                block = block.mean(axis=1, dtype=np.float32)
            done += len(block)
            yield block, sound.samplerate, done / total


class _Stream:
    """Parent-side state of one stream; the reader thread fills it.

    Audio the helper has not handled yet is bounded by ``LIVE_QUEUE_SECONDS``. A
    push past the bound overflows the stream: its queued audio is released, the
    helper closes it, and it gives no more labels.
    """

    def __init__(self, owner: NemoSpeakerDiarizer, sid: int, source: str) -> None:
        self._owner = owner
        self._sid = sid
        self._source = source
        self._changed = threading.Condition()
        self._opened = False
        self._final: list[SpeakerSegment] = []
        self._tail: tuple[SpeakerSegment, ...] = ()
        self._final_until = float("-inf")
        # Seconds of each push the helper has not answered, oldest first.
        self._unanswered: collections.deque[float] = collections.deque()
        self._queued_seconds = 0.0
        self._overflowed = False
        self._finished: tuple[SpeakerSegment, ...] | None = None
        self._error: str | None = None

    # --- reader thread ---
    def on_message(self, message: tuple) -> None:
        kind = message[0]
        with self._changed:
            if self._overflowed:
                return  # replies to audio sent before the overflow
            if kind == "opened":
                self._opened = True
            elif kind in ("pushed", "update"):
                self._queued_seconds -= self._unanswered.popleft()
                if kind == "update":
                    self._final.extend(message[2])
                    self._tail = message[3]
                    self._final_until = message[4]
            elif kind == "finished":
                self._final.extend(message[2])
                self._tail = ()
                self._final_until = float("inf")
                self._finished = tuple(self._final)
            elif kind == "failed":
                self._error = f"{self._source} speaker separation failed: {message[2]}"
            self._changed.notify_all()

    def fail(self, reason: str) -> None:
        with self._changed:
            if self._error is None and not self._overflowed:
                self._error = reason
            self._changed.notify_all()

    # --- caller ---
    @property
    def queued_seconds(self) -> float:
        """Seconds of pushed audio the helper has not handled yet."""
        with self._changed:
            return self._queued_seconds

    def overflowed(self) -> bool:
        with self._changed:
            return self._overflowed

    def _wait(self, done: Callable[[], bool], timeout: float | None) -> None:
        with self._changed:
            if not self._changed.wait_for(lambda: done() or self._error is not None, timeout):
                raise SpeakerDiarizerError(f"{self._source} speaker separation timed out")
            if self._error is not None:
                raise SpeakerDiarizerError(self._error)

    def wait_open(self) -> None:
        self._wait(lambda: self._opened, _OPEN_SECONDS)

    def push(self, samples: np.ndarray, rate: int = SAMPLE_RATE) -> None:
        seconds = len(samples) / rate
        with self._changed:
            if self._overflowed:
                return
            if self._queued_seconds + seconds <= LIVE_QUEUE_SECONDS:
                self._queued_seconds += seconds
                self._unanswered.append(seconds)
                self._owner.send(
                    ("push", self._sid, np.asarray(samples, np.float32).tobytes(), rate)
                )
                return
            self._overflowed = True
            self._tail = ()
            self._unanswered.clear()
            self._queued_seconds = 0.0
        self._owner.forget(self._sid)

    def wait_replies(self, should_cancel: Callable[[], bool]) -> bool:
        """Wait until the helper has handled every push; False on a cancel."""
        while True:
            with self._changed:
                if self._error is not None:
                    raise SpeakerDiarizerError(self._error)
                if not self._unanswered:
                    return True
                self._changed.wait(_POLL_SECONDS)
            if should_cancel():
                return False

    def poll(self) -> LivePoll:
        # One lock: the reader thread changes finals, tail, and final edge together.
        with self._changed:
            if self._error is not None:
                raise SpeakerDiarizerError(self._error)
            final = tuple(self._final)
            self._final.clear()
            return LivePoll(final, self._tail, self._final_until)

    def finish(self, timeout: float) -> tuple[SpeakerSegment, ...]:
        with self._changed:
            if self._overflowed:
                final = tuple(self._final)
                self._final.clear()
                return final
        self._owner.send(("finish", self._sid))
        self._wait(lambda: self._finished is not None, timeout)
        with self._changed:
            self._final.clear()
            return self._finished

    def close(self) -> None:
        self._owner.forget(self._sid)


_REPLIES = frozenset({"opened", "pushed", "update", "finished", "failed"})


def _kind(message: object) -> object:
    """The kind of a helper message, or ``None`` when it is not a message."""
    return message[0] if isinstance(message, tuple) and message else None


class NemoSpeakerDiarizer:
    """The ``SpeakerDiarizer`` of Linux. *threads* caps the helper's CPU threads.

    *child* is the helper's entry point; tests replace it.
    """

    def __init__(
        self,
        threads: int = THREADS,
        live_geometry: Geometry = LIVE,
        *,
        child: Callable[..., None] = child_main,
    ) -> None:
        self._threads = threads
        self._live_geometry = live_geometry
        self._child = child
        self._lock = threading.Lock()
        self._streams: dict[int, _Stream] = {}
        self._ids = itertools.count()
        self._process = None
        self._commands: Connection | None = None
        # Messages for the helper, one queue per stream in order. The sender thread
        # takes one message from each waiting stream in turn, so a stream that is
        # behind never delays another. Each queue is bounded by its stream.
        self._queues: dict[int, collections.deque[tuple]] = {}
        self._turns: collections.deque[int] = collections.deque()
        self._outbox_ready = threading.Condition()
        self._sending = False
        self._failure: str | None = None

    def unavailable_reason(self) -> str | None:
        return host_unavailable_reason()

    @property
    def pid(self) -> int | None:
        return None if self._process is None else self._process.pid

    def _start(self) -> None:
        reason = self.unavailable_reason()
        if reason is not None:
            raise SpeakerDiarizerError(reason)
        # The one boundary: every error of starting the helper or of its first answer
        # becomes a SpeakerDiarizerError, and whatever was made is closed.
        ends: list[Connection] = []
        process = None
        try:
            context = multiprocessing.get_context("spawn")
            commands_read, commands_write = context.Pipe(duplex=False)
            ends += (commands_read, commands_write)
            results_read, results_write = context.Pipe(duplex=False)
            ends += (results_read, results_write)
            process = context.Process(
                target=self._child, args=(commands_read, results_write, self._threads), daemon=True
            )
            try:
                process.start()
            except OSError as exc:
                process = None
                raise SpeakerDiarizerError(f"the speaker helper could not start: {exc}") from exc
            # The parent holds no child end, so the death of the child shows end of file.
            commands_read.close()
            results_write.close()
            if not results_read.poll(_START_SECONDS):
                raise SpeakerDiarizerError("the speaker helper did not start")
            try:
                message = results_read.recv()
            except Exception as exc:  # EOF, a dead pipe, or a reply that does not unpickle
                process.join(1)
                raise SpeakerDiarizerError(
                    f"the speaker helper ended (exit code {process.exitcode})"
                ) from exc
            if _kind(message) == "failed" and len(message) > 2:
                raise SpeakerDiarizerError(str(message[2]))
            if _kind(message) != "ready":
                raise SpeakerDiarizerError("the speaker helper gave an unexpected reply")
        except Exception as exc:
            if process is not None:
                process.kill()
                process.join()
            for end in ends:
                end.close()
            if isinstance(exc, SpeakerDiarizerError):
                raise
            raise SpeakerDiarizerError(f"the speaker helper could not start: {exc}") from exc
        self._process = process
        self._commands = commands_write
        with self._outbox_ready:
            self._sending = True
        threading.Thread(target=self._send_loop, args=(commands_write,), daemon=True).start()
        threading.Thread(target=self._read_loop, args=(results_read, process), daemon=True).start()

    def _send_loop(self, commands: Connection) -> None:
        while True:
            with self._outbox_ready:
                self._outbox_ready.wait_for(lambda: self._turns or not self._sending)
                if not self._sending:
                    return
                sid = self._turns.popleft()
                waiting = self._queues[sid]
                message = waiting.popleft()
                if waiting:
                    self._turns.append(sid)
                else:
                    del self._queues[sid]
            try:
                commands.send(message)
            except OSError:
                return  # the reader thread reports the dead helper

    def _read_loop(self, results: Connection, process) -> None:
        reason = None
        while reason is None:
            try:
                message = results.recv()
            except (EOFError, OSError):
                break
            except Exception:  # a reply that does not unpickle
                reason = "the speaker helper gave an unexpected reply"
                break
            if _kind(message) not in _REPLIES or len(message) < 2:
                reason = "the speaker helper gave an unexpected reply"
                break
            with self._lock:
                stream = self._streams.get(message[1])
            if stream is not None:
                try:
                    stream.on_message(message)
                except Exception:  # a known kind with the wrong shape or order
                    reason = "the speaker helper gave an unexpected reply"
        if reason is not None:
            process.kill()
        process.join()
        results.close()
        self._fail_all(reason or f"the speaker helper ended (exit code {process.exitcode})")

    def _fail_all(self, reason: str) -> None:
        with self._lock:
            if self._failure is None:
                self._failure = reason
            streams = list(self._streams.values())
        for stream in streams:
            stream.fail(reason)

    def send(self, message: tuple) -> None:
        """Queue *message* behind the earlier messages of its stream (``message[1]``)."""
        sid = message[1]
        with self._outbox_ready:
            if not self._sending:
                return
            if sid not in self._queues:
                self._queues[sid] = collections.deque()
                self._turns.append(sid)
            self._queues[sid].append(message)
            self._outbox_ready.notify()

    def queued_pushes(self, sid: int) -> int:
        """Pushes of stream *sid* still waiting to go to the helper."""
        with self._outbox_ready:
            return sum(1 for m in self._queues.get(sid, ()) if m[0] == "push")

    def forget(self, sid: int) -> None:
        """End stream *sid*: drop everything it still has queued and close it in the
        helper. A push the helper is handling may finish; its reply is ignored."""
        with self._lock:
            known = self._streams.pop(sid, None) is not None
        with self._outbox_ready:
            if self._queues.pop(sid, None) is not None:
                self._turns.remove(sid)
        if known:
            self.send(("close", sid))

    def _open(self, source: str, geometry: Geometry) -> _Stream:
        with self._lock:
            if self._failure is not None:
                raise SpeakerDiarizerError(self._failure)
            if self._process is None:
                self._start()
            sid = next(self._ids)
            stream = _Stream(self, sid, source)
            self._streams[sid] = stream
        self.send(("open", sid, geometry))
        try:
            stream.wait_open()
        except SpeakerDiarizerError:
            stream.close()
            raise
        return stream

    def open_live(self, source: str) -> _Stream:
        return self._open(source, self._live_geometry)

    def diarize_file(
        self,
        source: Path | np.ndarray | Iterable[np.ndarray],
        *,
        progress: Callable[[float], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[SpeakerSegment, ...] | None:
        should_cancel = should_cancel or (lambda: False)
        stream = self._open("file", OFFLINE)
        try:
            for block, rate, done in file_blocks(source, FILE_BLOCK_SECONDS):
                stream.push(block, rate)
                if not stream.wait_replies(should_cancel):
                    return None
                if progress is not None and done is not None:
                    progress(done)
            segments = stream.finish(timeout=_OPEN_SECONDS)
        finally:
            stream.close()
        return tuple(sorted(segments, key=lambda s: (s.start, s.speaker)))

    def close(self) -> None:
        with self._lock:
            process, self._process = self._process, None
            if self._failure is None:
                self._failure = "speaker separation was stopped"
        with self._outbox_ready:
            self._sending = False
            self._queues.clear()
            self._turns.clear()
            self._outbox_ready.notify_all()
        if process is not None:
            process.kill()
            process.join()
        if self._commands is not None:
            with contextlib.suppress(OSError):
                self._commands.close()
        self._fail_all("speaker separation was stopped")
