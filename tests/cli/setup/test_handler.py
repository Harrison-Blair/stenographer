# SPDX-License-Identifier: GPL-3.0-or-later
"""``setup`` dispatch: --default writes, otherwise the wizard runs in its mode."""

from __future__ import annotations

import pytest

from stenographer.cli.parser import build_parser
from stenographer.cli.setup.handler import cmd_setup


def _args(*argv: str):
    return build_parser().parse_args(["setup", *argv])


def test_default_writes_the_template_and_never_starts_the_wizard(monkeypatch):
    from stenographer.cli.setup import default
    from stenographer.cli.setup import workflow as setup

    calls: list[str] = []
    monkeypatch.setattr(default, "write_default", lambda: calls.append("write") or 0)
    monkeypatch.setattr(setup, "run", lambda **kwargs: calls.append("wizard") or 0)

    assert cmd_setup(_args("--default")) == 0
    assert calls == ["write"]


@pytest.mark.parametrize(("argv", "expected"), [((), False), (("--quick",), True)])
def test_the_wizard_is_started_in_the_requested_mode(monkeypatch, argv, expected):
    from stenographer.cli.setup import workflow as setup

    calls: list[dict] = []
    monkeypatch.setattr(setup, "run", lambda **kwargs: calls.append(kwargs) or 3)

    assert cmd_setup(_args(*argv)) == 3
    assert calls == [{"quick": expected}]
