# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer doctor``: probe required capabilities."""

from __future__ import annotations

import argparse

from stenographer.cli import _fatal


def cmd_doctor(args: argparse.Namespace) -> int:
    from stenographer import config
    from stenographer.cli import doctor

    try:
        cfg = config.load_or_default()
    except config.ConfigError as exc:
        return _fatal(str(exc))

    return doctor.run(cfg, config.resolve_config_path())
