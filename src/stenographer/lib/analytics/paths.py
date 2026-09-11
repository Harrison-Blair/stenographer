# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve analytics storage through the current host provider."""

from pathlib import Path


def database_path() -> Path:
    # The provider owns all directory/environment semantics.
    import os

    from stenographer.lib.platform import current_platform

    return current_platform().state_dir(os.environ, Path.home()) / "analytics.sqlite3"
