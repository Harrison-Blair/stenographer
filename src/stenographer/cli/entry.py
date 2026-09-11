# SPDX-License-Identifier: GPL-3.0-or-later
"""Process bootstrap, private helper dispatch, and public command dispatch."""

from __future__ import annotations

import multiprocessing
import sys
from collections.abc import Sequence

from stenographer.cli.commands.registry import COMMANDS, resolve_command
from stenographer.cli.parser import build_parser


def dispatch(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch; startup boundaries belong in :func:`main`.

    Handlers are imported lazily per command so no subcommand pays for
    another's heavy dependencies.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0
    return resolve_command(COMMANDS, args.command).load_handler()(args)


def main(argv: Sequence[str] | None = None) -> int:
    """Configure the process, then parse and dispatch a command."""
    # Must run before argument parsing: in a frozen (PyInstaller) binary the
    # spawn-context worker child re-execs this entry point, and freeze_support
    # is what diverts it into the multiprocessing bootstrap instead.
    multiprocessing.freeze_support()
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    # Private helper re-exec path: it intentionally bypasses argparse so it is
    # absent from the public command list and every help surface. The check
    # comes from the stdlib-only entry module; the helper itself is imported
    # only on the positive branch because it needs the runtime dependencies.
    from stenographer.overlay.entry import private_entry_requested

    if private_entry_requested(arguments):
        from stenographer.overlay.helper.execution import run_overlay_helper

        return run_overlay_helper()

    # Doctor reports the daemon log as an existing-or-absent host fact. Opening
    # the logging pipeline here would create that file before it can inspect it.
    if arguments and arguments[0] == "doctor":
        return dispatch(arguments)

    from stenographer.lib.logging.pipeline import setup_logging

    setup_logging()
    try:
        return dispatch(arguments)
    finally:
        # The listener thread is daemonic and atexit's logging.shutdown() closes
        # the sinks without draining them, so the teardown tail — the very lines
        # a stop is diagnosed from — would be lost without this.
        from stenographer.lib.logging.pipeline import shutdown_logging

        shutdown_logging()
