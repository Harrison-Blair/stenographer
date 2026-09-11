# SPDX-License-Identifier: GPL-3.0-or-later
"""Configured lifecycle feedback and one-time pack resolution."""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stenographer.lib.config.models import FeedbackConfig
    from stenographer.lib.platform.cue_player import CuePlayer

from stenographer.lib.sounds.packs import resolve_sound_pack
from stenographer.lib.sounds.playback import cue_audible
from stenographer.lib.sounds.sound_pack import SoundPack


class Feedback:
    """Own mute, volume, and one-time sound-pack resolution policy."""

    def __init__(
        self,
        *,
        cfg: FeedbackConfig,
        player: CuePlayer | None,
        config_dir: pathlib.Path,
        asset_root: pathlib.Path | None = None,
    ) -> None:
        self._cfg = cfg
        self._player = player
        self._pack = resolve_sound_pack(
            cfg.sound_pack,
            config_dir,
            bundled_root=asset_root,
        )

    @property
    def sound_pack(self) -> SoundPack:
        """The effective pack fixed for this ``Feedback`` lifetime."""
        return self._pack

    def play(self, name: str) -> None:
        if not cue_audible(self._cfg.mute, self._cfg.volume, has_player=self._player is not None):
            return
        path = self._pack.path_for(name)
        if path is None:
            return
        self._player.play(path, self._cfg.volume)

    def close(self) -> None:
        return None
