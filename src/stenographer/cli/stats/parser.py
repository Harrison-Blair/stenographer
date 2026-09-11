# SPDX-License-Identifier: GPL-3.0-or-later
"""Register stats arguments without runtime dependencies."""


def register(subparsers) -> None:
    stats = subparsers.add_parser("stats", help="Report durable personal dictation analytics.")
    stats.add_argument(
        "stats_command",
        nargs="?",
        default="summary",
        choices=("summary", "export", "delete", "reset"),
    )
    stats.add_argument("--source", choices=("hotkey", "file", "all"), default="hotkey")
    stats.add_argument("--since", metavar="YYYY-MM-DD", help="First local calendar day, inclusive.")
    stats.add_argument("--until", metavar="YYYY-MM-DD", help="Last local calendar day, inclusive.")
    stats.add_argument("--model", help="Exact model identifier.")
    stats.add_argument("--app-version", help="Exact application version.")
    stats.add_argument("--device", help="Exact microphone name.")
    stats.add_argument("--outcome", help="Exact terminal outcome.")
    stats.add_argument("--format", choices=("json", "csv"), default="json")
    stats.add_argument("--output", help="Write export to this file instead of standard output.")
    stats.add_argument(
        "--yes", action="store_true", help="Confirm deletion after showing its count."
    )
