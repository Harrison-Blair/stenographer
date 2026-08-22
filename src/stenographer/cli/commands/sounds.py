# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer sounds``: list, preview, and select whole sound packs."""

from __future__ import annotations

import argparse


def cmd_sounds(args: argparse.Namespace) -> int:
    from stenographer.cli import sounds

    return sounds.run(
        pack_name=args.pack,
        list_only=args.list_packs,
        preview_name=args.preview,
    )
