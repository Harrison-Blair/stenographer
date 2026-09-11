# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview one sound pack without saving settings."""

from stenographer.cli.shared.console import Console
from stenographer.lib.config.models import Config


def _preview(console: Console, config: Config, pack: object) -> bool:
    from stenographer.lib.platform import current_platform
    from stenographer.lib.sounds import playback

    try:
        player = current_platform().cue_player()
    except Exception as exc:
        console.error(f"could not initialize cue playback: {exc}")
        return False
    if player is None:
        console.error("no supported cue player is available")
        return False
    try:
        playback.preview_sound_pack(pack, player, playback.preview_volume(config.feedback))
    except Exception as exc:
        console.error(f"sound-pack preview failed: {exc}")
        return False
    return True
