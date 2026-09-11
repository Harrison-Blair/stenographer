# SPDX-License-Identifier: GPL-3.0-or-later
"""Register completion arguments without runtime dependencies."""

SUPPORTED_SHELLS = ("bash", "zsh", "fish")


def register(subparsers) -> None:
    completion = subparsers.add_parser(
        "completion", help="Emit a native shell completion definition."
    )
    completion.add_argument("shell", choices=SUPPORTED_SHELLS)
