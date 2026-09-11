# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the command registry and its specs."""

from __future__ import annotations

import argparse
import importlib

import pytest

from stenographer.cli.commands.registry import COMMANDS, resolve_command
from stenographer.cli.commands.spec import CommandSpec
from stenographer.cli.model.parser import MODEL_COMMANDS


def test_spec_requires_exactly_one_parser_source():
    with pytest.raises(ValueError):
        CommandSpec("x", handler_module="m", handler_name="f")
    with pytest.raises(ValueError):
        CommandSpec("x", handler_module="m", handler_name="f", help="h", parser_module="p")


def test_leaf_spec_registers_argumentless_subcommand():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    CommandSpec("leaf", handler_module="m", handler_name="f", help="Leaf help.").register(
        subparsers
    )

    assert parser.parse_args(["leaf"]).command == "leaf"
    assert "Leaf help." in parser.format_help()
    with pytest.raises(SystemExit):
        parser.parse_args(["leaf", "extra"])


def test_spec_with_parser_module_delegates_to_register(monkeypatch):
    calls = []
    module = type("M", (), {"register": staticmethod(lambda sub: calls.append(sub))})
    monkeypatch.setattr(importlib, "import_module", lambda name: module)
    spec = CommandSpec("x", handler_module="m", handler_name="f", parser_module="fake")

    spec.register("SUB")

    assert calls == ["SUB"]


def test_load_handler_resolves_by_name_at_call_time(monkeypatch):
    module = type("M", (), {"cmd": staticmethod(lambda args: 7)})
    monkeypatch.setattr(importlib, "import_module", lambda name: module)
    spec = CommandSpec("x", handler_module="m", handler_name="cmd", help="h")

    assert spec.load_handler()(None) == 7
    module.cmd = staticmethod(lambda args: 8)
    assert spec.load_handler()(None) == 8


def test_registry_names_are_unique_and_resolvable():
    names = [spec.name for spec in COMMANDS]
    assert len(names) == len(set(names))
    for spec in COMMANDS:
        assert resolve_command(COMMANDS, spec.name) is spec


def test_resolve_unknown_command_raises():
    with pytest.raises(LookupError):
        resolve_command(COMMANDS, "bogus")


@pytest.mark.parametrize("spec", [*COMMANDS, *MODEL_COMMANDS], ids=lambda s: s.name)
def test_every_parser_module_exposes_register(spec):
    if spec.parser_module is None:
        return
    assert callable(importlib.import_module(spec.parser_module).register)
