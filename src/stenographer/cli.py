# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line entry point: argparse surface and dispatch."""

from __future__ import annotations

import argparse
import multiprocessing
import pathlib
import sys
from collections.abc import Sequence

from stenographer._version import __version__


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

    return parser


def _fatal(message: str) -> int:
    """Print a capability/config failure and return the exit-78 code."""
    print(f"stenographer: {message}", file=sys.stderr)
    return 78


def _cmd_transcribe(args: argparse.Namespace) -> int:
    from stenographer import config
    from stenographer.format import format_transcript

    try:
        cfg = config.load_or_default()
    except config.ConfigError as exc:
        return _fatal(str(exc))

    path = pathlib.Path(args.file)
    if not path.exists():
        print(f"stenographer: file not found: {path}", file=sys.stderr)
        return 2

    from stenographer import model

    if not model.is_model_cached(cfg.asr.model):
        return _fatal("ASR model not found; run `stenographer model download`")

    import soundfile

    samples, sample_rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    if sample_rate != 16000:
        import logging

        logging.getLogger(__name__).warning(
            "transcribe: file sample rate is %d, not 16000 (pass-through)", sample_rate
        )

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
    from stenographer import config, model

    try:
        cfg = config.load_or_default()
    except config.ConfigError as exc:
        return _fatal(str(exc))

    model.download_model(cfg.asr.model)
    print(f"stenographer: downloaded {cfg.asr.model}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from stenographer import config

    try:
        cfg = config.load_or_default()
    except config.ConfigError as exc:
        return _fatal(str(exc))

    from stenographer import daemon

    return daemon.run(cfg)


def _format_input_devices(devices: list[dict], default_index: int) -> list[str]:
    """Pure: render the input-device listing, marking the default with ``*``."""
    lines = []
    for index, device in enumerate(devices):
        if device.get("max_input_channels", 0) <= 0:
            continue
        marker = "*" if index == default_index else " "
        channels = device["max_input_channels"]
        lines.append(f"{marker} {index}: {device.get('name', '?')} ({channels} ch)")
    if not lines:
        lines.append("  (no input devices found)")
    return lines


def _cmd_devices(args: argparse.Namespace) -> int:
    import sounddevice

    try:
        devices = sounddevice.query_devices()
    except sounddevice.PortAudioError as exc:
        print(f"stenographer: audio subsystem unavailable: {exc}", file=sys.stderr)
        return 1
    try:
        default_index = sounddevice.default.device[0]
    except (TypeError, IndexError):
        default_index = -1
    for line in _format_input_devices(list(devices), default_index):
        print(line)
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from stenographer import config, doctor

    try:
        cfg = config.load_or_default()
    except config.ConfigError as exc:
        return _fatal(str(exc))

    return doctor.run(cfg, config.resolve_config_path())


def dispatch(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch; startup boundaries belong in :func:`main`."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "transcribe":
        return _cmd_transcribe(args)
    if args.command == "model":
        return _cmd_model_download(args)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "doctor":
        return _cmd_doctor(args)
    return _cmd_devices(args)


def main(argv: Sequence[str] | None = None) -> int:
    """Configure the process, then parse and dispatch a command."""
    # Must run before argument parsing: in a frozen (PyInstaller) binary the
    # spawn-context worker child re-execs this entry point, and freeze_support
    # is what diverts it into the multiprocessing bootstrap instead.
    multiprocessing.freeze_support()
    from stenographer.logging_setup import setup_logging

    setup_logging()
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    # Private helper re-exec path: it intentionally bypasses argparse so it is
    # absent from the public command list and every help surface.
    from stenographer.overlay import private_entry_requested

    if private_entry_requested(arguments):
        from stenographer.overlay import run_overlay_helper

        return run_overlay_helper()
    return dispatch(arguments)


if __name__ == "__main__":
    sys.exit(main())
