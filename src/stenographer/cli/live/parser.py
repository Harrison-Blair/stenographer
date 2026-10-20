# SPDX-License-Identifier: GPL-3.0-or-later
"""Argument parser for ``stenographer live``."""

from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction) -> None:
    live = subparsers.add_parser("live", help="Record and transcribe live audio.")
    live.add_argument(
        "--mic",
        dest="mic",
        action="store_true",
        default=True,
        help="Enable microphone capture (default).",
    )
    live.add_argument(
        "--system",
        dest="system",
        action="store_true",
        default=True,
        help="Enable system audio capture (default).",
    )
    disabled = live.add_mutually_exclusive_group()
    disabled.add_argument(
        "--no-mic", dest="mic", action="store_false", help="Disable microphone capture."
    )
    disabled.add_argument(
        "--no-system", dest="system", action="store_false", help="Disable system audio capture."
    )
    live.add_argument("--device", metavar="DEV", help="Use DEV as the microphone input device.")
