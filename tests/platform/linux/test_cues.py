# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure command-builder tests for the Linux cue player. No subprocess, no playback."""

from __future__ import annotations

import pathlib

from stenographer.platform.linux.cues import build_play_command


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
