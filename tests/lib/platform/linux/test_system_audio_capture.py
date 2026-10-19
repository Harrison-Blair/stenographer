# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux system audio capture through real child processes."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

from stenographer.lib.platform.errors import SystemAudioCaptureError
from stenographer.lib.platform.linux.system_audio import LinuxSystemAudioCapture

_CAPTURE_SCRIPT = f"""#!{sys.executable}
import os
import struct
import sys
import time
from pathlib import Path

Path(os.environ['PW_CAPTURE_ARGS']).write_text(' '.join(sys.argv[1:]))
sys.stdout.buffer.write(struct.pack('<4f', 0.25, -0.5, 0.75, -1.0))
sys.stdout.buffer.flush()
if os.environ.get('PW_EXIT_EARLY') == '1':
    raise SystemExit(17)
while True:
    time.sleep(0.05)
"""


def _install_tools(tmp_path: Path, monkeypatch, *, early_exit: bool = False) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pactl = bin_dir / "pactl"
    pactl.write_text("#!/bin/sh\nprintf 'studio\\n'\n")
    pactl.chmod(0o755)
    pw_record = bin_dir / "pw-record"
    pw_record.write_text(_CAPTURE_SCRIPT)
    pw_record.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PW_CAPTURE_ARGS", str(tmp_path / "args.txt"))
    if early_exit:
        monkeypatch.setenv("PW_EXIT_EARLY", "1")
    else:
        monkeypatch.delenv("PW_EXIT_EARLY", raising=False)
    return tmp_path / "args.txt"


def test_linux_capture_reads_raw_float_frames_and_stops_process(tmp_path, monkeypatch):
    args_file = _install_tools(tmp_path, monkeypatch)
    capture = LinuxSystemAudioCapture()
    blocks: list[np.ndarray | SystemAudioCaptureError] = []

    available, reason = capture.available()
    assert available is True
    assert reason is None

    capture.start(blocks.append)
    deadline = time.monotonic() + 2
    while not args_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    capture.stop()

    audio = np.concatenate([block for block in blocks if isinstance(block, np.ndarray)])
    assert np.array_equal(audio, np.array([0.25, -0.5, 0.75, -1.0], dtype=np.float32))
    arrays = [block for block in blocks if isinstance(block, np.ndarray)]
    assert all(block.dtype == np.float32 and block.ndim == 1 for block in arrays)
    assert args_file.read_text().split() == [
        "--raw",
        "--target",
        "studio.monitor",
        "--rate",
        "16000",
        "--channels",
        "1",
        "--format",
        "f32",
        "-",
    ]
    assert capture._thread is not None and not capture._thread.is_alive()
    assert capture._process is None


def test_early_process_exit_is_reported_to_callback(tmp_path, monkeypatch):
    _install_tools(tmp_path, monkeypatch, early_exit=True)
    capture = LinuxSystemAudioCapture()
    events: list[np.ndarray | SystemAudioCaptureError] = []

    capture.start(events.append)
    assert capture._thread is not None
    capture._thread.join(timeout=5)
    capture.stop()

    failures = [event for event in events if isinstance(event, SystemAudioCaptureError)]
    assert len(failures) == 1
    assert "exited unexpectedly" in str(failures[0])


def test_capture_reports_missing_pw_record_as_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    capture = LinuxSystemAudioCapture()

    available, reason = capture.available()

    assert available is False
    assert reason is not None and "pw-record" in reason
