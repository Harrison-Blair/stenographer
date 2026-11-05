# SPDX-License-Identifier: GPL-3.0-or-later
"""``sounds`` dispatch: each parsed option reaches the workflow by its own name."""

from __future__ import annotations

import pytest

from stenographer.cli.parser import build_parser
from stenographer.cli.sounds.handler import cmd_sounds


def _args(*argv: str):
    return build_parser().parse_args(["sounds", *argv])


@pytest.mark.parametrize(
    ("argv", "expected_kwargs", "return_code"),
    [
        ((), {"pack_name": None, "list_only": False, "preview_name": None}, 0),
        (("--list",), {"pack_name": None, "list_only": True, "preview_name": None}, 2),
        (
            ("--preview", "warm-desk"),
            {"pack_name": None, "list_only": False, "preview_name": "warm-desk"},
            2,
        ),
        (("legacy",), {"pack_name": "legacy", "list_only": False, "preview_name": None}, 2),
    ],
)
def test_options_reach_the_workflow_and_return_its_code(
    monkeypatch, argv, expected_kwargs, return_code
):
    from stenographer.cli.sounds import workflow

    calls: list[dict] = []
    monkeypatch.setattr(workflow, "run", lambda **kwargs: calls.append(kwargs) or return_code)

    assert cmd_sounds(_args(*argv)) == return_code
    assert calls == [expected_kwargs]
