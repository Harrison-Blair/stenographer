# SPDX-License-Identifier: GPL-3.0-or-later
"""Microphone listing: the rendered command output."""

from __future__ import annotations

import argparse

from stenographer.lib.platform.mic_capture import InputSource, InputSources


def test_listing_prints_name_and_description_and_marks_the_default(monkeypatch, capsys):
    from stenographer.cli.devices import handler

    query = InputSources(
        sources=(
            InputSource("alsa_input.usb-mic", "USB mic"),
            InputSource("alsa_input.studio", "Studio interface"),
        ),
        default="alsa_input.studio",
    )
    monkeypatch.setattr(handler, "query_devices", lambda: query)

    assert handler.cmd_devices(argparse.Namespace()) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        "  alsa_input.usb-mic  USB mic\n* alsa_input.studio  Studio interface\n"
    )
    assert captured.err == ""


def test_listing_says_so_when_no_microphone_exists(monkeypatch, capsys):
    from stenographer.cli.devices import handler

    monkeypatch.setattr(handler, "query_devices", lambda: InputSources(default="x.monitor"))

    assert handler.cmd_devices(argparse.Namespace()) == 0
    assert capsys.readouterr().out == "  (no microphones found)\n"


def test_a_failed_listing_is_reported_on_stderr_and_fails(monkeypatch, capsys):
    from stenographer.cli.devices import handler

    monkeypatch.setattr(
        handler, "query_devices", lambda: InputSources(error="pactl is not installed")
    )

    assert handler.cmd_devices(argparse.Namespace()) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "stenographer: pactl is not installed\n"
