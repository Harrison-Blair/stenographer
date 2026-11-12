# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux microphone capture through a real child process, and the pactl source list."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from stenographer.lib.platform.errors import MicCaptureError
from stenographer.lib.platform.linux.mic_capture import (
    LinuxMicCapture,
    input_sources,
    parse_pactl_sources,
    pw_record_command,
)
from stenographer.lib.platform.mic_capture import InputSource

_CAPTURE_SCRIPT = f"""#!{sys.executable}
import json
import os
import struct
import sys
import time
from pathlib import Path

Path(os.environ['PW_CAPTURE_ARGS']).write_text(json.dumps(sys.argv[1:]))
if os.environ.get('PW_TARGET_NOT_FOUND') == '1':
    # pw-record 1.0.5 on an absent target: a few raw bytes, then exit 1.
    sys.stdout.buffer.write(bytes(75))
    sys.stdout.buffer.flush()
    sys.stderr.write('target not found\\n')
    raise SystemExit(1)
encoding = int(os.environ.get('PW_AU_ENCODING', '6'))
sys.stdout.buffer.write(b'.snd' + struct.pack('>5I', 24, 0xFFFFFFFF, encoding, 16000, 1))
sys.stdout.buffer.write(struct.pack('>700f', 0.25, -0.5, *([0.0] * 698)))
sys.stdout.buffer.flush()
if os.environ.get('PW_EXIT_EARLY') == '1':
    raise SystemExit(1)
while True:
    time.sleep(0.05)
"""

_PACTL_SOURCES = [
    {"name": "alsa_output.usb-headset.monitor", "description": "Monitor of Headset"},
    {"name": "alsa_input.usb-HyperX-00.iec958-stereo", "description": "HyperX QuadCast 2 S"},
    {"name": "steno_build_mic", "description": "steno_build_mic"},
    {"name": "nameless_description"},
]


def _install(tmp_path: Path, monkeypatch, *, early_exit: bool = False) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pw_record = bin_dir / "pw-record"
    pw_record.write_text(_CAPTURE_SCRIPT)
    pw_record.chmod(0o755)
    (tmp_path / "sources.json").write_text(json.dumps(_PACTL_SOURCES))
    pactl = bin_dir / "pactl"
    pactl.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "if sys.argv[1:] == ['get-default-source']:\n"
        "    print('steno_build_mic')\n"
        "else:\n"
        f"    print(open({str(tmp_path / 'sources.json')!r}).read())\n"
    )
    pactl.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PW_CAPTURE_ARGS", str(tmp_path / "args.txt"))
    if early_exit:
        monkeypatch.setenv("PW_EXIT_EARLY", "1")
    else:
        monkeypatch.delenv("PW_EXIT_EARLY", raising=False)
    return tmp_path / "args.txt"


def test_the_default_source_has_no_target_and_a_named_one_never_falls_back():
    assert pw_record_command("pw-record", None) == [
        "pw-record",
        "--rate",
        "16000",
        "--channels",
        "1",
        "--format",
        "f32",
        "-",
    ]
    assert pw_record_command("pw-record", "steno_build_mic")[:4] == [
        "pw-record",
        "-P",
        "{ node.dont-fallback = true node.dont-reconnect = true }",
        "--target",
    ]


def test_capture_delivers_decoded_blocks_and_stop_ends_the_child(tmp_path, monkeypatch):
    args_file = _install(tmp_path, monkeypatch)
    capture = LinuxMicCapture()
    items: list[np.ndarray | MicCaptureError] = []
    got = threading.Event()

    def receive(item):
        items.append(item)
        got.set()

    capture.start("steno_build_mic", receive)
    try:
        assert got.wait(timeout=2)
        deadline = time.monotonic() + 2
        while sum(i.size for i in items if isinstance(i, np.ndarray)) < 512:
            assert time.monotonic() < deadline
            time.sleep(0.01)
    finally:
        process = capture._process
        capture.stop()

    assert process is not None and process.poll() is not None
    assert json.loads(args_file.read_text())[2:4] == ["--target", "steno_build_mic"]
    audio = np.concatenate([i for i in items if isinstance(i, np.ndarray)])
    assert audio[:2].tolist() == [0.25, -0.5]
    assert not any(isinstance(i, MicCaptureError) for i in items)
    assert capture._process is None


def test_a_child_that_exits_during_capture_is_reported(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch, early_exit=True)
    capture = LinuxMicCapture()
    items: list[np.ndarray | MicCaptureError] = []

    capture.start(None, items.append)
    assert capture._thread is not None
    capture._thread.join(timeout=5)
    capture.stop()

    failures = [i for i in items if isinstance(i, MicCaptureError)]
    assert len(failures) == 1
    assert "exited unexpectedly with status 1" in str(failures[0])


def test_an_absent_target_that_writes_a_partial_sample_and_exits_is_a_capture_error(
    tmp_path, monkeypatch
):
    # Raft (PipeWire 1.0.5): an absent named target wrote 75 bytes, then exit 1.
    _install(tmp_path, monkeypatch)
    monkeypatch.setenv("PW_TARGET_NOT_FOUND", "1")
    capture = LinuxMicCapture()
    items: list[np.ndarray | MicCaptureError] = []

    capture.start("steno_build_absent", items.append)
    try:
        capture._thread.join(timeout=5)
        assert not capture._thread.is_alive()
        assert capture._process.poll() == 1
    finally:
        capture.stop()

    assert [str(item) for item in items] == ["pw-record ended in the middle of a float32 sample"]


def test_a_format_error_ends_the_child_before_it_is_reported(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch)
    monkeypatch.setenv("PW_AU_ENCODING", "3")
    capture = LinuxMicCapture()
    reported = []
    alive_at_report = []

    def receive(item):
        if isinstance(item, MicCaptureError):
            alive_at_report.append(capture._process.poll() is None)
            reported.append(item)

    capture.start("steno_build_mic", receive)
    try:
        capture._thread.join(timeout=5)
        assert not capture._thread.is_alive()
        assert [str(error) for error in reported] == [
            "pw-record wrote AU encoding 3 at 16000 Hz with 1 channels"
        ]
        # The capture is reported failed, so it no longer records.
        assert alive_at_report == [False]
        assert capture._process.poll() is not None
    finally:
        capture.stop()


def test_start_without_pw_record_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(MicCaptureError, match="pw-record is not installed"):
        LinuxMicCapture().start(None, lambda item: None)


def test_parse_pactl_sources_leaves_out_monitors():
    assert parse_pactl_sources(json.dumps(_PACTL_SOURCES)) == (
        InputSource("alsa_input.usb-HyperX-00.iec958-stereo", "HyperX QuadCast 2 S"),
        InputSource("steno_build_mic", "steno_build_mic"),
        InputSource("nameless_description", "nameless_description"),
    )


def test_parse_pactl_sources_rejects_output_that_is_not_a_list():
    with pytest.raises(ValueError):
        parse_pactl_sources("{}")


def test_input_sources_lists_the_sources_and_the_default(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch)

    query = input_sources()

    assert query.error is None
    assert query.default == "steno_build_mic"
    assert [source.name for source in query.sources] == [
        "alsa_input.usb-HyperX-00.iec958-stereo",
        "steno_build_mic",
        "nameless_description",
    ]


@pytest.mark.parametrize("missing", ["pw-record", "pactl"])
def test_input_sources_names_a_missing_tool(tmp_path, monkeypatch, missing):
    _install(tmp_path, monkeypatch)
    (tmp_path / "bin" / missing).unlink()

    assert input_sources().error == f"{missing} is not installed"
