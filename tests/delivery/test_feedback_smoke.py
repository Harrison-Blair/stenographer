# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke suite for cue playback and sound packs (spec §6.3).

Really plays the four lifecycle cues through ``Feedback.play`` and then all
four cues from every bundled pack plus a discovered custom pack through the
detected audio player (canberra-gtk-play/pw-play/paplay) — no mocks. Each pack
plays record_start, record_stop, delivered, error in order.

Self-skips unless STENOGRAPHER_INTEGRATION=1 and an audio player is on PATH, so
the default unit run never spawns a player or makes sound.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time

import pytest

pytestmark = pytest.mark.integration

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)

from stenographer.config import FeedbackConfig  # noqa: E402
from stenographer.delivery.feedback import (  # noqa: E402
    BUNDLED_PACKS,
    CUE_ORDER,
    Feedback,
    bundled_sound_root,
    load_sound_pack,
    preview_sound_pack,
)
from stenographer.platform.linux.cues import LinuxCuePlayer, detect_player  # noqa: E402

PLAYER = detect_player()
if PLAYER is None:
    pytest.skip(
        "no audio player (canberra-gtk-play/pw-play/paplay) on PATH",
        allow_module_level=True,
    )


def test_play_each_cue_audibly(tmp_path: pathlib.Path):
    fb = Feedback(
        cfg=FeedbackConfig(volume=0.6, mute=False),
        player=LinuxCuePlayer(PLAYER),
        config_dir=tmp_path,
    )
    for name in CUE_ORDER:
        fb.play(name)  # must not raise
        time.sleep(1.0)
    fb.close()


def test_play_every_bundled_and_custom_pack_audibly(tmp_path: pathlib.Path):
    assets = bundled_sound_root()
    custom_root = tmp_path / "sounds" / "filesystem-custom"
    shutil.copytree(assets / "minimal-ui", custom_root)
    names = (*BUNDLED_PACKS, "filesystem-custom")
    player = LinuxCuePlayer(PLAYER)

    for name in names:
        pack = load_sound_pack(name, tmp_path, bundled_root=assets)
        assert pack is not None
        preview_sound_pack(pack, player, 0.6, pause_seconds=0.5)  # must not raise
