# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers for saved session tests."""

import io
from datetime import UTC, datetime

import numpy as np
import soundfile as sf

from stenographer.lib.live.session_writer import SessionWriter


def make_recording(root, lines, started_at=datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)):
    writer = SessionWriter.open(root, started_at)
    writer.write_audio("system", np.zeros(16000, dtype=np.float32))
    for line in lines:
        writer.append_line(line)
    writer.close()
    return writer.path


def write_unknown_length_flac(path):
    """Write a FLAC file of only its header whose STREAMINFO gives no total sample count.

    A recording whose source gave no audio leaves such a file.
    """
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(16000, dtype=np.float32), 16000, format="FLAC")
    data = bytearray(buffer.getvalue())
    # The 36 bits of total samples: the low 4 bits of byte 21, then bytes 22 to 25.
    data[21] &= 0xF0
    data[22:26] = bytes(4)
    # Cut the file after the last metadata block, before the first audio frame.
    offset = 4
    while True:
        header = data[offset]
        offset += 4 + int.from_bytes(data[offset + 1 : offset + 4], "big")
        if header & 0x80:
            break
    path.write_bytes(bytes(data[:offset]))
    # libsndfile reports an unknown count as SF_COUNT_MAX (2**63 - 1).
    assert sf.info(path).frames == 2**63 - 1
    return path
