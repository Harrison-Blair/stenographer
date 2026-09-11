# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import pathlib
from importlib.resources import files

log = logging.getLogger(__name__)


def bundled_icon_path() -> pathlib.Path:
    """The bundled app icon, anchored on the package like every other asset.

    Package-relative so the frozen bundle resolves it under
    ``_internal/stenographer/assets/`` with no ``sys._MEIPASS`` special-casing
    (see ``packaging/entry.py``).
    """
    return pathlib.Path(str(files("stenographer"))) / "assets" / "icons" / "stenographer.png"


def build_notify_command(
    message: str, urgency: str = "critical", icon: str | None = None
) -> list[str]:
    """The ``notify-send`` argv for a notification at *urgency*. PURE."""
    argv = ["notify-send", "-a", "Stenographer", "-u", urgency]
    if icon is not None:
        argv += ["-i", icon]
    return [*argv, "Stenographer", message]
