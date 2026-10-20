# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in capture test for a real PipeWire output monitor."""

from __future__ import annotations

import shutil
import subprocess
import time

import numpy as np
import pytest

from stenographer.lib.platform import current_platform
from stenographer.lib.platform.errors import SystemAudioCaptureError
from stenographer.lib.platform.linux.system_audio import (
    _CAPTURE_NODE,
    _has_sink_monitor_links,
    _parse_pw_dump_output,
    _parse_pw_link_output,
)


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
        sink_result = subprocess.run(
            [shutil.which("pactl") or "pactl", "get-default-sink"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        sink = sink_result.stdout.strip()
        pw_link = shutil.which("pw-link")
        if pw_link is not None:
            result = subprocess.run(
                [pw_link, "-l"], capture_output=True, text=True, check=True, timeout=5
            )
            ports, links = _parse_pw_link_output(result.stdout)
        else:
            pw_dump = shutil.which("pw-dump")
            assert pw_dump is not None
            result = subprocess.run(
                [pw_dump], capture_output=True, text=True, check=True, timeout=5
            )
            ports, links = _parse_pw_dump_output(result.stdout)
        assert _has_sink_monitor_links(ports, links, sink, _CAPTURE_NODE)
        time.sleep(3)
    finally:
        capture.stop()

    assert not errors, errors
    assert sum(block.size for block in blocks) >= 3 * 16000
    samples = np.concatenate(blocks)
    rms = float(np.sqrt(np.mean(np.square(samples))))
    assert rms > 0.0, "play audio during the capture"
