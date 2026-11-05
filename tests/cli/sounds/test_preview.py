# SPDX-License-Identifier: GPL-3.0-or-later
"""Sound-pack preview: a failure is always reported, never raised at the caller.

Nothing here plays audio: the cue player and the playback call are the two
seams the preview goes through, and both are supplied by the test.
"""

from __future__ import annotations

import dataclasses

import pytest

from stenographer.cli.sounds.workflow import _preview
from stenographer.lib.config.models import Config
from tests.cli.support import console as _console


def _platform(player):
    class Plat:
        def cue_player(self):
            if isinstance(player, Exception):
                raise player
            return player

    return Plat


def test_a_cue_player_that_cannot_be_built_is_reported(monkeypatch):
    from stenographer.lib import platform as platform_module

    monkeypatch.setattr(
        platform_module,
        "current_platform",
        _platform(RuntimeError("PulseAudio is not running")),
    )
    console = _console()

    assert _preview(console, Config.defaults(), object()) is False
    assert console.stderr.getvalue() == (
        "stenographer: could not initialize cue playback: PulseAudio is not running\n"
    )


def test_a_host_with_no_cue_player_is_reported(monkeypatch):
    from stenographer.lib import platform as platform_module

    monkeypatch.setattr(platform_module, "current_platform", _platform(None))
    console = _console()

    assert _preview(console, Config.defaults(), object()) is False
    assert console.stderr.getvalue() == "stenographer: no supported cue player is available\n"


def test_a_failed_playback_is_reported(monkeypatch):
    from stenographer.lib import platform as platform_module
    from stenographer.lib.sounds import playback

    player = object()
    monkeypatch.setattr(platform_module, "current_platform", _platform(player))

    def fail(pack, cue_player, volume):
        raise ValueError("sound pack 'half-done' is incomplete")

    monkeypatch.setattr(playback, "preview_sound_pack", fail)
    console = _console()

    assert _preview(console, Config.defaults(), object()) is False
    assert console.stderr.getvalue() == (
        "stenographer: sound-pack preview failed: sound pack 'half-done' is incomplete\n"
    )


@pytest.mark.parametrize(("mute", "volume", "expected"), [(False, 0.4, 0.4), (True, 0.4, 0.6)])
def test_a_successful_preview_passes_the_pack_player_and_audible_volume(
    monkeypatch,
    mute,
    volume,
    expected,
):
    from stenographer.lib import platform as platform_module
    from stenographer.lib.sounds import playback

    player = object()
    pack = object()
    calls: list[tuple] = []
    monkeypatch.setattr(platform_module, "current_platform", _platform(player))
    monkeypatch.setattr(
        playback,
        "preview_sound_pack",
        lambda one, two, three: calls.append((one, two, three)),
    )
    defaults = Config.defaults()
    config = dataclasses.replace(
        defaults,
        feedback=dataclasses.replace(defaults.feedback, mute=mute, volume=volume),
    )
    console = _console()

    assert _preview(console, config, pack) is True
    assert calls == [(pack, player, expected)]
    assert console.stderr.getvalue() == ""


@pytest.mark.parametrize(("mute", "volume"), [(True, 0.4), (True, 0.6), (False, 0.0)])
def test_a_preview_that_overrides_silence_says_so_and_changes_no_setting(
    monkeypatch,
    mute,
    volume,
):
    from stenographer.lib import platform as platform_module
    from stenographer.lib.sounds import playback

    monkeypatch.setattr(platform_module, "current_platform", _platform(object()))
    monkeypatch.setattr(playback, "preview_sound_pack", lambda one, two, three: None)
    defaults = Config.defaults()
    feedback = dataclasses.replace(defaults.feedback, mute=mute, volume=volume)
    config = dataclasses.replace(defaults, feedback=feedback)
    console = _console()

    assert _preview(console, config, object()) is True
    assert console.stdout.getvalue() == (
        "Cues are muted or at volume zero: this preview plays at volume 0.6 "
        "and changes neither setting.\n"
    )


def test_a_preview_at_the_configured_volume_prints_no_note(monkeypatch):
    from stenographer.lib import platform as platform_module
    from stenographer.lib.sounds import playback

    monkeypatch.setattr(platform_module, "current_platform", _platform(object()))
    monkeypatch.setattr(playback, "preview_sound_pack", lambda one, two, three: None)
    defaults = Config.defaults()
    config = dataclasses.replace(
        defaults,
        feedback=dataclasses.replace(defaults.feedback, mute=False, volume=0.4),
    )
    console = _console()

    assert _preview(console, config, object()) is True
    assert console.stdout.getvalue() == ""
