# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the reauthored CLI parser (M0 scaffold)."""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

import stenographer
from stenographer.cli import build_parser, dispatch
from stenographer.cli.commands.devices import _format_input_devices


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        dispatch(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == stenographer.__version__


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        dispatch(["--help"])
    assert exc.value.code == 0


def test_no_command_prints_help(capsys):
    assert dispatch([]) == 0
    out = capsys.readouterr().out
    assert "usage: stenographer" in out
    for command in ("run", "transcribe", "model", "doctor", "devices", "setup", "completion"):
        assert command in out


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


def test_setup_quick_flag_defaults_false_and_parses_true():
    parser = build_parser()

    assert parser.parse_args(["setup"]).quick is False
    assert parser.parse_args(["setup", "--quick"]).quick is True


@pytest.mark.parametrize("command", ["run", "doctor", "devices", "setup"])
def test_plain_subcommands_parse(command):
    args = build_parser().parse_args([command])
    assert args.command == command


@pytest.mark.parametrize("command", ["doctor", "devices"])
def test_doctor_and_devices_dispatch_to_handlers(command, monkeypatch):
    module = importlib.import_module(f"stenographer.cli.commands.{command}")
    hits = []
    monkeypatch.setattr(module, f"cmd_{command}", lambda args: hits.append(command) or 0)
    assert dispatch([command]) == 0
    assert hits == [command]


def test_setup_dispatches_to_handler(monkeypatch):
    from stenographer.cli.commands import setup as setup_command

    hits = []
    monkeypatch.setattr(setup_command, "cmd_setup", lambda args: hits.append(args.command) or 0)
    assert dispatch(["setup"]) == 0
    assert hits == ["setup"]


def test_quick_setup_dispatches_flag_to_handler(monkeypatch):
    from stenographer.cli.commands import setup as setup_command

    seen = []
    monkeypatch.setattr(setup_command, "cmd_setup", lambda args: seen.append(args.quick) or 0)
    assert dispatch(["setup", "--quick"]) == 0
    assert seen == [True]


def test_format_input_devices_marks_default_and_skips_outputs():
    devices = [
        {"name": "hdmi-out", "max_input_channels": 0},
        {"name": "usb mic", "max_input_channels": 1},
        {"name": "webcam mic", "max_input_channels": 2},
    ]
    lines = _format_input_devices(devices, default_index=1)
    assert lines == ["* 1: usb mic (1 ch)", "  2: webcam mic (2 ch)"]


def test_format_input_devices_empty():
    assert _format_input_devices([{"name": "out", "max_input_channels": 0}], -1) == [
        "  (no input devices found)"
    ]


def test_run_dispatches_config_to_daemon(monkeypatch):
    # `run` loads config and hands it to daemon.run, returning its exit code.
    # daemon.run is stubbed here to verify wiring only (not to assert a mocked
    # subprocess call): the real daemon is exercised by manual dictation.
    import stenographer.config as config
    import stenographer.daemon as daemon

    sentinel = object()
    monkeypatch.setattr(config, "load_or_default", lambda: sentinel)
    seen = {}

    def fake_run(cfg):
        seen["cfg"] = cfg
        return 3

    monkeypatch.setattr(daemon, "run", fake_run)
    assert dispatch(["run"]) == 3
    assert seen["cfg"] is sentinel


def test_transcribe_dispatches_to_handler(monkeypatch):
    # transcribe is no longer a stub: dispatch routes it to the real handler,
    # passing the parsed args through. (No config/ASR import is exercised
    # because the handler itself is replaced.)
    seen = {}

    def fake(args):
        seen["file"] = args.file
        seen["raw"] = args.raw
        return 0

    from stenographer.cli.commands import transcribe as transcribe_command

    monkeypatch.setattr(transcribe_command, "cmd_transcribe", fake)
    assert dispatch(["transcribe", "clip.wav", "--raw"]) == 0
    assert seen == {"file": "clip.wav", "raw": True}


def test_model_download_dispatches_to_handler(monkeypatch):
    hits = []

    def fake(args):
        hits.append(args.model_command)
        return 0

    from stenographer.cli.commands import model as model_command

    monkeypatch.setattr(model_command, "cmd_model_download", fake)
    assert dispatch(["model", "download"]) == 0
    assert hits == ["download"]


def test_unknown_subcommand_errors():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["bogus"])
    assert exc.value.code == 2


def test_private_overlay_entry_is_absent_from_public_help(capsys):
    with pytest.raises(SystemExit) as exc:
        dispatch(["--help"])
    assert exc.value.code == 0
    assert "_overlay" not in capsys.readouterr().out


def test_cli_module_has_no_heavy_imports():
    # Importing the CLI (and building its parser) must not pull in the ASR,
    # audio, or evdev stacks — those belong inside subcommand handlers. Checked
    # in a fresh interpreter so the assertion reflects this module's own import
    # graph, not a sys.modules table already polluted by the rest of the suite.
    code = (
        "import sys\n"
        "import stenographer.cli as cli\n"
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
