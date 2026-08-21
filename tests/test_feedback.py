# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic unit tests for the cue player (spec §6.1): command builder,
cue-path resolution, and shipped-asset presence. No subprocess, no playback."""

from __future__ import annotations

import pathlib

from stenographer.feedback import CUES, build_play_command, resolve_cue_path

_BUNDLED = pathlib.Path(__file__).parent.parent / "src" / "stenographer" / "assets" / "sounds"


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


def test_resolve_cue_path_present_and_absent(tmp_path):
    (tmp_path / "record_start.wav").write_bytes(b"RIFF")
    assert resolve_cue_path(tmp_path, "record_start") == tmp_path / "record_start.wav"
    assert resolve_cue_path(tmp_path, "nope") is None


def test_four_cues_defined():
    assert {"record_start", "record_stop", "delivered", "error"} == CUES


def test_all_cues_resolve_against_bundled_assets():
    assert {path.stem for path in _BUNDLED.glob("*.wav")} == CUES
    for name in CUES:
        assert resolve_cue_path(_BUNDLED, name) is not None, name
