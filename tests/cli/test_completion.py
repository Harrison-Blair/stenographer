# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for the static native completion definitions."""

from __future__ import annotations

import argparse

import pytest

from stenographer.cli import SUPPORTED_SHELLS, build_parser, dispatch
from stenographer.cli.commands.completion import completion_definition


def _public_cli_tokens(parser: argparse.ArgumentParser) -> set[str]:
    tokens: set[str] = set()
    pending = [parser]
    while pending:
        current = pending.pop()
        for action in current._actions:
            tokens.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                tokens.update(action.choices)
                pending.extend(action.choices.values())
    return tokens


def test_completion_shell_choices_parse():
    parser = build_parser()

    for shell in SUPPORTED_SHELLS:
        args = parser.parse_args(["completion", shell])
        assert args.command == "completion"
        assert args.shell == shell


@pytest.mark.parametrize("argv", [["completion"], ["completion", "powershell"]])
def test_completion_rejects_missing_or_unsupported_shell(argv):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(argv)
    assert exc.value.code == 2


@pytest.mark.parametrize(
    ("shell", "registration"),
    [
        ("bash", "complete -F _stenographer stenographer"),
        ("zsh", "#compdef stenographer"),
        ("fish", "complete -c stenographer"),
    ],
)
def test_completion_output_is_deterministic_spdx_marked_and_registered(shell, registration):
    first = completion_definition(shell)
    second = completion_definition(shell)

    assert first == second
    assert first.endswith("\n")
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in first
    assert registration in first
    assert "_overlay" not in first


@pytest.mark.parametrize("shell", SUPPORTED_SHELLS)
def test_completion_assets_cover_every_public_parser_token(shell):
    definition = completion_definition(shell)

    for token in _public_cli_tokens(build_parser()):
        fish_option = None
        if shell == "fish" and token.startswith("--"):
            fish_option = f"-l {token.removeprefix('--')}"
        elif shell == "fish" and token.startswith("-"):
            fish_option = f"-s {token.removeprefix('-')}"
        assert token in definition or fish_option in definition, (
            f"{shell} completion is missing {token}"
        )


@pytest.mark.parametrize(
    ("shell", "path_marker"),
    [("bash", "compgen -f"), ("zsh", "_files"), ("fish", "-F")],
)
def test_transcribe_completion_uses_native_file_completion(shell, path_marker):
    assert path_marker in completion_definition(shell)


def test_completion_dispatch_writes_only_the_selected_definition(capsys):
    assert dispatch(["completion", "fish"]) == 0
    captured = capsys.readouterr()
    assert captured.out == completion_definition("fish")
    assert captured.err == ""
