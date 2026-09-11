# SPDX-License-Identifier: GPL-3.0-or-later
"""Register ``model download`` arguments without runtime dependencies."""


def register(subparsers) -> None:
    download = subparsers.add_parser(
        "download",
        help="Download the ASR model, the refine model, or both.",
    )
    download.add_argument(
        "--asr",
        action="store_true",
        help="Download only the speech-recognition model.",
    )
    download.add_argument(
        "--refine",
        action="store_true",
        help="Pull only the refine model through the configured Ollama host.",
    )
