# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer model``: dispatch to the selected model subcommand."""

from __future__ import annotations

import argparse

from stenographer.cli.commands.registry import resolve_command
from stenographer.cli.model.parser import MODEL_COMMANDS


def cmd_model(args: argparse.Namespace) -> int:
    return resolve_command(MODEL_COMMANDS, args.model_command).load_handler()(args)
