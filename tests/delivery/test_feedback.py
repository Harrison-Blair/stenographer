# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic unit tests for cue policy (spec §6.1): cue-path resolution and
shipped-asset presence. No subprocess, no playback."""

from __future__ import annotations

import pathlib

from stenographer.delivery.feedback import CUES, resolve_cue_path

_BUNDLED = (
    pathlib.Path(__file__).parent.parent.parent / "src" / "stenographer" / "assets" / "sounds"
)


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
