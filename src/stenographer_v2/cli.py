# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line entry point: argparse surface and dispatch."""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys
from collections.abc import Sequence

from stenographer_v2._version import __version__

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Pure: importable and callable with only the stdlib present. No ASR/audio
    imports happen here or at module scope — those belong inside the
    subcommand handlers.
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


def _fatal(message: str) -> int:
    """Print a capability/config failure and return the exit-78 code."""
    print(f"stenographer: {message}", file=sys.stderr)
    return 78


def _cmd_transcribe(args: argparse.Namespace) -> int:
    from stenographer_v2 import config
    from stenographer_v2.format import format_transcript

    try:
        cfg = config.load_or_default()
    except config.ConfigError as exc:
        return _fatal(str(exc))

    path = pathlib.Path(args.file)
    if not path.exists():
        print(f"stenographer: file not found: {path}", file=sys.stderr)
        return 2

    from stenographer_v2 import model

    if not model.is_model_cached(cfg.asr.model):
        return _fatal("ASR model not found; run `stenographer model download`")

    import soundfile

    samples, sample_rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    if sample_rate != 16000:
        log.warning("transcribe: file sample rate is %d, not 16000 (pass-through)", sample_rate)

    m = model.Model(cfg.asr)
    try:
        result = m.transcribe(samples)
    finally:
        m.close()

    text = result.text if args.raw else format_transcript(result.text)
    sys.stdout.write(text)
    sys.stdout.write("\n")
    return 0


def _cmd_model_download(args: argparse.Namespace) -> int:
    from stenographer_v2 import config, model

    try:
        cfg = config.load_or_default()
    except config.ConfigError as exc:
        return _fatal(str(exc))

    model.download_model(cfg.asr.model)
    print(f"stenographer: downloaded {cfg.asr.model}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from stenographer_v2 import config

    try:
        cfg = config.load_or_default()
    except config.ConfigError as exc:
        return _fatal(str(exc))

    from stenographer_v2 import daemon

    return daemon.run(cfg)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch to a subcommand handler."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "transcribe":
        return _cmd_transcribe(args)
    if args.command == "model":
        return _cmd_model_download(args)
    if args.command == "run":
        return _cmd_run(args)
    return _stub(args.command)


if __name__ == "__main__":
    sys.exit(main())
