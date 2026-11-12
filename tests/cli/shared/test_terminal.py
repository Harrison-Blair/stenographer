# SPDX-License-Identifier: GPL-3.0-or-later
"""Gate, save-report, and document-load tests for the shared CLI frame."""

from __future__ import annotations

import io

import pytest

from stenographer.cli.shared.console import Console
from stenographer.cli.shared.terminal import (
    ask_yes_no,
    load_document,
)
from tests.cli.support import Terminal as _Terminal


@pytest.mark.parametrize(
    ("stdin_tty", "stdout_tty", "expected"),
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_both_stream_ends_must_be_a_terminal(stdin_tty, stdout_tty, expected):
    stdin = _Terminal() if stdin_tty else io.StringIO()
    stdout = _Terminal() if stdout_tty else io.StringIO()

    assert Console(stdin, stdout, io.StringIO()).interactive is expected


@pytest.mark.parametrize(("default", "marker"), [(True, "[Y/n]"), (False, "[y/N]")])
def test_ask_yes_no_marks_the_default_and_enter_retains_it(default, marker):
    console = Console(io.StringIO("\n"), io.StringIO(), io.StringIO())

    assert ask_yes_no(console, "Download it from the network now?", default=default) is default
    assert marker in console.stdout.getvalue()


def test_ask_yes_no_explicit_answer_overrides_the_default():
    console = Console(io.StringIO("n\n"), io.StringIO(), io.StringIO())

    assert ask_yes_no(console, "Restart the active service?", default=True) is False


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
    path.write_text("[stenographer.asr]\nidle_unload_seconds = -1\n", encoding="utf-8")
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(path))
    console = Console(io.StringIO(), io.StringIO(), io.StringIO())

    code = load_document(
        console,
        interrupt_message="setup interrupted",
        blank_line_before_interrupt=True,
    )

    assert code == 78
    assert "idle_unload_seconds" in console.stderr.getvalue()
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
