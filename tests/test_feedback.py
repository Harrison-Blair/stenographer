# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`stenographer.audio.feedback`."""

from __future__ import annotations

import logging
import pathlib
import shutil
import subprocess
from unittest.mock import MagicMock

import numpy as np
import pytest
import soundfile as sf

from stenographer.audio.feedback import Feedback

BUNDLED_ASSET_ROOT = (
    pathlib.Path(__file__).parent.parent / "src" / "stenographer" / "assets" / "sounds"
)


def test_resolve_path_returns_override_when_set(tmp_path: pathlib.Path) -> None:
    override = tmp_path / "custom.wav"
    override.write_bytes(b"\x00\x00")
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    (asset_root / "ptt_on.wav").write_bytes(b"\x00\x00")
    feedback = Feedback(
        player="pw-play",
        asset_root=asset_root,
        override_root={"ptt_on": override},
        volume=0.6,
        muted=False,
    )
    assert feedback._resolve_path("ptt_on") == override


def test_resolve_path_falls_back_to_asset_root(tmp_path: pathlib.Path) -> None:
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    (asset_root / "ptt_on.wav").write_bytes(b"\x00\x00")
    feedback = Feedback(
        player="pw-play",
        asset_root=asset_root,
        override_root={},
        volume=0.6,
        muted=False,
    )
    assert feedback._resolve_path("ptt_on") == asset_root / "ptt_on.wav"


def test_resolve_path_returns_none_when_neither_exists(tmp_path: pathlib.Path) -> None:
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    feedback = Feedback(
        player="pw-play",
        asset_root=asset_root,
        override_root={},
        volume=0.6,
        muted=False,
    )
    assert feedback._resolve_path("ptt_on") is None


def test_play_with_muted_does_not_call_popen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    (asset_root / "ptt_on.wav").write_bytes(b"\x00\x00")
    popen_mock = MagicMock()
    monkeypatch.setattr("stenographer.audio.feedback.subprocess.Popen", popen_mock)
    feedback = Feedback(
        player="pw-play",
        asset_root=asset_root,
        override_root={},
        volume=0.6,
        muted=True,
    )
    feedback.play("ptt_on")
    popen_mock.assert_not_called()


def test_play_with_pw_play_calls_popen_with_expected_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    cue = asset_root / "ptt_on.wav"
    cue.write_bytes(b"\x00\x00")
    popen_mock = MagicMock()
    monkeypatch.setattr("stenographer.audio.feedback.subprocess.Popen", popen_mock)
    feedback = Feedback(
        player="pw-play",
        asset_root=asset_root,
        override_root={},
        volume=0.6,
        muted=False,
    )
    feedback.play("ptt_on")
    popen_mock.assert_called_once()
    call = popen_mock.call_args
    assert call.args[0] == ["pw-play", "--volume=0.60", str(cue)]
    assert call.kwargs["stdout"] == subprocess.DEVNULL
    assert call.kwargs["stderr"] == subprocess.DEVNULL
    assert call.kwargs["start_new_session"] is True


def test_play_with_paplay_passes_volume_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    sr = 44100
    original = np.full(int(sr * 0.05), 0.3, dtype=np.float32)
    source_path = tmp_path / "ptt_on.wav"
    sf.write(str(source_path), original, sr)
    asset_root = tmp_path / "empty_assets"
    asset_root.mkdir()
    popen_mock = MagicMock()
    monkeypatch.setattr("stenographer.audio.feedback.subprocess.Popen", popen_mock)
    feedback = Feedback(
        player="paplay",
        asset_root=asset_root,
        override_root={"ptt_on": source_path},
        volume=0.5,
        muted=False,
    )
    feedback.play("ptt_on")
    popen_mock.assert_called_once()
    cmd = popen_mock.call_args.args[0]
    # paplay volume is linear 0..65536; the original file plays directly.
    assert cmd == ["paplay", "--volume=32768", str(source_path)]


def test_play_logs_warning_and_skips_popen_when_no_asset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    asset_root = tmp_path / "empty_assets"
    asset_root.mkdir()
    popen_mock = MagicMock()
    monkeypatch.setattr("stenographer.audio.feedback.subprocess.Popen", popen_mock)
    feedback = Feedback(
        player="pw-play",
        asset_root=asset_root,
        override_root={},
        volume=0.6,
        muted=False,
    )
    with caplog.at_level(logging.WARNING, logger="stenographer.audio.feedback"):
        feedback.play("ptt_on")
    popen_mock.assert_not_called()
    assert any(r.levelno == logging.WARNING for r in caplog.records)


@pytest.mark.integration
def test_real_pw_play_invocation() -> None:
    if shutil.which("pw-play") is None:
        pytest.skip("pw-play not on PATH")
    cue = BUNDLED_ASSET_ROOT / "ptt_on.wav"
    if not cue.is_file():
        pytest.skip(f"bundled cue missing: {cue}")
    proc = subprocess.Popen(
        ["pw-play", "--volume=0.30", str(cue)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    rc = proc.wait(timeout=5.0)
    assert rc == 0


def test_bundled_model_loading_asset_exists() -> None:
    assert (BUNDLED_ASSET_ROOT / "model_loading.wav").is_file()


def test_bundled_model_ready_asset_exists() -> None:
    assert (BUNDLED_ASSET_ROOT / "model_ready.wav").is_file()
