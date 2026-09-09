# SPDX-License-Identifier: GPL-3.0-or-later
"""Environment-derived host facts: XDG user directories and journal detection."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

_APP = "stenographer"


def config_path(env: Mapping[str, str], home: Path) -> Path:
    """``$XDG_CONFIG_HOME/stenographer/config.toml`` (``~/.config`` fallback)."""
    xdg = env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else home / ".config"
    return base / _APP / "config.toml"


def state_dir(env: Mapping[str, str], home: Path) -> Path:
    """Resolve the application state directory using XDG precedence."""
    root = Path(env["XDG_STATE_HOME"]) if env.get("XDG_STATE_HOME") else home / ".local/state"
    return root / _APP


def runtime_dir(env: Mapping[str, str]) -> Path:
    """``$XDG_RUNTIME_DIR`` (``/run/user/<uid>`` fallback)."""
    return Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")


def journal_attached(env: Mapping[str, str]) -> bool:
    """True when systemd handed this process a journal stream for stderr.

    ``JOURNAL_STREAM`` is set by systemd for a unit whose output goes to the
    journal, which stamps every entry itself.
    """
    return "JOURNAL_STREAM" in env
