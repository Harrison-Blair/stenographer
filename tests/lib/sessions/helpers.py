# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers for saved session tests."""

from datetime import UTC, datetime

import numpy as np

from stenographer.lib.live.session_writer import SessionWriter


def make_recording(root, lines, started_at=datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)):
    writer = SessionWriter.open(root, started_at)
    writer.write_audio("system", np.zeros(16000, dtype=np.float32))
    for line in lines:
        writer.append_line(line)
    writer.close()
    return writer.path
