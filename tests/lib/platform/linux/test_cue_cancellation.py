# SPDX-License-Identifier: GPL-3.0-or-later
"""Cancellation terminates and reaps an actual child, without playing physical audio."""

import sys
import threading
import time

import psutil
import pytest

from stenographer.lib.platform.linux.cues import _cancellable_preview


def test_cancelled_preview_terminates_real_player_process(tmp_path):
    marker = tmp_path / "child.pid"
    cancellation = threading.Event()
    failed = threading.Event()

    def run():
        try:
            _cancellable_preview(
                [
                    sys.executable,
                    "-c",
                    "import os, sys, time; from pathlib import Path; "
                    "Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)",
                    str(marker),
                ],
                cancellation,
            )
        except RuntimeError as exc:
            assert str(exc) == "Sound preview cancelled"
            failed.set()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        pid = int(marker.read_text())
        assert psutil.pid_exists(pid)
        cancellation.set()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert failed.is_set()
        assert not psutil.pid_exists(pid)
    finally:
        cancellation.set()
        worker.join(timeout=2)


def test_already_cancelled_preview_does_not_launch_child(tmp_path):
    cancellation = threading.Event()
    cancellation.set()
    marker = tmp_path / "must-not-exist"
    with pytest.raises(RuntimeError, match="cancelled"):
        _cancellable_preview(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
                str(marker),
            ],
            cancellation,
        )
    assert not marker.exists()
