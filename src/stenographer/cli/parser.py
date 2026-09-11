# SPDX-License-Identifier: GPL-3.0-or-later
"""Root command parser; imports remain lightweight."""

import argparse

from stenographer._version import __version__
from stenographer.cli.commands.registry import COMMANDS


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Pure: importable and callable with only the stdlib present. No ASR/audio
    imports happen here or at module scope — those belong inside the
    subcommand handlers.
    """
    parser = argparse.ArgumentParser(
        prog="stenographer",
        description="Local, offline push-to-talk dictation.",
    )
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command", required=False)
    for spec in COMMANDS:
        spec.register(subparsers)
    return parser
