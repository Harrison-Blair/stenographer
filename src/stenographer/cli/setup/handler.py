# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer setup``: interactive configuration review."""

from __future__ import annotations

import argparse


def cmd_setup(args: argparse.Namespace) -> int:
    from stenographer.cli.setup import workflow as setup

    if args.default:
        from stenographer.cli.setup.default import write_default

        return write_default()
    return setup.run(quick=args.quick)
