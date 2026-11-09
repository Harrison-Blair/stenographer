# SPDX-License-Identifier: GPL-3.0-or-later
"""Root command parser; imports remain lightweight."""

import argparse

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
        description="Local, offline push-to-talk dictation.",
    )
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command", required=False)
    subparsers.add_parser(
        "run", help="Run the dictation daemon.", description="Run the dictation daemon."
    )
    _transcribe(subparsers)
    _model(subparsers)
    subparsers.add_parser(
        "doctor", help="Probe required capabilities.", description="Probe required capabilities."
    )
    subparsers.add_parser(
        "devices", help="List audio input devices.", description="List audio input devices."
    )
    _setup(subparsers)
    _sounds(subparsers)
    _completion(subparsers)
    _stats(subparsers)
    return parser


def _transcribe(subparsers) -> None:
    transcribe = subparsers.add_parser("transcribe", help="Transcribe an audio file.")
    transcribe.add_argument("file", help="Path to the audio file to transcribe.")
    transcribe.add_argument("--raw", action="store_true", help="Emit the unformatted transcript.")
    transcribe.add_argument(
        "--refine",
        action="store_true",
        help="Clean the transcript through the configured local Ollama model.",
    )


def _setup(subparsers) -> None:
    setup = subparsers.add_parser(
        "setup", help="Interactively review configuration and capabilities."
    )
    setup_mode = setup.add_mutually_exclusive_group()
    setup_mode.add_argument(
        "--quick",
        action="store_true",
        help="Configure the hotkey, microphone, and feedback essentials only.",
    )
    setup_mode.add_argument(
        "--default",
        action="store_true",
        help="Write the annotated default configuration without prompting.",
    )


def _sounds(subparsers) -> None:
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


def _completion(subparsers) -> None:
    completion = subparsers.add_parser(
        "completion", help="Emit a native shell completion definition."
    )
    completion.add_argument("shell", choices=SUPPORTED_SHELLS)


def _stats(subparsers) -> None:
    stats = subparsers.add_parser(
        "stats",
        help="Report durable personal dictation analytics.",
        description="Reset deletes all records; use delete for filtered deletion.",
    )
    stats.add_argument(
        "stats_command",
        nargs="?",
        default="summary",
        choices=("summary", "export", "delete", "reset"),
    )
    stats.add_argument(
        "--source",
        choices=("hotkey", "file", "all"),
        default=None,
        help="Filter by source (default: hotkey); unavailable for reset.",
    )
    stats.add_argument("--since", metavar="YYYY-MM-DD", help="First local calendar day, inclusive.")
    stats.add_argument("--until", metavar="YYYY-MM-DD", help="Last local calendar day, inclusive.")
    stats.add_argument("--model", help="Exact model identifier.")
    stats.add_argument("--app-version", help="Exact application version.")
    stats.add_argument("--device", help="Exact microphone name.")
    stats.add_argument("--outcome", help="Exact terminal outcome.")
    stats.add_argument(
        "--format", choices=("json", "csv"), help="Export format (export only; default: json)."
    )
    stats.add_argument(
        "--output", help="Write export to this file instead of standard output (export only)."
    )
    stats.add_argument(
        "--yes", action="store_true", help="Confirm deletion after showing its count."
    )


def _model(subparsers) -> None:
    model = subparsers.add_parser("model", help="Manage the ASR and refine models.")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    _model_download(model_sub)


def _model_download(subparsers) -> None:
    download = subparsers.add_parser(
        "download",
        help="Download the ASR or refine model; flags can be combined.",
        description="Download models; selection flags can be combined.",
    )
    download.add_argument(
        "--asr",
        action="store_true",
        help="Add the speech-recognition model to the selection.",
    )
    download.add_argument(
        "--refine",
        action="store_true",
        help="Add the refine model through the configured Ollama host.",
    )
