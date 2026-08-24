# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer doctor``: probe required capabilities."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from stenographer.cli.commands import with_config

if TYPE_CHECKING:
    from stenographer.config import Config


@with_config
def cmd_doctor(args: argparse.Namespace, cfg: Config) -> int:
    from stenographer import config
    from stenographer.cli import doctor

    return doctor.run(cfg, config.resolve_config_path())
