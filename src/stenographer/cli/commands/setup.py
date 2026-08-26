# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer setup``: interactive configuration review."""

from __future__ import annotations

import argparse


def cmd_setup(args: argparse.Namespace) -> int:
    from stenographer.cli import setup

    if args.default:
        return setup.write_default()
    return setup.run(quick=args.quick)
