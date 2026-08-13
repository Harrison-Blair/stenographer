# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line entry point: argparse surface and dispatch (M0 scaffold stubs)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from stenographer_v2._version import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Pure: importable and callable with only the stdlib present. No ASR/audio
    imports happen here or at module scope — those belong inside the
    subcommand handlers added in later milestones.
    """
    parser = argparse.ArgumentParser(
        prog="stenographer-v2",
        description="Local, offline, Wayland push-to-talk dictation.",
    )
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("run", help="Run the dictation daemon.")

    transcribe = subparsers.add_parser("transcribe", help="Transcribe an audio file.")
    transcribe.add_argument("file", help="Path to the audio file to transcribe.")
    transcribe.add_argument("--raw", action="store_true", help="Emit the unformatted transcript.")

    model = subparsers.add_parser("model", help="Manage the ASR model.")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("download", help="Download the ASR model into the cache.")

    subparsers.add_parser("doctor", help="Probe required capabilities.")
    subparsers.add_parser("devices", help="List audio input devices.")

    return parser


def _stub(command: str) -> int:
    print(f"{command}: not implemented yet (M0 scaffold)", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch to a subcommand stub."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return _stub(args.command)


if __name__ == "__main__":
    sys.exit(main())
