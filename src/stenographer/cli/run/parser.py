# SPDX-License-Identifier: GPL-3.0-or-later
"""Register run arguments without runtime dependencies."""


def register(subparsers) -> None:
    subparsers.add_parser("run", help="Run the dictation daemon.")
