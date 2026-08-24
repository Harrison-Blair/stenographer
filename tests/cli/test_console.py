# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure gate and save-report tests for the shared interactive-CLI frame."""

from __future__ import annotations

import io
import pathlib

import pytest

from stenographer.cli.console import (
    Console,
    ask_yes_no,
    load_document,
    parse_bool,
    require_interactive,
    save_report_lines,
    streams_interactive,
)


class _Terminal(io.StringIO):
    """A stream that claims to be a terminal."""

    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize(
    ("stdin_tty", "stdout_tty", "expected"),
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_both_stream_ends_must_be_a_terminal(stdin_tty, stdout_tty, expected):
    stdin = _Terminal() if stdin_tty else io.StringIO()
    stdout = _Terminal() if stdout_tty else io.StringIO()

    assert streams_interactive(stdin, stdout) is expected


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
    lines = save_report_lines(
        changed=True,
        path=pathlib.PurePosixPath("/cfg/config.toml"),
        backup_path=pathlib.PurePosixPath("/cfg/config.toml.bak-1"),
        saved_prefix="Saved",
        unchanged_message="Configuration is unchanged; no file was written.",
    )

    assert lines == ["Saved /cfg/config.toml", "Backup: /cfg/config.toml.bak-1"]


def test_save_report_omits_a_missing_backup():
    lines = save_report_lines(
        changed=True,
        path=pathlib.PurePosixPath("/cfg/config.toml"),
        backup_path=None,
        saved_prefix="Selected sound pack legacy; saved",
        unchanged_message="Sound pack legacy is already selected; no file was written.",
    )

    assert lines == ["Selected sound pack legacy; saved /cfg/config.toml"]


def test_unchanged_save_reports_only_the_unchanged_sentence():
    lines = save_report_lines(
        changed=False,
        path=pathlib.PurePosixPath("/cfg/config.toml"),
        backup_path=pathlib.PurePosixPath("/cfg/config.toml.bak-1"),
        saved_prefix="Saved",
        unchanged_message="Configuration is unchanged; no file was written.",
    )

    assert lines == ["Configuration is unchanged; no file was written."]


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
    from stenographer.cli import console as console_module

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
