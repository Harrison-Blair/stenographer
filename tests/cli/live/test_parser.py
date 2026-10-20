# SPDX-License-Identifier: GPL-3.0-or-later
"""Argument tests for ``stenographer live``."""

from __future__ import annotations

import argparse

import pytest

from stenographer.cli.live.parser import register


def _parser():
    parser = argparse.ArgumentParser(prog="stenographer")
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers)
    return parser


def test_live_parser_defaults_both_sources_on_and_accepts_overrides():
    parser = _parser()

    defaults = parser.parse_args(["live"])
    options = parser.parse_args(["live", "--no-mic", "--system", "--device", "USB Microphone"])

    assert defaults.mic is True
    assert defaults.system is True
    assert options.mic is False
    assert options.system is True
    assert options.device == "USB Microphone"


def test_live_parser_rejects_both_sources_off(capsys):
    parser = _parser()

    with pytest.raises(SystemExit) as result:
        parser.parse_args(["live", "--no-mic", "--no-system"])

    assert result.value.code == 2
    error = capsys.readouterr().err
    assert "--no-system" in error and "--no-mic" in error


def test_live_help_lists_source_and_device_flags(capsys):
    parser = _parser()

    with pytest.raises(SystemExit) as result:
        parser.parse_args(["live", "--help"])

    assert result.value.code == 0
    help_text = capsys.readouterr().out
    assert "--mic" in help_text
    assert "--no-mic" in help_text
    assert "--system" in help_text
    assert "--no-system" in help_text
    assert "--device" in help_text
