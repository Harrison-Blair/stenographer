# SPDX-License-Identifier: GPL-3.0-or-later
"""Gate, save-report, and document-load tests for the shared CLI frame."""

from __future__ import annotations

import io
import pathlib

import pytest

from stenographer.cli.shared.console import Console
from stenographer.cli.shared.terminal import (
    ask_yes_no,
    load_document,
    parse_bool,
    report_save,
    require_interactive,
)
from stenographer.lib.config.document import SaveResult
from tests.cli.support import Terminal as _Terminal


@pytest.mark.parametrize(
    ("stdin_tty", "stdout_tty", "expected"),
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_both_stream_ends_must_be_a_terminal(stdin_tty, stdout_tty, expected):
    stdin = _Terminal() if stdin_tty else io.StringIO()
    stdout = _Terminal() if stdout_tty else io.StringIO()

    assert Console(stdin, stdout, io.StringIO()).interactive is expected


def test_gate_reports_and_exits_two_without_a_terminal():
    stderr = io.StringIO()
    console = Console(io.StringIO(), io.StringIO(), stderr)

    assert require_interactive(console, "setup requires an interactive terminal") == 2
    assert stderr.getvalue() == "stenographer: setup requires an interactive terminal\n"


def test_gate_passes_silently_on_a_terminal():
    stderr = io.StringIO()
    console = Console(_Terminal(), _Terminal(), stderr)

    assert require_interactive(console, "setup requires an interactive terminal") is None
    assert stderr.getvalue() == ""


def test_inapplicable_gate_never_reports_or_exits():
    stderr = io.StringIO()
    console = Console(io.StringIO(), io.StringIO(), stderr)

    message = "sounds requires an interactive terminal"

    assert require_interactive(console, message, when=False) is None
    assert stderr.getvalue() == ""


def test_save_report_states_the_saved_path_and_backup():
    console = Console(io.StringIO(), io.StringIO(), io.StringIO())
    report_save(
        console,
        SaveResult(
            changed=True,
            path=pathlib.PurePosixPath("/cfg/config.toml"),
            backup_path=pathlib.PurePosixPath("/cfg/config.toml.bak-1"),
        ),
        saved_prefix="Saved",
        unchanged_message="Configuration is unchanged; no file was written.",
    )

    assert console.stdout.getvalue() == "Saved /cfg/config.toml\nBackup: /cfg/config.toml.bak-1\n"


def test_save_report_omits_a_missing_backup():
    console = Console(io.StringIO(), io.StringIO(), io.StringIO())
    report_save(
        console,
        SaveResult(
            changed=True,
            path=pathlib.PurePosixPath("/cfg/config.toml"),
            backup_path=None,
        ),
        saved_prefix="Selected sound pack legacy; saved",
        unchanged_message="Sound pack legacy is already selected; no file was written.",
    )

    assert console.stdout.getvalue() == "Selected sound pack legacy; saved /cfg/config.toml\n"


def test_unchanged_save_reports_only_the_unchanged_sentence():
    console = Console(io.StringIO(), io.StringIO(), io.StringIO())
    report_save(
        console,
        SaveResult(
            changed=False,
            path=pathlib.PurePosixPath("/cfg/config.toml"),
            backup_path=pathlib.PurePosixPath("/cfg/config.toml.bak-1"),
        ),
        saved_prefix="Saved",
        unchanged_message="Configuration is unchanged; no file was written.",
    )

    assert console.stdout.getvalue() == "Configuration is unchanged; no file was written.\n"


@pytest.mark.parametrize(("default", "marker"), [(True, "[Y/n]"), (False, "[y/N]")])
def test_ask_yes_no_marks_the_default_and_enter_retains_it(default, marker):
    console = Console(io.StringIO("\n"), io.StringIO(), io.StringIO())

    assert ask_yes_no(console, "Download it from the network now?", default=default) is default
    assert marker in console.stdout.getvalue()


def test_ask_yes_no_explicit_answer_overrides_the_default():
    console = Console(io.StringIO("n\n"), io.StringIO(), io.StringIO())

    assert ask_yes_no(console, "Restart the active service?", default=True) is False


@pytest.mark.parametrize("current", [True, False])
def test_parse_bool_enter_retains_either_current(current):
    assert parse_bool("", current) is current


@pytest.mark.parametrize(("blank_line", "expected_stdout"), [(True, "\n"), (False, "")])
def test_interrupted_load_keeps_each_commands_spacing(monkeypatch, blank_line, expected_stdout):
    from stenographer.cli.shared import terminal as console_module

    def interrupt(path):
        raise KeyboardInterrupt

    monkeypatch.setattr(console_module.ConfigDocument, "load", interrupt)
    console = Console(io.StringIO(), io.StringIO(), io.StringIO())

    code = load_document(
        console,
        interrupt_message="setup interrupted",
        blank_line_before_interrupt=blank_line,
    )

    assert code == 130
    assert console.stdout.getvalue() == expected_stdout
    assert console.stderr.getvalue() == "stenographer: setup interrupted\n"


def test_rejected_configuration_reports_the_key_error_and_exits_seventy_eight(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "config.toml"
    path.write_text("[stenographer.asr]\ncpu_threads = 99\n", encoding="utf-8")
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(path))
    console = Console(io.StringIO(), io.StringIO(), io.StringIO())

    code = load_document(
        console,
        interrupt_message="setup interrupted",
        blank_line_before_interrupt=True,
    )

    assert code == 78
    assert "cpu_threads" in console.stderr.getvalue()
    assert console.stdout.getvalue() == ""


def test_unreadable_configuration_reports_a_persistence_failure_and_exits_one(monkeypatch):
    from stenographer.cli.shared import terminal as terminal_module
    from stenographer.lib.config.errors import ConfigPersistenceError

    def refuse(path):
        raise ConfigPersistenceError(f"cannot resolve {path}: too many levels of symbolic links")

    monkeypatch.setattr(terminal_module.ConfigDocument, "load", refuse)
    console = Console(io.StringIO(), io.StringIO(), io.StringIO())

    code = load_document(
        console,
        interrupt_message="sounds interrupted",
        blank_line_before_interrupt=False,
    )

    assert code == 1
    assert "too many levels of symbolic links" in console.stderr.getvalue()
