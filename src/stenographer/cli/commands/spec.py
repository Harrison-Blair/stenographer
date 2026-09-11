# SPDX-License-Identifier: GPL-3.0-or-later
"""Declarative description of one CLI subcommand."""

from __future__ import annotations

import argparse
import importlib
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Where a subcommand's parser and handler live, expressed as import paths.

    Module *paths* rather than imported objects keep two boundaries intact:
    the root parser stays importable with only the stdlib, and a handler's
    heavy dependencies load only when that command actually runs.

    A leaf command with no arguments supplies ``help`` and no parser module;
    a command with arguments supplies ``parser_module`` exposing
    ``register(subparsers)``. Exactly one of the two must be given.
    """

    name: str
    handler_module: str
    handler_name: str
    help: str | None = None
    parser_module: str | None = None

    def __post_init__(self) -> None:
        if (self.help is None) == (self.parser_module is None):
            raise ValueError(f"{self.name!r}: give exactly one of help or parser_module")

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        """Add this command to ``subparsers``."""
        if self.parser_module is None:
            subparsers.add_parser(self.name, help=self.help)
            return
        importlib.import_module(self.parser_module).register(subparsers)

    def load_handler(self) -> Callable[[argparse.Namespace], int]:
        """Import the handler now; looked up by name so tests may monkeypatch it."""
        return getattr(importlib.import_module(self.handler_module), self.handler_name)
