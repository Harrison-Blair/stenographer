# SPDX-License-Identifier: GPL-3.0-or-later
"""The Linux cue player: its pure argv builder, and its real child processes.

No audio is ever played. Player detection runs against a tmp PATH, and every
process this file starts is a shell or Python stub it wrote itself, so the
timeout and failure paths are exercised with real children.
"""

from __future__ import annotations

import os
import pathlib
import shlex
import subprocess
from functools import partial

import psutil
import pytest

from stenographer.lib.platform.linux import cues
from stenographer.lib.platform.linux.cues import (
    LinuxCuePlayer,
    build_play_command,
    detect_player,
)
from tests.support import wait_until as _wait_until

wait_until = partial(_wait_until, timeout=10.0, interval=0.01)


def _script(path, body):
    """A real executable on disk: the only "player" these tests ever run."""
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def _recorder(path, record):
    return _script(path, f'printf "%s\\n" "$@" >> {shlex.quote(str(record))}\n')


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
    _script(tmp_path / "pw-play", f"echo $$ > {shlex.quote(str(marker))}\nexec sleep 60\n")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(cues, "PREVIEW_TIMEOUT_SECONDS", 0.3)

    with pytest.raises(subprocess.TimeoutExpired) as raised:
        LinuxCuePlayer("pw-play").preview(pathlib.Path("/tmp/cue.wav"), 0.5)
    assert raised.value.cmd == ["pw-play", "--volume=0.50", "/tmp/cue.wav"]
    assert raised.value.timeout == pytest.approx(0.3, abs=0.05)
    pid = int(marker.read_text())
    assert wait_until(lambda: not psutil.pid_exists(pid))


def test_cue_player_spawns_the_detected_player_detached(tmp_path, monkeypatch):
    record = tmp_path / "argv"
    _recorder(tmp_path / "paplay", record)
    monkeypatch.setenv("PATH", str(tmp_path))

    LinuxCuePlayer("paplay").play(pathlib.Path("/tmp/cue.wav"), 0.6)
    assert wait_until(record.exists)
    assert wait_until(lambda: record.read_text().splitlines() == ["--volume=39321", "/tmp/cue.wav"])


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
