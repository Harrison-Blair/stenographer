# SPDX-License-Identifier: GPL-3.0-or-later
"""The Linux cue player: its pure argv builder, and its real child processes.

No audio is ever played. Player detection runs against a tmp PATH, and every
process this file starts is a shell or Python stub it wrote itself, so the
timeout, failure, and cancellation paths are exercised with real children.
"""

from __future__ import annotations

import pathlib
import shlex
import subprocess
import threading
import time

import psutil
import pytest

from stenographer.lib.platform.linux import cues
from stenographer.lib.platform.linux.cues import (
    _cancellable_preview,
    build_play_command,
    detect_player,
)
from stenographer.lib.platform.linux.linux_cue_player import LinuxCuePlayer


def _script(path, body):
    """A real executable on disk: the only "player" these tests ever run."""
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def _recorder(path, record):
    return _script(path, f'printf "%s\\n" "$@" >> {shlex.quote(str(record))}\n')


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_canberra_volume_converts_linear_gain_to_decibels():
    cmd = build_play_command("canberra-gtk-play", pathlib.Path("/tmp/x.wav"), 0.6)
    assert cmd == [
        "canberra-gtk-play",
        "--file=/tmp/x.wav",
        "--description=Stenographer cue",
        "--cache-control=volatile",
        "--volume=-4.44",
    ]


def test_pw_play_volume_two_decimals():
    cmd = build_play_command("pw-play", pathlib.Path("/tmp/x.wav"), 0.6)
    assert cmd == ["pw-play", "--volume=0.60", "/tmp/x.wav"]


def test_paplay_volume_linear_scaling():
    assert build_play_command("paplay", pathlib.Path("/tmp/x.wav"), 0.6)[1] == "--volume=39321"
    assert build_play_command("paplay", pathlib.Path("/tmp/x.wav"), 1.0)[1] == "--volume=65536"
    assert build_play_command("paplay", pathlib.Path("/tmp/x.wav"), 0.0)[1] == "--volume=0"


def test_detect_player_finds_nothing_when_no_player_is_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert detect_player() is None


def test_detect_player_prefers_canberra_over_the_pipewire_players(tmp_path, monkeypatch):
    # libcanberra is purpose-built for short event sounds, so it wins whenever
    # it is installed; paplay is only the last resort.
    monkeypatch.setenv("PATH", str(tmp_path))
    _script(tmp_path / "paplay", "exit 0\n")
    assert detect_player() == "paplay"
    _script(tmp_path / "pw-play", "exit 0\n")
    assert detect_player() == "pw-play"
    _script(tmp_path / "canberra-gtk-play", "exit 0\n")
    assert detect_player() == "canberra-gtk-play"


def test_preview_gives_up_on_a_stalled_player_and_reaps_it(tmp_path, monkeypatch):
    """A player that never exits must raise TimeoutExpired and leave no child.

    The timeout is shrunk so a real sleeping child outlives it in well under a
    second; the child records its own pid, so its death is observed, not assumed.
    """
    marker = tmp_path / "child.pid"
    stalled = _script(
        tmp_path / "stalled", f"echo $$ > {shlex.quote(str(marker))}\nexec sleep 60\n"
    )
    monkeypatch.setattr(cues, "PREVIEW_TIMEOUT_SECONDS", 0.3)

    command = [str(stalled)]
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        _cancellable_preview(command, threading.Event())
    assert raised.value.cmd == command
    assert raised.value.timeout == 0.3
    pid = int(marker.read_text())
    assert _wait_for(lambda: not psutil.pid_exists(pid))


def test_preview_reports_a_player_that_exits_nonzero(tmp_path):
    failing = _script(tmp_path / "failing", "exit 3\n")
    with pytest.raises(subprocess.CalledProcessError) as raised:
        _cancellable_preview([str(failing)], threading.Event())
    assert raised.value.returncode == 3


def test_cancellation_kills_a_player_that_ignores_sigterm(tmp_path):
    """terminate() is the polite first move; a player that ignores it is killed.

    Seen to hang against a terminate-only teardown: the child ignores SIGTERM,
    so only the kill() fallback ends the preview.
    """
    marker = tmp_path / "child.pid"
    stubborn = _script(
        tmp_path / "stubborn",
        f"trap '' TERM\necho $$ > {shlex.quote(str(marker))}\nwhile :; do sleep 0.1; done\n",
    )
    command = [str(stubborn)]
    cancellation = threading.Event()
    outcome: list[BaseException] = []

    def run():
        try:
            _cancellable_preview(command, cancellation)
        except BaseException as exc:
            outcome.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert _wait_for(marker.exists)
        pid = int(marker.read_text())
        cancellation.set()
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert [type(exc) for exc in outcome] == [RuntimeError]
        assert str(outcome[0]) == "Sound preview cancelled"
        assert _wait_for(lambda: not psutil.pid_exists(pid))
    finally:
        cancellation.set()
        worker.join(timeout=10)


def test_cue_player_spawns_the_detected_player_detached(tmp_path, monkeypatch):
    record = tmp_path / "argv"
    _recorder(tmp_path / "paplay", record)
    monkeypatch.setenv("PATH", str(tmp_path))

    LinuxCuePlayer("paplay").play(pathlib.Path("/tmp/cue.wav"), 0.6)
    assert _wait_for(record.exists)
    assert _wait_for(lambda: record.read_text().splitlines() == ["--volume=39321", "/tmp/cue.wav"])


def test_cue_player_preview_waits_for_the_player_and_surfaces_its_failure(tmp_path, monkeypatch):
    record = tmp_path / "argv"
    player = _recorder(tmp_path / "pw-play", record)
    monkeypatch.setenv("PATH", str(tmp_path))

    # A synchronous preview: the argv is already recorded when it returns.
    LinuxCuePlayer("pw-play").preview(pathlib.Path("/tmp/cue.wav"), 0.5)
    assert record.read_text().splitlines() == ["--volume=0.50", "/tmp/cue.wav"]

    _script(player, "exit 7\n")
    with pytest.raises(subprocess.CalledProcessError) as raised:
        LinuxCuePlayer("pw-play").preview(pathlib.Path("/tmp/cue.wav"), 0.5)
    assert raised.value.returncode == 7


def test_cue_player_preview_under_an_uncancelled_lease_plays_to_completion(tmp_path, monkeypatch):
    record = tmp_path / "argv"
    _recorder(tmp_path / "pw-play", record)
    monkeypatch.setenv("PATH", str(tmp_path))

    LinuxCuePlayer("pw-play").preview(
        pathlib.Path("/tmp/cue.wav"), 0.5, cancellation=threading.Event()
    )
    assert record.read_text().splitlines() == ["--volume=0.50", "/tmp/cue.wav"]


def test_cue_player_preview_honours_a_lease_cancelled_before_playback(tmp_path, monkeypatch):
    record = tmp_path / "argv"
    _recorder(tmp_path / "pw-play", record)
    monkeypatch.setenv("PATH", str(tmp_path))
    cancellation = threading.Event()
    cancellation.set()

    with pytest.raises(RuntimeError, match="cancelled"):
        LinuxCuePlayer("pw-play").preview(
            pathlib.Path("/tmp/cue.wav"), 0.5, cancellation=cancellation
        )
    time.sleep(0.2)
    assert not record.exists()
