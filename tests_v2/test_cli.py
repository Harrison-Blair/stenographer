# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the reauthored CLI parser (M0 scaffold)."""

from __future__ import annotations

import subprocess
import sys

import pytest
import stenographer_v2
import stenographer_v2.cli as cli
from stenographer_v2.cli import build_parser, main


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == stenographer_v2.__version__


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_transcribe_parses_file_and_raw():
    parser = build_parser()

    args = parser.parse_args(["transcribe", "clip.wav"])
    assert args.command == "transcribe"
    assert args.file == "clip.wav"
    assert args.raw is False

    args = parser.parse_args(["transcribe", "clip.wav", "--raw"])
    assert args.raw is True


def test_model_download_subcommand():
    args = build_parser().parse_args(["model", "download"])
    assert args.command == "model"
    assert args.model_command == "download"


@pytest.mark.parametrize("command", ["run", "doctor", "devices"])
def test_plain_subcommands_parse(command):
    args = build_parser().parse_args([command])
    assert args.command == command


@pytest.mark.parametrize("command", ["run", "doctor", "devices"])
def test_plain_subcommands_are_stubs(command, capsys):
    # run/doctor/devices are still M0 stubs in M1.
    assert main([command]) == 1
    assert "not implemented" in capsys.readouterr().err


def test_transcribe_dispatches_to_handler(monkeypatch):
    # transcribe is no longer a stub: main routes it to the real handler,
    # passing the parsed args through. (No config/ASR import is exercised
    # because the handler itself is replaced.)
    seen = {}

    def fake(args):
        seen["file"] = args.file
        seen["raw"] = args.raw
        return 0

    monkeypatch.setattr(cli, "_cmd_transcribe", fake)
    assert main(["transcribe", "clip.wav", "--raw"]) == 0
    assert seen == {"file": "clip.wav", "raw": True}


def test_model_download_dispatches_to_handler(monkeypatch):
    hits = []

    def fake(args):
        hits.append(args.model_command)
        return 0

    monkeypatch.setattr(cli, "_cmd_model_download", fake)
    assert main(["model", "download"]) == 0
    assert hits == ["download"]


def test_unknown_subcommand_errors():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["bogus"])
    assert exc.value.code == 2


def test_cli_module_has_no_heavy_imports():
    # Importing the CLI (and building its parser) must not pull in the ASR,
    # audio, or evdev stacks — those belong inside subcommand handlers. Checked
    # in a fresh interpreter so the assertion reflects this module's own import
    # graph, not a sys.modules table already polluted by the rest of the suite.
    code = (
        "import sys\n"
        "import stenographer_v2.cli as cli\n"
        "cli.build_parser()\n"
        "heavy = [n for n in ('faster_whisper', 'sounddevice', 'evdev') if n in sys.modules]\n"
        "print(','.join(heavy))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""
