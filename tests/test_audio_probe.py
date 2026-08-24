# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the shared input-device enumeration and its adapters."""

from __future__ import annotations

from stenographer.audio_probe import has_input_device, input_device_choices
from stenographer.cli.commands.devices import _default_input_index

_DEVICES = [
    {"name": "hdmi-out", "max_input_channels": 0},
    {"name": "usb mic", "max_input_channels": 1},
    {"name": "webcam mic", "max_input_channels": 2},
]


def test_has_input_device_ignores_output_only_devices():
    assert has_input_device(_DEVICES) is True
    assert has_input_device([{"name": "hdmi-out", "max_input_channels": 0}]) is False
    assert has_input_device([]) is False
    assert has_input_device([{"name": "nameless"}]) is False


def test_input_device_choices_keep_portaudio_indices():
    assert input_device_choices(_DEVICES) == [
        ("1", "1: usb mic"),
        ("2", "2: webcam mic"),
    ]


def test_input_device_choices_empty_without_inputs():
    assert input_device_choices([{"name": "hdmi-out", "max_input_channels": 0}]) == []


def test_input_device_choices_fall_back_to_a_placeholder_name():
    assert input_device_choices([{"max_input_channels": 1}]) == [("0", "0: ?")]


def test_default_input_index_takes_the_input_half_of_the_pair():
    assert _default_input_index((3, 7)) == 3
    assert _default_input_index([-1, 4]) == -1


def test_default_input_index_normalises_unusable_pairs_to_the_sentinel():
    assert _default_input_index(None) == -1
    assert _default_input_index(()) == -1
    assert _default_input_index(("default", "default")) == -1
