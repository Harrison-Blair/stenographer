# SPDX-License-Identifier: GPL-3.0-or-later
"""Register devices arguments without runtime dependencies."""


def register(subparsers) -> None:
    subparsers.add_parser("devices", help="List audio input devices.")
