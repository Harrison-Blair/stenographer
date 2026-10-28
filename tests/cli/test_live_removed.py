# SPDX-License-Identifier: GPL-3.0-or-later
"""The standalone live command is gone; the hub Record screen replaces it."""

from __future__ import annotations

import re

import pytest

from stenographer.cli.completion.handler import completion_definition
from stenographer.cli.parser import build_parser

# Each pattern matches a top-level ``live`` command entry, never the
# ``model download --live`` flag or its description.
LIVE_COMMAND_ENTRIES = {
    "bash": (r"compgen -W '[^']*\brun live\b", r"^\s*live\)"),
    "zsh": (r"'live\[", r"^\s*live\)"),
    "fish": (r"-a live\b", r"__stenographer_command_is live'", r"\brun live\b"),
}


@pytest.mark.parametrize("argv", [["live"], ["live", "--help"]])
def test_live_command_is_an_invalid_choice(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(argv)

    assert exc.value.code == 2
    assert "invalid choice: 'live'" in capsys.readouterr().err


def test_top_level_help_does_not_list_live():
    help_text = build_parser().format_help()

    assert not re.search(r"(?<![-\w.])live(?![\w.])", help_text)


@pytest.mark.parametrize("shell", sorted(LIVE_COMMAND_ENTRIES))
def test_completion_does_not_offer_the_live_command(shell):
    definition = completion_definition(shell)

    for pattern in LIVE_COMMAND_ENTRIES[shell]:
        assert not re.search(pattern, definition, re.MULTILINE), pattern
