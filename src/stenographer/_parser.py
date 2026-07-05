# SPDX-License-Identifier: GPL-3.0-or-later
"""Argument parser, kept import-light so shell completion stays fast.

This module is imported on the argcomplete hot path (every Tab press),
so it must not pull in heavy dependencies like faster-whisper or
sounddevice.
"""

from __future__ import annotations

import argparse
import pathlib

from stenographer import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stenographer",
        description="Local, offline, Wayland push-to-talk / toggle dictation.",
    )
    parser.add_argument("-c", "--config", type=pathlib.Path, default=None)
    parser.add_argument("-v", "--version", action="version", version=f"stenographer {__version__}")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    run_parser = sub.add_parser("run", help="Start/stop/disable the daemon.")
    run_sub = run_parser.add_subparsers(dest="run_command", required=False)
    run_sub.add_parser("stop", help="Stop any running daemon.")
    run_sub.add_parser("disable", help="Disable the systemd user unit.")

    transcribe = sub.add_parser("transcribe", help="Transcribe an audio file and print to stdout.")
    transcribe.add_argument("file", type=pathlib.Path)

    sub.add_parser("dictate", help="One-shot dictation.")

    model = sub.add_parser("model", help="Model management.")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("download", help="Download the configured ASR model.")

    update = sub.add_parser("update", help="Check for and install a newer release.")
    update.add_argument(
        "--check", action="store_true", help="Only check; do not download or restart."
    )
    update.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    update.add_argument(
        "--no-restart",
        action="store_true",
        help="Do not start the daemon after the install.",
    )
    update.add_argument("--prerelease", action="store_true", help="Include pre-release tags.")
    update.add_argument("--repo", default=None, help="Override the configured GitHub OWNER/REPO.")

    sub.add_parser("doctor", help="Print capability probe and resolved config.")

    sub.add_parser("devices", help="List audio input devices.")

    return parser
