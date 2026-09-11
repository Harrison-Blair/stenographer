# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve configuration locations and load or write defaults."""

from __future__ import annotations

import os
import pathlib

from stenographer.lib.config.models import Config


def resolve_config_path(*, create_parent: bool = True) -> pathlib.Path:
    """Return the configured path, optionally creating its parent directory."""

    env_path = os.environ.get("STENOGRAPHER_CONFIG")
    if env_path:
        path = pathlib.Path(env_path)
    else:
        from stenographer.lib.platform import current_platform

        path = current_platform().config_path(os.environ, pathlib.Path.home())
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_or_default() -> Config:
    path = resolve_config_path()
    if path.is_file():
        return Config.load(path)
    Config.write_default(path)
    return Config.defaults()
