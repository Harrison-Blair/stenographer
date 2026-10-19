# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in capture test for a real PipeWire output monitor."""

from __future__ import annotations

import time

import numpy as np
import pytest

from stenographer.lib.platform import current_platform
from stenographer.lib.platform.errors import SystemAudioCaptureError


@pytest.mark.integration
def test_default_monitor_captures_three_seconds_of_playing_audio():
    """Play audio during this test; it records three seconds from the default sink."""
    capture = current_platform().system_audio_capture()
    available, reason = capture.available()
    if not available:
        pytest.skip(reason or "system audio capture is unavailable")

    blocks: list[np.ndarray] = []
    errors: list[SystemAudioCaptureError] = []

    def receive(event: np.ndarray | SystemAudioCaptureError) -> None:
        if isinstance(event, SystemAudioCaptureError):
            errors.append(event)
        else:
            blocks.append(event)

    capture.start(receive)
    try:
        time.sleep(3)
    finally:
        capture.stop()

    assert not errors, errors
    assert sum(block.size for block in blocks) >= 3 * 16000
    assert any(np.any(block) for block in blocks), "play audio during the capture"
