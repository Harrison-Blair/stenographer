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

    sub.add_parser("run", help="Start the daemon in the foreground.")

    enable = sub.add_parser(
        "enable", help="Install and enable the systemd user unit, then start it."
    )
    enable.add_argument(
        "--no-start", action="store_true", help="Enable the unit but do not start it now."
    )
    sub.add_parser("disable", help="Disable (and stop) the systemd user unit.")
    sub.add_parser("start", help="Start an existing systemd user unit.")
    sub.add_parser("stop", help="Stop any running daemon (systemd or foreground).")

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

    bench = sub.add_parser("bench", help="Benchmark ASR configs (batch matrix + streaming sim).")
    bench.add_argument(
        "file",
        type=pathlib.Path,
        nargs="?",
        default=None,
        help="Audio file or directory of clips. Omit and use --record instead.",
    )
    bench.add_argument(
        "--record",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Record SECONDS from the mic instead of reading a file.",
    )
    bench.add_argument(
        "--save", type=pathlib.Path, default=None, help="Save the --record capture to this WAV."
    )
    bench.add_argument(
        "--models",
        default=None,
        help="Comma-separated model ids to sweep (default: cached quality set).",
    )
    bench.add_argument("--beams", default="5,1", help="Comma-separated beam sizes (default 5,1).")
    bench.add_argument(
        "--computes",
        default="int8,int8_float16",
        help="Comma-separated compute types (default int8,int8_float16).",
    )
    bench.add_argument("--no-streaming", action="store_true", help="Skip the streaming simulation.")
    bench.add_argument(
        "--show-text", action="store_true", help="Print each config's full transcript."
    )
    bench.add_argument(
        "--stream-model",
        default=None,
        help="Model id for the streaming sim (default: large-v3 gold).",
    )
    bench.add_argument(
        "--chunk", type=float, default=1.0, help="Streaming step size in seconds (default 1.0)."
    )
    bench.add_argument("--agree", type=int, default=2, help="LocalAgreement window N (default 2).")
    bench.add_argument(
        "--no-context",
        action="store_true",
        help="Disable committed-text context prompt in streaming.",
    )

    return parser
