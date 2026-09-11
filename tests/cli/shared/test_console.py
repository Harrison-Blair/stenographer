# SPDX-License-Identifier: GPL-3.0-or-later
"""Prompt echo, end-of-input, and the validated retry loop of the shared console."""

from __future__ import annotations

import io

import pytest

from stenographer.cli.shared.console import Console


def _console(answers: str = "") -> Console:
    return Console(io.StringIO(answers), io.StringIO(), io.StringIO())


def test_ask_echoes_the_prompt_and_strips_only_the_line_ending():
    console = _console("  medium.en  \r\n")

    assert console.ask("Model: ") == "  medium.en  "
    assert console.stdout.getvalue() == "Model: "


def test_ask_raises_end_of_file_when_the_input_is_exhausted():
    console = _console("")

    with pytest.raises(EOFError):
        console.ask("Model: ")
    # The prompt is still written: the user's terminal shows what was asked.
    assert console.stdout.getvalue() == "Model: "


def test_validated_reports_every_rejection_and_returns_the_first_accepted_value():
    console = _console("zero\nnine\n7\n")

    def parse(text: str) -> int:
        if not text.strip().isdecimal():
            raise ValueError("enter an integer in [1, 10]")
        return int(text)

    assert console.validated("Beam size: ", parse) == 7
    assert console.stderr.getvalue() == (
        "stenographer: enter an integer in [1, 10]\nstenographer: enter an integer in [1, 10]\n"
    )
    assert console.stdout.getvalue() == "Beam size: Beam size: Beam size: "


def test_validated_lets_end_of_input_end_the_retry_loop():
    console = _console("zero\n")

    def parse(text: str) -> int:
        return int(text)

    with pytest.raises(EOFError):
        console.validated("Beam size: ", parse)
    assert "stenographer: invalid literal" in console.stderr.getvalue()
