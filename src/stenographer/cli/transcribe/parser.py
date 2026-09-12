# SPDX-License-Identifier: GPL-3.0-or-later
"""Register transcribe arguments without runtime dependencies."""


def register(subparsers) -> None:
    transcribe = subparsers.add_parser("transcribe", help="Transcribe an audio file.")
    transcribe.add_argument("file", help="Path to the audio file to transcribe.")
    transcribe.add_argument("--raw", action="store_true", help="Emit the unformatted transcript.")
    transcribe.add_argument(
        "--refine",
        action="store_true",
        help="Clean the transcript through the configured local Ollama model.",
    )
