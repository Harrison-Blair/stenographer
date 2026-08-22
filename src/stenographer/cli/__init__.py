# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line entry point: argparse surface and dispatch."""

from __future__ import annotations

import argparse
import multiprocessing
import sys
from collections.abc import Sequence

from stenographer._version import __version__

SUPPORTED_SHELLS = ("bash", "zsh", "fish")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Pure: importable and callable with only the stdlib present. No ASR/audio
    imports happen here or at module scope — those belong inside the
    subcommand handlers.
    """
    parser = argparse.ArgumentParser(
        prog="stenographer",
        description="Local, offline, Wayland push-to-talk dictation.",
    )
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command", required=False)

    subparsers.add_parser("run", help="Run the dictation daemon.")

    transcribe = subparsers.add_parser("transcribe", help="Transcribe an audio file.")
    transcribe.add_argument("file", help="Path to the audio file to transcribe.")
    transcribe.add_argument("--raw", action="store_true", help="Emit the unformatted transcript.")

    model = subparsers.add_parser("model", help="Manage the ASR model.")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("download", help="Download the ASR model into the cache.")

    subparsers.add_parser("doctor", help="Probe required capabilities.")
    subparsers.add_parser("devices", help="List audio input devices.")
    setup = subparsers.add_parser(
        "setup", help="Interactively review configuration and capabilities."
    )
    setup.add_argument(
        "--quick",
        action="store_true",
        help="Configure the hotkey, microphone, and feedback essentials only.",
    )
    sounds = subparsers.add_parser("sounds", help="List, preview, or select a sound pack.")
    sounds_mode = sounds.add_mutually_exclusive_group()
    sounds_mode.add_argument("pack", nargs="?", help="Sound-pack name to select.")
    sounds_mode.add_argument(
        "--list",
        action="store_true",
        dest="list_packs",
        help="List available bundled and custom sound packs.",
    )
    sounds_mode.add_argument(
        "--preview",
        metavar="PACK",
        help="Preview a sound pack without changing configuration.",
    )
    completion = subparsers.add_parser(
        "completion", help="Emit a native shell completion definition."
    )
    completion.add_argument("shell", choices=SUPPORTED_SHELLS)

    return parser


def _fatal(message: str) -> int:
    """Print a capability/config failure and return the exit-78 code."""
    print(f"stenographer: {message}", file=sys.stderr)
    return 78


def dispatch(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch; startup boundaries belong in :func:`main`.

    Handlers are imported lazily per branch so no subcommand pays for
    another's heavy dependencies.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "transcribe":
        from stenographer.cli.commands.transcribe import cmd_transcribe

        return cmd_transcribe(args)
    if args.command == "model":
        from stenographer.cli.commands.model import cmd_model_download

        return cmd_model_download(args)
    if args.command == "run":
        from stenographer.cli.commands.run import cmd_run

        return cmd_run(args)
    if args.command == "doctor":
        from stenographer.cli.commands.doctor import cmd_doctor

        return cmd_doctor(args)
    if args.command == "devices":
        from stenographer.cli.commands.devices import cmd_devices

        return cmd_devices(args)
    if args.command == "completion":
        from stenographer.cli.commands.completion import cmd_completion

        return cmd_completion(args)
    if args.command == "sounds":
        from stenographer.cli.commands.sounds import cmd_sounds

        return cmd_sounds(args)
    from stenographer.cli.commands.setup import cmd_setup

    return cmd_setup(args)


def main(argv: Sequence[str] | None = None) -> int:
    """Configure the process, then parse and dispatch a command."""
    # Must run before argument parsing: in a frozen (PyInstaller) binary the
    # spawn-context worker child re-execs this entry point, and freeze_support
    # is what diverts it into the multiprocessing bootstrap instead.
    multiprocessing.freeze_support()
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    # Private helper re-exec path: it intentionally bypasses argparse so it is
    # absent from the public command list and every help surface. The check
    # comes from the stdlib-only entry module; the helper itself is imported
    # only on the positive branch because it needs the runtime dependencies.
    from stenographer.overlay.entry import private_entry_requested

    if private_entry_requested(arguments):
        from stenographer.overlay.supervisor import run_overlay_helper

        return run_overlay_helper()

    from stenographer.utils.logging_setup import setup_logging

    setup_logging()
    return dispatch(arguments)
