# SPDX-License-Identifier: GPL-3.0-or-later
"""Register model download arguments."""


def register(subparsers) -> None:
    subparsers.add_parser("download", help="Download the ASR model into the cache.")
