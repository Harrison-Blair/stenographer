# SPDX-License-Identifier: GPL-3.0-or-later
"""The quick wizard: the essentials only, in the order it asks for them.

Device menus come from the two module-level enumerators the quick wizard
shares with the full wizard, so nothing here reaches PortAudio or ``/dev/input``.
"""

from __future__ import annotations

import io

import pytest

from stenographer.cli.setup import quick as quick_setup
from stenographer.cli.setup.errors import SetupCancelledError
from stenographer.cli.shared.console import Console
from stenographer.lib.config.models import Config


def _console(answers: str) -> Console:
    return Console(io.StringIO(answers), io.StringIO(), io.StringIO())


@pytest.fixture
def device_menus(monkeypatch):
    """``quick`` binds both enumerators into its own namespace, so patch them there."""

    monkeypatch.setattr(quick_setup, "_hotkey_devices", lambda: [("event3", "event3: Keyboard")])
    monkeypatch.setattr(quick_setup, "_audio_devices", lambda: [("1", "1: USB mic")])


def test_quick_wizard_asks_only_the_essentials_and_returns_them(device_menus, tmp_path):
    console = _console(
        "1\n"  # hotkey device
        "type\nKEY_F9\n"  # binding
        "toggle\n"  # mode
        "1\n"  # audio input device
        "0.8\n\n\n\nlegacy\n"  # feedback: volume, mute, overlay, updates, pack
        "keep\n"  # spectrum response
        "\n"  # refine: stay disabled
        "\n"  # review: save
    )

    config = quick_setup._quick_wizard(
        console,
        Config.defaults(),
        tmp_path,
        new_config=False,
    )

    assert config.hotkey.device == "event3"
    assert config.hotkey.binding == "KEY_F9"
    assert config.hotkey.mode == "toggle"
    assert config.audio.input_device == "1"
    assert config.feedback.volume == 0.8
    assert config.feedback.sound_pack == "legacy"
    # The quick wizard never touches the audio gate or any ASR key.
    assert config.audio.min_speech_rms == Config.defaults().audio.min_speech_rms
    assert config.asr == Config.defaults().asr

    stdout = console.stdout.getvalue()
    assert "\nHotkey" in stdout
    assert "\nMicrophone" in stdout
    assert "\nFeedback" in stdout
    assert "IMPORTANT: spectrum calibration controls only the 18 display bars." in stdout
    assert "\nQuick setup review" in stdout
    assert "Save [Enter/S] or Cancel [C]: " in stdout
    # The log threshold is not an essential.
    assert "Log level" not in stdout


def test_quick_wizard_skips_calibration_when_the_overlay_is_turned_off(device_menus, tmp_path):
    console = _console(
        "\nkeep\n\n"  # hotkey device, binding, mode
        "\n"  # audio input device
        "\n\nno\n\n\n"  # feedback, overlay disabled
        "\n"  # refine: stay disabled
        "\n"  # review: save
    )

    config = quick_setup._quick_wizard(
        console,
        Config.defaults(),
        tmp_path,
        new_config=False,
    )

    assert config.feedback.overlay is False
    stdout = console.stdout.getvalue()
    assert "Overlay is disabled, so display-spectrum calibration was skipped." in stdout
    assert "Spectrum response" not in stdout


def test_quick_wizard_cancel_raises_so_nothing_is_saved(device_menus, tmp_path):
    console = _console("\nkeep\n\n\n\n\n\n\n\nkeep\n\nc\n")

    with pytest.raises(SetupCancelledError):
        quick_setup._quick_wizard(console, Config.defaults(), tmp_path, new_config=False)


def test_a_new_configuration_offers_binding_capture_first(device_menus, tmp_path):
    console = _console("\nkeep\n\n\n\n\n\n\n\nkeep\n\n\n")

    quick_setup._quick_wizard(console, Config.defaults(), tmp_path, new_config=True)

    assert "Binding (capture/keep/type) [capture]: " in console.stdout.getvalue()
