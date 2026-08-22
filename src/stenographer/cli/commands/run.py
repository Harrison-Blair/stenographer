# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer run``: the dictation daemon."""

from __future__ import annotations

import argparse

from stenographer.cli import _fatal


def cmd_run(args: argparse.Namespace) -> int:
    from stenographer import config

    try:
        cfg = config.load_or_default()
    except config.ConfigError as exc:
        return _fatal(str(exc))

    from stenographer import daemon

    return daemon.run(cfg)
