# SPDX-License-Identifier: GPL-3.0-or-later
"""The core must import with every Linux-only module blocked.

Run in a fresh interpreter (same style as test_cli_module_has_no_heavy_imports)
with ``sys.modules[name] = None`` for the Linux-only stack, so any core module
that regains a module-level ``import evdev``/``fcntl``/``termios``/... fails
loudly here on Linux instead of only on a Windows CI box. Seen to FAIL against
the pre-extraction tree (daemon.py imported fcntl; hotkey.py imported evdev).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[2] / "src" / "stenographer" / "platform"

CLI_IMPORT = re.compile(
    r"^\s*(?:from\s+stenographer\.cli|import\s+stenographer\.cli|from\s+\.{2,3}cli)\b", re.M
)

SRC_ROOT = PLATFORM_ROOT.parent

# Host-only prose and paths that must never reappear in core code or strings.
LINUX_WORDS = re.compile(
    r"systemctl|journalctl|install\.sh|/dev/uinput|usermod|wl-clipboard|xclip"
    r"|stenographer\.service"
)

BLOCKED = (
    "evdev",
    "fcntl",
    "termios",
    "grp",
    "pty",
    "pywayland",
    "Xlib",
    "stenographer.platform.linux",
)

CORE = (
    "stenographer.status",
    "stenographer.keycodes",
    "stenographer.config",
    "stenographer.audio",
    "stenographer.hotkey",
    "stenographer.audio_probe",
    "stenographer.capabilities",
    "stenographer.binding_capture",
    "stenographer.daemon",
    "stenographer.delivery.deliver",
    "stenographer.delivery.feedback",
    "stenographer.cli",
    "stenographer.cli.doctor",
    "stenographer.cli.setup",
    "stenographer.cli.setup_config",
    "stenographer.cli.sounds",
    "stenographer.cli.binding_capture",
    "stenographer.cli.calibration",
    "stenographer.cli.commands.run",
    "stenographer.cli.commands.doctor",
    "stenographer.cli.commands.devices",
    "stenographer.cli.commands.setup",
    "stenographer.cli.commands.sounds",
    "stenographer.cli.commands.model",
    "stenographer.cli.commands.transcribe",
    "stenographer.cli.commands.completion",
    "stenographer.overlay",
    "stenographer.overlay.supervisor",
    "stenographer.overlay.render",
    "stenographer.overlay.spectrum",
    "stenographer.transcribe.worker",
    "stenographer.transcribe.model",
    "stenographer.transcribe.format",
    "stenographer.utils.logging_setup",
    "stenographer.platform",
    "stenographer.platform.base",
    "stenographer.platform.windows",
)


def test_platform_providers_never_import_the_cli():
    """The boundary is directional: providers may use core vocabulary, never ``cli``."""

    offenders = sorted(
        str(path.relative_to(PLATFORM_ROOT))
        for path in PLATFORM_ROOT.rglob("*.py")
        if CLI_IMPORT.search(path.read_text(encoding="utf-8"))
    )
    assert not offenders, offenders


def test_core_never_hardcodes_linux_prose():
    """Labels, fix hints, and service commands come from ``HostGuidance``, not core."""

    offenders = sorted(
        str(path.relative_to(SRC_ROOT))
        for path in SRC_ROOT.rglob("*.py")
        if not path.is_relative_to(PLATFORM_ROOT / "linux")
        and LINUX_WORDS.search(path.read_text(encoding="utf-8"))
    )
    assert not offenders, offenders


def test_core_imports_with_linux_only_modules_blocked():
    code = (
        "import importlib, sys\n"
        f"for name in {BLOCKED!r}:\n"
        "    sys.modules[name] = None\n"
        f"for name in {CORE!r}:\n"
        "    importlib.import_module(name)\n"
        "import stenographer.cli as cli\n"
        "cli.build_parser()\n"
        "from stenographer.platform.base import Platform\n"
        "from stenographer.platform.windows import WindowsPlatform\n"
        "assert isinstance(WindowsPlatform(), Platform)\n"
        "leaked = [n for n, m in sys.modules.items()\n"
        "          if n.startswith('stenographer.platform.linux') and m is not None]\n"
        "assert not leaked, leaked\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
