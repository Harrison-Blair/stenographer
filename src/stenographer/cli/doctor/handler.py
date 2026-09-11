# SPDX-License-Identifier: GPL-3.0-or-later
"""``stenographer doctor``: probe required capabilities."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from stenographer.cli.shared.config import with_config

if TYPE_CHECKING:
    from stenographer.lib.config.models import Config


@with_config
def cmd_doctor(args: argparse.Namespace, cfg: Config) -> int:
    from stenographer.cli.doctor import report as doctor
    from stenographer.lib.config.paths import resolve_config_path

    return doctor.run(cfg, resolve_config_path())
