# SPDX-License-Identifier: GPL-3.0-or-later
"""Register setup arguments without runtime dependencies."""


def register(subparsers) -> None:
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
