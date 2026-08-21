# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke suite for the cue player (spec §6.3, M4 Verify).

Really plays each of the four bundled cues through the detected audio player
(canberra-gtk-play/pw-play/paplay) — no mocks. The operator should hear four
distinct cues, in order: record_start, record_stop, delivered, error. A short
sleep separates them so each is audible; play() must
never raise.

Self-skips unless STENOGRAPHER_INTEGRATION=1 and an audio player is on PATH, so
the default unit run never spawns a player or makes sound.
"""

from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.integration

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)

from stenographer.config import FeedbackConfig  # noqa: E402
from stenographer.feedback import CUES, Feedback, detect_player  # noqa: E402

if detect_player() is None:
    pytest.skip(
        "no audio player (canberra-gtk-play/pw-play/paplay) on PATH",
        allow_module_level=True,
    )


def test_play_each_cue_audibly():
    fb = Feedback(cfg=FeedbackConfig(volume=0.6, mute=False))
    try:
        for name in ("record_start", "record_stop", "delivered", "error"):
            assert name in CUES
            fb.play(name)  # must not raise
            time.sleep(1.0)
    finally:
        fb.close()
