# SPDX-License-Identifier: GPL-3.0-or-later
"""Audibility, preview volume, and ordered cue playback policy."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import threading

    from stenographer.lib.config.models import FeedbackConfig
    from stenographer.lib.platform.cue_player import CuePlayer

from stenographer.lib.sounds.constants import PREVIEW_PAUSE_SECONDS, PREVIEW_VOLUME_WHEN_MUTED
from stenographer.lib.sounds.sound_pack import SoundPack


def cue_audible(mute: bool, volume: float, *, has_player: bool) -> bool:
    """Whether a cue may make sound at all: unmuted, positive volume, a player. PURE."""
    return not mute and volume > 0.0 and has_player


def preview_volume(cfg: FeedbackConfig) -> float:
    """Return audible preview volume without mutating mute or volume settings."""
    if cfg.mute or cfg.volume <= 0.0:
        return PREVIEW_VOLUME_WHEN_MUTED
    return cfg.volume


def preview_sound_pack(
    pack: SoundPack,
    player: CuePlayer,
    volume: float,
    *,
    pause_seconds: float = PREVIEW_PAUSE_SECONDS,
    cancellation: threading.Event | None = None,
) -> None:
    """Play all lifecycle cues in order with silence between them."""
    if not pack.complete:
        raise ValueError(f"sound pack {pack.name!r} is incomplete")
    for index, path in enumerate(pack.cue_paths):
        assert path is not None  # narrowed by ``complete`` above
        if cancellation is None:
            player.preview(path, volume)
        else:
            if cancellation.is_set():
                raise RuntimeError("Sound preview cancelled")
            player.preview(path, volume, cancellation=cancellation)
        if index + 1 < len(pack.cue_paths):
            if cancellation is None:
                time.sleep(pause_seconds)
            elif cancellation.wait(pause_seconds):
                raise RuntimeError("Sound preview cancelled")
