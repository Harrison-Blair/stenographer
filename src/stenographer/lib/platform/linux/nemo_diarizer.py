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
    SpeakerSegment,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from multiprocessing.connection import Connection
    from pathlib import Path

# The helper loads only the C library before it reports ready; the model loads
# on the first stream.
_START_SECONDS = 30.0
_OPEN_SECONDS = 60.0
# Saved audio goes to the helper in blocks of this length, one block in flight.
FILE_BLOCK_SECONDS = 30.0
_POLL_SECONDS = 0.05


def file_blocks(
    source: Path | np.ndarray, block_seconds: float
) -> Iterator[tuple[np.ndarray, int, float]]:
    """Yield ``(mono float32 block, rate, share done)`` of a file or of samples."""
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
            elif kind == "finished":
                self._final.extend(message[2])
                self._tail = ()
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
        self._owner.release(self._sid)

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

    def poll(self) -> tuple[tuple[SpeakerSegment, ...], tuple[SpeakerSegment, ...]]:
        with self._changed:
            if self._error is not None:
                raise SpeakerDiarizerError(self._error)
            final = tuple(self._final)
            self._final.clear()
            return final, self._tail

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
        # Messages for the helper, in order; the sender thread drains it.
        self._outbox: collections.deque[tuple] = collections.deque()
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
        context = multiprocessing.get_context("spawn")
        commands_read, commands_write = context.Pipe(duplex=False)
        results_read, results_write = context.Pipe(duplex=False)
        process = context.Process(
            target=self._child, args=(commands_read, results_write, self._threads), daemon=True
        )
        process.start()
        # The parent holds no child end, so the death of the child shows end of file.
        commands_read.close()
        results_write.close()
        try:
            if not results_read.poll(_START_SECONDS):
                raise SpeakerDiarizerError("the speaker helper did not start")
            message = results_read.recv()
        except (EOFError, OSError):
            message = ("failed", None, f"the speaker helper ended (exit code {process.exitcode})")
        except SpeakerDiarizerError:
            process.kill()
            raise
        if message[0] != "ready":
            process.kill()
            process.join()
            raise SpeakerDiarizerError(message[2])
        self._process = process
        self._commands = commands_write
        with self._outbox_ready:
            self._sending = True
        threading.Thread(target=self._send_loop, args=(commands_write,), daemon=True).start()
        threading.Thread(target=self._read_loop, args=(results_read, process), daemon=True).start()

    def _send_loop(self, commands: Connection) -> None:
        while True:
            with self._outbox_ready:
                self._outbox_ready.wait_for(lambda: self._outbox or not self._sending)
                if not self._sending:
                    return
                message = self._outbox.popleft()
            try:
                commands.send(message)
            except OSError:
                return  # the reader thread reports the dead helper

    def _read_loop(self, results: Connection, process) -> None:
        while True:
            try:
                message = results.recv()
            except (EOFError, OSError):
                break
            with self._lock:
                stream = self._streams.get(message[1])
            if stream is not None:
                stream.on_message(message)
        process.join()
        self._fail_all(f"the speaker helper ended (exit code {process.exitcode})")

    def _fail_all(self, reason: str) -> None:
        with self._lock:
            if self._failure is None:
                self._failure = reason
            streams = list(self._streams.values())
        for stream in streams:
            stream.fail(reason)

    def send(self, message: tuple) -> None:
        with self._outbox_ready:
            if self._sending:
                self._outbox.append(message)
                self._outbox_ready.notify()

    def queued_pushes(self, sid: int) -> int:
        """Pushes of stream *sid* still waiting in the outbox."""
        with self._outbox_ready:
            return sum(1 for m in self._outbox if m[0] == "push" and m[1] == sid)

    def release(self, sid: int) -> None:
        """Drop the queued audio of stream *sid* and close it in the helper."""
        with self._outbox_ready:
            self._outbox = collections.deque(
                m for m in self._outbox if not (m[0] == "push" and m[1] == sid)
            )
        self.forget(sid)

    def forget(self, sid: int) -> None:
        with self._lock:
            known = self._streams.pop(sid, None) is not None
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
        source: Path | np.ndarray,
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
                if progress is not None:
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
            self._outbox.clear()
            self._outbox_ready.notify_all()
        if process is not None:
            process.kill()
            process.join()
        if self._commands is not None:
            with contextlib.suppress(OSError):
                self._commands.close()
        self._fail_all("speaker separation was stopped")
