# SPDX-License-Identifier: GPL-3.0-or-later
"""systemd user-unit management for the Stenographer daemon.

Single owner of the systemd knowledge that used to be rebuilt inline across
``cli.py`` and ``update.py``: the unit-name constant, the ``systemctl --user``
argv builder, the unit-file template, and resolution of the launcher path
baked into ``ExecStart``. The CLI lifecycle subcommands and the self-update
stop/start helpers construct their invocations from here so the unit name and
manager scope live in exactly one place.
"""

from __future__ import annotations

import pathlib
import shutil
import sys

UNIT_NAME = "stenographer.service"


def systemctl_argv(*args: str) -> list[str]:
    """Build a ``systemctl --user`` command line for the given arguments."""
    return ["systemctl", "--user", *args]


def resolve_daemon_exec() -> str:
    """Return the ``ExecStart`` command line for the systemd user unit.

    Resolves the path to the launcher that should run the daemon. For
    the PyInstaller onedir binary this is ``sys.executable`` (the
    bundle launcher); for a pip/pipx console-script install it is the
    ``stenographer`` entry point on ``PATH``. The path is resolved so a
    symlinked launcher (e.g. ``~/.local/bin/stenographer``) expands to
    its real target, matching what ``scripts/install.sh`` writes.
    """
    if getattr(sys, "frozen", False):
        launcher = pathlib.Path(sys.executable).resolve()
    else:
        found = shutil.which("stenographer")
        launcher = pathlib.Path(found or sys.argv[0]).resolve()
    return f"{launcher} run"


def render_unit(exec_start: str) -> str:
    """Render the systemd user unit for the given ``ExecStart`` command line."""
    return (
        "[Unit]\n"
        "Description=stenographer dictation daemon\n"
        "After=graphical-session.target pipewire.service pulseaudio.service\n"
        "PartOf=graphical-session.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        "RestartSec=2\n"
        "\n"
        "[Install]\n"
        "WantedBy=graphical-session.target\n"
    )
