# SPDX-License-Identifier: GPL-3.0-or-later
"""Register doctor arguments without runtime dependencies."""


def register(subparsers) -> None:
    subparsers.add_parser("doctor", help="Probe required capabilities.")
