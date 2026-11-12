# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the CLI parser."""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

import stenographer
from stenographer.cli.entry import dispatch
from stenographer.cli.parser import build_parser


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


@pytest.mark.parametrize(
    ("argv", "module", "handler", "expected"),
    [
        (["run"], "run.handler", "cmd_run", {"command": "run"}),
        (["doctor"], "doctor.handler", "cmd_doctor", {"command": "doctor"}),
        (["devices"], "devices.handler", "cmd_devices", {"command": "devices"}),
        (["setup"], "setup.handler", "cmd_setup", {"command": "setup", "quick": False}),
        (["setup", "--quick"], "setup.handler", "cmd_setup", {"quick": True}),
        (
            ["sounds", "warm-desk"],
            "sounds.handler",
            "cmd_sounds",
            {"pack": "warm-desk", "list_packs": False, "preview": None},
        ),
        (
            ["transcribe", "clip.wav"],
            "transcribe.handler",
            "cmd_transcribe",
            {"command": "transcribe", "file": "clip.wav", "raw": False},
        ),
        (
            ["transcribe", "clip.wav", "--raw"],
            "transcribe.handler",
            "cmd_transcribe",
            {"file": "clip.wav", "raw": True},
        ),
        (
            ["model", "download"],
            "model.download.handler",
            "cmd_model_download",
            {"command": "model", "model_command": "download"},
        ),
    ],
)
def test_commands_dispatch_parsed_arguments(argv, module, handler, expected, monkeypatch):
    target = importlib.import_module(f"stenographer.cli.{module}")
    seen = []
    monkeypatch.setattr(target, handler, lambda args: seen.append(vars(args)) or 0)
    assert dispatch(argv) == 0
    assert len(seen) == 1
    assert {key: seen[0][key] for key in expected} == expected


def test_setup_default_dispatches_to_the_noninteractive_writer(monkeypatch):
    """Seen to FAIL against a handler that ignored the flag (the wizard ran)."""
    from stenographer.cli.setup import default as default_engine
    from stenographer.cli.setup import workflow as setup_engine

    hits: list[str] = []
    monkeypatch.setattr(default_engine, "write_default", lambda **kw: hits.append("default") or 0)
    monkeypatch.setattr(setup_engine, "run", lambda **kw: hits.append("run") or 1)

    assert dispatch(["setup", "--default"]) == 0
    assert hits == ["default"]


def test_main_doctor_dispatches_without_creating_the_daemon_log(monkeypatch, tmp_path):
    """Inspection must not create the file whose absence doctor reports."""

    import stenographer.cli.entry as cli
    from stenographer.lib.logging.pipeline import shutdown_logging

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

    import stenographer.cli.entry as cli
    from stenographer.lib.logging.pipeline import shutdown_logging

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

    import stenographer.cli.entry as cli
    from stenographer.lib.logging.pipeline import fmt_event, shutdown_logging

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("STENOGRAPHER_LOG_LEVEL", raising=False)

    def fake_dispatch(argv):
        log = logging.getLogger("stenographer.lib.daemon")
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


def test_run_dispatches_config_to_daemon(monkeypatch):
    # `run` loads config and hands it to daemon.run, returning its exit code.
    # daemon.run is stubbed here to verify wiring only (not to assert a mocked
    # subprocess call): the real daemon is exercised by manual dictation.
    import stenographer.cli.run.startup as daemon
    import stenographer.lib.config.models as config
    import stenographer.lib.config.paths as config_paths

    sentinel = config.Config.defaults()
    monkeypatch.setattr(config_paths, "load_or_default", lambda: sentinel)
    seen = {}

    def fake_run(cfg):
        seen["cfg"] = cfg
        return 3

    monkeypatch.setattr(daemon, "run", fake_run)
    assert dispatch(["run"]) == 3
    assert seen["cfg"] is sentinel


def test_unknown_subcommand_errors():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["bogus"])
    assert exc.value.code == 2


def test_private_overlay_entry_is_absent_from_public_help(capsys):
    with pytest.raises(SystemExit) as exc:
        dispatch(["--help"])
    assert exc.value.code == 0
    assert "_overlay" not in capsys.readouterr().out


def test_cli_help_does_not_import_numpy():
    code = (
        "import sys\n"
        "sys.modules['numpy'] = None\n"
        "from stenographer.cli import main\n"
        "raise SystemExit(main(['--help']))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "usage: stenographer" in result.stdout


def test_cli_module_has_no_heavy_imports():
    # Importing the CLI (and building its parser) must not pull in the ASR,
    # audio, or evdev stacks — those belong inside subcommand handlers. Checked
    # in a fresh interpreter so the assertion reflects this module's own import
    # graph, not a sys.modules table already polluted by the rest of the suite.
    code = (
        "import sys\n"
        "import stenographer.cli.entry as cli\n"
        "cli.build_parser()\n"
        "heavy = [n for n in ('sherpa_onnx', 'sounddevice', 'evdev', 'pywayland', 'Xlib')\n"
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


def test_command_surface():
    parser = build_parser()
    help_text = parser.format_help()
    assert "{run,transcribe,model,doctor,devices,setup,sounds,completion,stats}" in help_text
    examples = [
        (["run"], {"command": "run"}),
        (
            ["transcribe", "clip.wav", "--raw", "--refine"],
            {"file": "clip.wav", "raw": True, "refine": True},
        ),
        (
            ["model", "download", "--asr", "--refine"],
            {"model_command": "download", "asr": True, "refine": True},
        ),
        (["doctor"], {"command": "doctor"}),
        (["devices"], {"command": "devices"}),
        (["setup", "--quick"], {"quick": True}),
        (["setup", "--default"], {"default": True}),
        (["sounds", "--list"], {"list_packs": True}),
        (["sounds", "--preview", "pack"], {"preview": "pack"}),
        (["completion", "fish"], {"shell": "fish"}),
        (
            [
                "stats",
                "export",
                "--source",
                "file",
                "--since",
                "2020-01-01",
                "--until",
                "2020-01-02",
                "--model",
                "m",
                "--app-version",
                "v",
                "--device",
                "d",
                "--outcome",
                "o",
                "--format",
                "csv",
                "--output",
                "out",
                "--yes",
            ],
            {
                "stats_command": "export",
                "source": "file",
                "since": "2020-01-01",
                "until": "2020-01-02",
                "model": "m",
                "app_version": "v",
                "device": "d",
                "outcome": "o",
                "format": "csv",
                "output": "out",
                "yes": True,
            },
        ),
    ]
    for argv, expected in examples:
        parsed = vars(parser.parse_args(argv))
        assert all(parsed[key] == value for key, value in expected.items())
    with pytest.raises(SystemExit):
        parser.parse_args(["model"])


def test_information_commands_do_not_initialize_logging(monkeypatch, capsys):
    import pytest

    from stenographer.cli.entry import main
    from stenographer.lib.logging import pipeline

    def unexpected():
        raise AssertionError("logging started")

    monkeypatch.setattr(pipeline, "setup_logging", unexpected)
    for option in ("--help", "-h", "--version"):
        with pytest.raises(SystemExit) as exit_info:
            main([option])
        assert exit_info.value.code == 0
        assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("command", "description"),
    [
        ("run", "Run the dictation daemon."),
        ("doctor", "Probe required capabilities."),
        ("devices", "List audio input devices."),
    ],
)
def test_leaf_help_includes_description(command, description, capsys):
    with pytest.raises(SystemExit):
        dispatch([command, "--help"])
    assert description in capsys.readouterr().out
