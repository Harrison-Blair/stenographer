# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux system audio capture through real child processes."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from stenographer.lib.platform.errors import SystemAudioCaptureError
from stenographer.lib.platform.linux.system_audio import LinuxSystemAudioCapture

_PW_LINK_FIXTURE = """studio:monitor_AUX0
  |-> stenographer-system-capture:input_FL
studio:monitor_AUX1
  |-> stenographer-system-capture:input_FR
studio:playback_AUX0
  |<- spotify:output_FL
  |<- Firefox:output_FL
studio:playback_AUX1
  |<- spotify:output_FR
  |<- Firefox:output_FR
microphone:capture_FL
  |-> stenographer-mic:input_FL
microphone:capture_FR
  |-> stenographer-mic:input_FR
stenographer-system-capture:input_FL
  |<- studio:monitor_AUX0
stenographer-system-capture:input_FR
  |<- studio:monitor_AUX1
spotify:output_FL
  |-> studio:playback_AUX0
spotify:output_FR
  |-> studio:playback_AUX1
stenographer-mic:input_FL
  |<- microphone:capture_FL
stenographer-mic:input_FR
  |<- microphone:capture_FR
Firefox:output_FL
  |-> studio:playback_AUX0
Firefox:output_FR
  |-> studio:playback_AUX1
"""

_CAPTURE_SCRIPT = f"""#!{sys.executable}
import json
import os
import struct
import sys
import time
from pathlib import Path

Path(os.environ['PW_CAPTURE_ARGS']).write_text(json.dumps(sys.argv[1:]))
Path(os.environ['PW_CAPTURE_PID']).write_text(str(os.getpid()))
order = '<'
if os.environ.get('PW_AU') == '1':
    # PipeWire 1.6 writes an AU file to a pipe: a header, then big-endian samples.
    order = '>'
    sys.stdout.buffer.write(b'.snd' + struct.pack('>5I', 24, 0xFFFFFFFF, 6, 16000, 1))
sys.stdout.buffer.write(struct.pack(order + '4f', 9.0, 9.0, 9.0, 9.0))
sys.stdout.buffer.flush()
time.sleep(0.3)
sys.stdout.buffer.write(struct.pack(order + '512f', 0.25, -0.5, 0.75, -1.0, *([0.0] * 508)))
sys.stdout.buffer.flush()
if os.environ.get('PW_EXIT_EARLY') == '1':
    raise SystemExit(17)
while True:
    time.sleep(0.05)
"""

_LINK_SCRIPT = f"""#!{sys.executable}
import os
import sys
import time
from pathlib import Path

time.sleep(float(os.environ.get('PW_LINK_DELAY', '0.15')))
sys.stdout.write(Path(os.environ['PW_LINK_OUTPUT']).read_text())
"""


def _install_tools(
    tmp_path: Path,
    monkeypatch,
    *,
    early_exit: bool = False,
    link_output: str | None = None,
    include_link_tool: bool = True,
    au: bool = False,
) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pactl = bin_dir / "pactl"
    pactl.write_text("#!/bin/sh\nprintf 'studio\\n'\n")
    pactl.chmod(0o755)
    pw_record = bin_dir / "pw-record"
    pw_record.write_text(_CAPTURE_SCRIPT)
    pw_record.chmod(0o755)
    link_output_path = tmp_path / "links.txt"
    link_output_path.write_text(_PW_LINK_FIXTURE if link_output is None else link_output)
    if include_link_tool:
        pw_link = bin_dir / "pw-link"
        pw_link.write_text(_LINK_SCRIPT)
        pw_link.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PW_CAPTURE_ARGS", str(tmp_path / "args.txt"))
    monkeypatch.setenv("PW_CAPTURE_PID", str(tmp_path / "pid.txt"))
    monkeypatch.setenv("PW_LINK_OUTPUT", str(link_output_path))
    monkeypatch.setenv("PW_LINK_DELAY", "0.15")
    if au:
        monkeypatch.setenv("PW_AU", "1")
    else:
        monkeypatch.delenv("PW_AU", raising=False)
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

    received = threading.Event()

    def receive(block):
        blocks.append(block)
        if isinstance(block, np.ndarray):
            received.set()

    capture.start(receive)
    try:
        deadline = time.monotonic() + 2
        while not args_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert args_file.exists()
        assert json.loads(args_file.read_text()) == [
            "-P",
            "{ stream.capture.sink = true, node.name = stenographer-system-capture }",
            "--target",
            "studio",
            "--rate",
            "16000",
            "--channels",
            "1",
            "--format",
            "f32",
            "-",
        ]
        assert received.wait(timeout=2)
    finally:
        capture.stop()

    audio = np.concatenate([block for block in blocks if isinstance(block, np.ndarray)])
    assert np.array_equal(audio[:4], np.array([0.25, -0.5, 0.75, -1.0], dtype=np.float32))
    assert np.count_nonzero(audio[4:]) == 0
    arrays = [block for block in blocks if isinstance(block, np.ndarray)]
    assert all(block.dtype == np.float32 and block.ndim == 1 for block in arrays)
    assert capture._thread is not None and not capture._thread.is_alive()
    assert capture._process is None


def test_capture_decodes_the_au_stream_of_pipewire_1_6(tmp_path, monkeypatch):
    # The header arrives before the link check, whose discard must not lose it.
    _install_tools(tmp_path, monkeypatch, au=True)
    capture = LinuxSystemAudioCapture()
    blocks: list[np.ndarray | SystemAudioCaptureError] = []
    received = threading.Event()

    def receive(block):
        blocks.append(block)
        if isinstance(block, np.ndarray):
            received.set()

    capture.start(receive)
    try:
        assert received.wait(timeout=2)
    finally:
        capture.stop()

    audio = np.concatenate([block for block in blocks if isinstance(block, np.ndarray)])
    assert np.array_equal(audio[:4], np.array([0.25, -0.5, 0.75, -1.0], dtype=np.float32))
    assert np.count_nonzero(audio[4:]) == 0
    assert not any(isinstance(block, SystemAudioCaptureError) for block in blocks)


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


def test_capture_reports_player_exit_before_link(tmp_path, monkeypatch):
    _install_tools(tmp_path, monkeypatch, link_output="")
    player = tmp_path / "bin" / "pw-record"
    player.write_text("#!/bin/sh\nexit 2\n")
    with pytest.raises(
        SystemAudioCaptureError, match="pw-record exited before system capture connected"
    ):
        LinuxSystemAudioCapture().start(lambda block: None)


@pytest.mark.parametrize(
    "link_output",
    [
        pytest.param(
            "microphone:capture_FL\n"
            "  |-> stenographer-system-capture:input_FL\n"
            "microphone:capture_FR\n"
            "  |-> stenographer-system-capture:input_FR\n",
            id="wrong_monitor",
        ),
        pytest.param("", id="no_links"),
    ],
)
def test_capture_without_a_monitor_link_stops_after_a_bounded_wait_and_emits_no_audio(
    tmp_path, monkeypatch, link_output
):
    _install_tools(tmp_path, monkeypatch, link_output=link_output)
    capture = LinuxSystemAudioCapture()
    blocks: list[np.ndarray | SystemAudioCaptureError] = []

    started = time.monotonic()
    try:
        with pytest.raises(SystemAudioCaptureError, match="not linked to the sink monitor"):
            capture.start(blocks.append)
    finally:
        capture.stop()
    elapsed = time.monotonic() - started

    assert 1.5 <= elapsed < 3
    assert blocks == []
    assert capture._process is None
    process_id = int((tmp_path / "pid.txt").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(process_id, 0)


def test_capture_reports_missing_pw_record_as_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    capture = LinuxSystemAudioCapture()

    available, reason = capture.available()

    assert available is False
    assert reason is not None and "pw-record" in reason


def test_capture_requires_a_link_inspection_tool(tmp_path, monkeypatch):
    _install_tools(tmp_path, monkeypatch, include_link_tool=False)
    capture = LinuxSystemAudioCapture()

    available, reason = capture.available()

    assert available is False
    assert reason is not None and "pw-link" in reason and "pw-dump" in reason
