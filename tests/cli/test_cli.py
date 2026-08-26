# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the CLI parser."""

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
    for command in (
        "run",
        "transcribe",
        "model",
        "doctor",
        "devices",
        "setup",
        "sounds",
        "completion",
    ):
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


def test_setup_default_flag_parses_and_excludes_quick():
    """Seen to FAIL against the parser without the flag (`--default` exited 2)."""
    parser = build_parser()

    assert parser.parse_args(["setup"]).default is False
    assert parser.parse_args(["setup", "--default"]).default is True
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["setup", "--quick", "--default"])
    assert exc.value.code == 2


def test_sounds_command_forms_parse_and_conflicts_exit_two():
    parser = build_parser()

    assert parser.parse_args(["sounds"]).pack is None
    assert parser.parse_args(["sounds", "legacy"]).pack == "legacy"
    assert parser.parse_args(["sounds", "--list"]).list_packs is True
    assert parser.parse_args(["sounds", "--preview", "minimal-ui"]).preview == "minimal-ui"
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["sounds", "legacy", "--list"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["sounds", "legacy", "--preview", "minimal-ui"])
    assert exc.value.code == 2


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


def test_setup_default_dispatches_to_the_noninteractive_writer(monkeypatch):
    """Seen to FAIL against a handler that ignored the flag (the wizard ran)."""
    from stenographer.cli import setup as setup_engine

    hits: list[str] = []
    monkeypatch.setattr(setup_engine, "write_default", lambda **kw: hits.append("default") or 0)
    monkeypatch.setattr(setup_engine, "run", lambda **kw: hits.append("run") or 1)

    assert dispatch(["setup", "--default"]) == 0
    assert hits == ["default"]


def test_sounds_dispatches_to_handler(monkeypatch):
    from stenographer.cli.commands import sounds as sounds_command

    seen = []
    monkeypatch.setattr(
        sounds_command,
        "cmd_sounds",
        lambda args: seen.append((args.pack, args.list_packs, args.preview)) or 0,
    )

    assert dispatch(["sounds", "warm-desk"]) == 0
    assert seen == [("warm-desk", False, None)]


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


def test_main_doctor_dispatches_without_creating_the_daemon_log(monkeypatch, tmp_path):
    """Inspection must not create the file whose absence doctor reports."""

    import stenographer.cli as cli
    from stenographer.utils.logging_setup import shutdown_logging

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    log_path = tmp_path / "stenographer" / "stenographer.log"
    seen = []
    monkeypatch.setattr(cli, "dispatch", lambda argv: seen.append(argv) or 0)
    shutdown_logging()

    assert cli.main(["doctor"]) == 0

    assert seen == [("doctor",)]
    assert not log_path.exists()


def test_main_doctor_leaves_an_existing_daemon_log_unchanged(monkeypatch, tmp_path):
    """A read-only report must leave an existing diagnostic artifact untouched."""

    import stenographer.cli as cli
    from stenographer.utils.logging_setup import shutdown_logging

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    log_path = tmp_path / "stenographer" / "stenographer.log"
    log_path.parent.mkdir()
    sentinel = b"existing diagnostic bytes\n"
    log_path.write_bytes(sentinel)
    seen = []
    monkeypatch.setattr(cli, "dispatch", lambda argv: seen.append(argv) or 0)
    shutdown_logging()

    assert cli.main(["doctor"]) == 0

    assert seen == [("doctor",)]
    assert log_path.read_bytes() == sentinel


def test_main_flushes_the_log_queue_before_returning(monkeypatch, tmp_path, capsys):
    """Nothing else stops the listener: its thread is daemonic and never joined.

    Seen to FAIL against a ``main`` that dispatched without the ``finally``
    (only the handful of records the listener happened to drain in time
    reached the stream; the tail — the teardown lines — was lost).
    """

    import logging

    import stenographer.cli as cli
    from stenographer.utils.logging_setup import fmt_event, shutdown_logging

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("STENOGRAPHER_LOG_LEVEL", raising=False)

    def fake_dispatch(argv):
        log = logging.getLogger("stenographer.daemon")
        for step in range(500):
            log.info(fmt_event("daemon", "stopping", step=step))
        return 0

    monkeypatch.setattr(cli, "dispatch", fake_dispatch)
    try:
        assert cli.main([]) == 0
        # Read before any cleanup of our own: the question is what ``main``
        # itself had written by the time it returned.
        written = capsys.readouterr().err
    finally:
        shutdown_logging()

    assert "daemon: stopping step=499" in written


def test_with_config_applies_the_configured_log_level(monkeypatch, tmp_path):
    """Every config-reading command gets the threshold, not just ``run``.

    Seen to FAIL with the call living in ``cmd_run`` (a handler wrapped by
    ``with_config`` still logged at INFO under `log_level = "error"`).
    """

    import argparse
    import dataclasses
    import logging
    from io import StringIO

    import stenographer.config as config
    from stenographer.cli.commands import with_config
    from stenographer.utils.logging_setup import fmt_event, setup_logging, shutdown_logging

    defaults = config.Config.defaults()
    quiet = dataclasses.replace(
        defaults, feedback=dataclasses.replace(defaults.feedback, log_level="error")
    )
    monkeypatch.setattr(config, "load_or_default", lambda: quiet)
    monkeypatch.delenv("STENOGRAPHER_LOG_LEVEL", raising=False)

    def handler(args, cfg):
        logging.getLogger("stenographer.doctor").info(fmt_event("doctor", "probing"))
        logging.getLogger("stenographer.doctor").error(fmt_event("doctor", "refused"))
        return 0

    shutdown_logging()
    stream = StringIO()
    setup_logging(env={"XDG_STATE_HOME": str(tmp_path)}, home=tmp_path, stderr=stream)
    try:
        assert with_config(handler)(argparse.Namespace()) == 0
    finally:
        shutdown_logging()

    written = stream.getvalue()
    assert "doctor: probing" not in written
    assert "doctor: refused" in written


def test_run_dispatches_config_to_daemon(monkeypatch):
    # `run` loads config and hands it to daemon.run, returning its exit code.
    # daemon.run is stubbed here to verify wiring only (not to assert a mocked
    # subprocess call): the real daemon is exercised by manual dictation.
    import stenographer.config as config
    import stenographer.daemon as daemon

    # A real Config: `run` reads feedback.log_level off it before dispatching.
    sentinel = config.Config.defaults()
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
        "heavy = [n for n in ('faster_whisper', 'sounddevice', 'evdev', 'pywayland', 'Xlib')\n"
        "         if n in sys.modules]\n"
        "print(','.join(heavy))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""
