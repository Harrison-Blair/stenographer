# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``pw-record`` stdout stream, shared by the microphone and the system capture.

``pw-record --format f32 -`` writes 16 kHz mono float32 to a pipe. Older
PipeWire (1.0.5 on Ubuntu 24.04) writes raw little-endian samples. PipeWire
1.6 writes an AU file instead: a ``.snd`` header, then big-endian samples.
:class:`PwRecordDecoder` reads both and frames the samples into blocks.
"""

from __future__ import annotations

import os
import struct
import subprocess
import threading
from collections.abc import Callable

import numpy as np

from stenographer.lib.platform.errors import PwRecordFormatError

RATE = 16000
BLOCK_FRAMES = 512
_SAMPLE_BYTES = 4
_AU_MAGIC = b".snd"
_AU_HEADER_BYTES = 24
_AU_FLOAT32 = 6


class PwRecordDecoder:
    """Turn ``pw-record`` stdout bytes into float32 blocks of ``BLOCK_FRAMES`` samples. PURE."""

    def __init__(self) -> None:
        self._pending = bytearray()
        self._dtype: str | None = None
        self._skip = 0

    def feed(self, chunk: bytes) -> list[np.ndarray]:
        """Add *chunk* and return every complete block."""
        self._pending.extend(chunk)
        if self._dtype is None and not self._read_header():
            return []
        if self._skip:
            dropped = min(self._skip, len(self._pending))
            del self._pending[:dropped]
            self._skip -= dropped
        block_bytes = BLOCK_FRAMES * _SAMPLE_BYTES
        blocks = []
        while len(self._pending) >= block_bytes:
            blocks.append(self._samples(self._pending[:block_bytes]))
            del self._pending[:block_bytes]
        return blocks

    def discard(self) -> None:
        """Drop the buffered whole samples; keep a partial sample and the format."""
        whole = len(self._pending) - len(self._pending) % _SAMPLE_BYTES
        if self._dtype is not None:
            del self._pending[:whole]

    def finish(self) -> np.ndarray | None:
        """Return the last short block at end of stream, or ``None``."""
        if len(self._pending) % _SAMPLE_BYTES:
            raise PwRecordFormatError("pw-record ended in the middle of a float32 sample")
        if not self._pending or self._dtype is None:
            return None
        block = self._samples(self._pending)
        self._pending.clear()
        return block

    def _read_header(self) -> bool:
        if len(self._pending) < len(_AU_MAGIC):
            return False
        if self._pending[: len(_AU_MAGIC)] != _AU_MAGIC:
            self._dtype = "<f4"
            return True
        if len(self._pending) < _AU_HEADER_BYTES:
            return False
        offset, _size, encoding, rate, channels = struct.unpack(
            ">IIIII", self._pending[4:_AU_HEADER_BYTES]
        )
        if (encoding, rate, channels) != (_AU_FLOAT32, RATE, 1) or offset < _AU_HEADER_BYTES:
            raise PwRecordFormatError(
                f"pw-record wrote AU encoding {encoding} at {rate} Hz with {channels} channels"
            )
        self._dtype = ">f4"
        self._skip = offset
        return True

    def _samples(self, raw: bytes | bytearray) -> np.ndarray:
        assert self._dtype is not None
        return np.frombuffer(bytes(raw), dtype=self._dtype).astype(np.float32)


def discard_pending(process: subprocess.Popen, decoder: PwRecordDecoder) -> None:
    """Read what the pipe holds now into *decoder* and drop its samples."""
    assert process.stdout is not None
    file_descriptor = process.stdout.fileno()
    os.set_blocking(file_descriptor, False)
    try:
        while True:
            try:
                chunk = os.read(file_descriptor, 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            decoder.feed(chunk)
            decoder.discard()
    finally:
        os.set_blocking(file_descriptor, True)


def read_stdout(
    process: subprocess.Popen,
    decoder: PwRecordDecoder,
    on_block: Callable[[object], None],
    stopping: threading.Event,
    error_type: type[Exception],
) -> None:
    """Reader thread: send each block to *on_block*, then an *error_type* if the stream failed.

    A stream that ends while *stopping* is not set is a failure.
    """
    assert process.stdout is not None
    read_error: Exception | None = None
    try:
        while True:
            chunk = process.stdout.read(BLOCK_FRAMES * _SAMPLE_BYTES)
            if not chunk:
                break
            for block in decoder.feed(chunk):
                _deliver(on_block, block)
        tail = decoder.finish()
        if tail is not None:
            _deliver(on_block, tail)
    except PwRecordFormatError as exc:
        read_error = error_type(str(exc))
    except OSError:
        read_error = error_type("could not read pw-record audio")

    if read_error is not None:
        _deliver(on_block, read_error)
    elif not stopping.is_set():
        status = process.wait()
        _deliver(on_block, error_type(f"pw-record exited unexpectedly with status {status}"))


def _deliver(on_block: Callable[[object], None], item: object) -> None:
    try:
        on_block(item)
    except Exception:
        return


def terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
