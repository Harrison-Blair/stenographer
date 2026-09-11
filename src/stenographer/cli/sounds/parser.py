# SPDX-License-Identifier: GPL-3.0-or-later
"""Register sounds arguments without runtime dependencies."""


def register(subparsers) -> None:
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
