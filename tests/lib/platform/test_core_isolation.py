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

SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "stenographer"
PLATFORM_ROOT = SRC_ROOT / "lib" / "platform"
OVERLAY_PLATFORM_ROOT = SRC_ROOT / "overlay" / "platform"

CLI_IMPORT = re.compile(
    r"^\s*(?:from\s+stenographer\.cli|import\s+stenographer\.cli|from\s+\.{2,3}cli)\b", re.M
)


# Host-only prose and paths that must never reappear in core code or strings.
LINUX_WORDS = re.compile(
    r"systemctl|journalctl|install\.sh|/dev/uinput|usermod|wl-clipboard|xclip"
    r"|stenographer\.service"
)

# Core modules that drive a child process, a device, or the process lifecycle
# may only do so through the platform Protocols: spawning, polling,
# signalling, and raw-fd I/O are where portable-looking stdlib calls stop
# being portable (SelectSelector takes only sockets on Windows; terminate()
# there is already a kill; a console-control code fed to signal.Signals
# raises). The ASR worker also delegates to a platform transport; only helper
# backends and the native ASR implementation own process primitives.
PROCESS_MODULES = re.compile(
    r"^\s*(?:import|from)\s+(subprocess|selectors|fcntl|signal|msvcrt|multiprocessing)\b", re.M
)

RAW_FD_IO = re.compile(r"\bos\.(?:read|write|kill|waitpid|pipe)\(")

# Every daemon module inherits the original driver's platform boundary, including
# modules only imported lazily or through type-checking branches elsewhere.
DAEMON_SOURCES = tuple(
    path.relative_to(SRC_ROOT).as_posix()
    for path in sorted((SRC_ROOT / "lib" / "daemon").rglob("*.py"))
)

TRANSPORT_FREE = (
    *(
        path.relative_to(SRC_ROOT).as_posix()
        for domain in ("overlay/supervision", "lib/audio", "lib/hotkey", "lib/transcribe")
        for path in (SRC_ROOT / domain).rglob("*.py")
    ),
    *DAEMON_SOURCES,
)

BLOCKED = (
    "PySide6",
    "stenographer_desktop",
    "evdev",
    "fcntl",
    "termios",
    "grp",
    "pty",
    "pywayland",
    "Xlib",
    "stenographer.lib.platform.linux",
)

CORE = tuple(
    "stenographer."
    + path.relative_to(SRC_ROOT)
    .with_suffix("")
    .as_posix()
    .replace("/", ".")
    .removesuffix(".__init__")
    for path in sorted(SRC_ROOT.rglob("*.py"))
    if not path.is_relative_to(PLATFORM_ROOT / "linux")
    and not path.is_relative_to(OVERLAY_PLATFORM_ROOT / "linux")
    and path.name != "__main__.py"
)


def test_platform_providers_never_import_the_cli():
    """The boundary is directional: providers may use core vocabulary, never ``cli``."""

    offenders = sorted(
        str(path.relative_to(SRC_ROOT))
        for boundary in (PLATFORM_ROOT, OVERLAY_PLATFORM_ROOT)
        for path in boundary.rglob("*.py")
        if CLI_IMPORT.search(path.read_text(encoding="utf-8"))
    )
    assert not offenders, offenders


def test_core_never_hardcodes_linux_prose():
    """Labels, fix hints, and service commands come from ``HostGuidance``, not core."""

    offenders = sorted(
        str(path.relative_to(SRC_ROOT))
        for path in SRC_ROOT.rglob("*.py")
        if not path.is_relative_to(PLATFORM_ROOT / "linux")
        and not path.is_relative_to(OVERLAY_PLATFORM_ROOT / "linux")
        and LINUX_WORDS.search(path.read_text(encoding="utf-8"))
    )
    assert not offenders, offenders


def test_core_drivers_never_spawn_poll_or_signal_directly():
    """The overlay supervisor talks to its child through ``HelperTransport`` only.

    A module-level import would be caught by the blocked-import test below only
    if the module were Linux-only, and ``subprocess``/``selectors`` are not —
    they import fine on Windows and then fail at *runtime* (SelectSelector
    rejects a pipe handle, terminate() skips straight to a kill). Source text
    is therefore the honest guard. Seen to FAIL against the pre-transport
    supervisor (``import os``/``selectors``/``subprocess`` plus ``os.read``),
    and against the pre-``install_stop_handlers`` daemon (``import signal``
    for ``signal.Signals(signum).name`` in its stop handler — POSIX
    vocabulary that would raise on a Windows console-control code).
    """

    offenders = []
    for relative in TRANSPORT_FREE:
        source = (SRC_ROOT / relative).read_text(encoding="utf-8")
        offenders += [f"{relative}: import {m.group(1)}" for m in PROCESS_MODULES.finditer(source)]
        offenders += [f"{relative}: {m.group(0)}" for m in RAW_FD_IO.finditer(source)]
    assert not offenders, offenders


def test_core_imports_with_linux_only_modules_blocked():
    code = (
        "import importlib, sys\n"
        f"for name in {BLOCKED!r}:\n"
        "    sys.modules[name] = None\n"
        f"for name in {CORE!r}:\n"
        "    importlib.import_module(name)\n"
        "import stenographer.cli as cli\n"
        "from stenographer.cli.parser import build_parser\n"
        "build_parser()\n"
        "from stenographer.lib.platform.platform import Platform\n"
        "from stenographer.lib.platform.windows.provider import WindowsPlatform\n"
        "assert isinstance(WindowsPlatform(), Platform)\n"
        "leaked = [n for n, m in sys.modules.items()\n"
        "          if n.startswith('stenographer.lib.platform.linux') and m is not None]\n"
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
