# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the microphone listing adapters and the device setting."""

from __future__ import annotations

import pytest

from stenographer.lib.audio.device_setting import capture_target, is_device_index
from stenographer.lib.audio.probe import input_device_choices, mic_issue
from stenographer.lib.platform.mic_capture import InputSource, InputSources

_QUERY = InputSources(
    sources=(InputSource("alsa_input.usb", "USB mic"), InputSource("remap", "Desk mic")),
    default="remap",
)


def test_input_device_choices_save_the_source_name_and_show_its_description():
    assert input_device_choices(_QUERY) == [("alsa_input.usb", "USB mic"), ("remap", "Desk mic")]
    assert input_device_choices(InputSources(error="pactl is not installed")) == []


def test_mic_issue_names_the_listing_error_or_a_missing_microphone():
    assert mic_issue(_QUERY) is None
    assert mic_issue(InputSources(error="pw-record is not installed")) == (
        "pw-record is not installed"
    )
    assert mic_issue(InputSources()) == "no microphone found"


@pytest.mark.parametrize("setting", [None, "", "pipewire", "default", "pulse", "0", "10"])
def test_these_settings_mean_the_default_microphone(setting):
    assert capture_target(setting) is None


@pytest.mark.parametrize(
    "setting", ["alsa_input.usb-HP_HyperX-00.iec958-stereo", "steno_build_mic", "Pulse", "1a"]
)
def test_any_other_setting_is_a_pipewire_source_name(setting):
    assert capture_target(setting) == setting


def test_only_a_decimal_number_is_an_old_device_index():
    assert is_device_index("10") is True
    assert is_device_index("0") is True
    for setting in (None, "", "pipewire", "hw:5,0", "1a"):
        assert is_device_index(setting) is False
