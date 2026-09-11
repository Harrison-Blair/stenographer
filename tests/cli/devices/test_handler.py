# SPDX-License-Identifier: GPL-3.0-or-later
"""Input-device listing: pure index selection and the rendered command output."""

from __future__ import annotations

import argparse

from stenographer.cli.devices.handler import _default_input_index


def test_default_input_index_takes_the_input_half_of_the_pair():
    assert _default_input_index((3, 7)) == 3
    assert _default_input_index([-1, 4]) == -1


def test_default_input_index_normalises_unusable_pairs_to_the_sentinel():
    assert _default_input_index(None) == -1
    assert _default_input_index(()) == -1
    assert _default_input_index(("default", "default")) == -1


def test_listing_prints_only_input_devices_and_marks_the_default(monkeypatch, capsys):
    from stenographer.cli.devices import handler
    from stenographer.lib.audio.device_query import DeviceQuery

    query = DeviceQuery(
        devices=(
            {"name": "HDMI out", "max_input_channels": 0},
            {"name": "USB mic", "max_input_channels": 1},
            {"name": "Studio interface", "max_input_channels": 2},
        ),
        default_device=(2, 0),
    )
    monkeypatch.setattr(handler, "query_devices", lambda: query)

    assert handler.cmd_devices(argparse.Namespace()) == 0

    captured = capsys.readouterr()
    assert captured.out == "  1: USB mic (1 ch)\n* 2: Studio interface (2 ch)\n"
    assert captured.err == ""


def test_listing_says_so_when_no_device_can_record(monkeypatch, capsys):
    from stenographer.cli.devices import handler
    from stenographer.lib.audio.device_query import DeviceQuery

    monkeypatch.setattr(
        handler,
        "query_devices",
        lambda: DeviceQuery(
            devices=({"name": "HDMI out", "max_input_channels": 0},),
            default_device=(-1, 0),
        ),
    )

    assert handler.cmd_devices(argparse.Namespace()) == 0
    assert capsys.readouterr().out == "  (no input devices found)\n"


def test_an_unusable_audio_stack_is_reported_on_stderr_and_fails(monkeypatch, capsys):
    from stenographer.cli.devices import handler
    from stenographer.lib.audio.device_query import DeviceQuery

    monkeypatch.setattr(
        handler,
        "query_devices",
        lambda: DeviceQuery(error="audio subsystem unavailable: no default output device"),
    )

    assert handler.cmd_devices(argparse.Namespace()) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ("stenographer: audio subsystem unavailable: no default output device\n")
