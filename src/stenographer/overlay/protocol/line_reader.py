# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from stenographer.overlay.protocol.constants import MAX_MESSAGE_BYTES
from stenographer.overlay.protocol.errors import ProtocolError


class LineReader:
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
