# SPDX-License-Identifier: GPL-3.0-or-later
"""``sounds`` dispatch: each parsed option reaches the workflow by its own name."""

from __future__ import annotations

from stenographer.cli.parser import build_parser
from stenographer.cli.sounds.handler import cmd_sounds


def _args(*argv: str):
    return build_parser().parse_args(["sounds", *argv])


def test_bare_invocation_asks_the_workflow_for_the_menu(monkeypatch):
    from stenographer.cli.sounds import workflow

    calls: list[dict] = []
    monkeypatch.setattr(workflow, "run", lambda **kwargs: calls.append(kwargs) or 0)

    assert cmd_sounds(_args()) == 0
    assert calls == [{"pack_name": None, "list_only": False, "preview_name": None}]


def test_each_option_is_forwarded_and_the_workflow_exit_code_is_returned(monkeypatch):
    from stenographer.cli.sounds import workflow

    calls: list[dict] = []
    monkeypatch.setattr(workflow, "run", lambda **kwargs: calls.append(kwargs) or 2)

    assert cmd_sounds(_args("--list")) == 2
    assert cmd_sounds(_args("--preview", "warm-desk")) == 2
    assert cmd_sounds(_args("legacy")) == 2

    assert calls == [
        {"pack_name": None, "list_only": True, "preview_name": None},
        {"pack_name": None, "list_only": False, "preview_name": "warm-desk"},
        {"pack_name": "legacy", "list_only": False, "preview_name": None},
    ]
