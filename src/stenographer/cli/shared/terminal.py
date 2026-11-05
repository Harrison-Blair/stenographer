# SPDX-License-Identifier: GPL-3.0-or-later
"""The interactive-terminal frame shared by ``setup`` and ``sounds``.

Stream defaulting, the TTY gate, the config-document load ladder, save
reporting, and the service-restart prompt live here so both commands share one
implementation. The line-building and gate decisions are pure; the console
itself only owns the three streams it was handed.
"""

from __future__ import annotations

import os
import sys
from typing import TextIO

from stenographer.cli.shared.console import Console
from stenographer.lib.config.document import ConfigDocument, SaveResult
from stenographer.lib.config.errors import ConfigError, ConfigPersistenceError


def open_console(
    stdin: TextIO | None,
    stdout: TextIO | None,
    stderr: TextIO | None,
) -> Console:
    """Build a console, falling back to the process streams for anything omitted."""

    return Console(
        sys.stdin if stdin is None else stdin,
        sys.stdout if stdout is None else stdout,
        sys.stderr if stderr is None else stderr,
    )


def require_interactive(console: Console, message: str, *, when: bool = True) -> int | None:
    """Report *message* and return the exit code when the gate applies and fails."""

    if not when or console.interactive:
        return None
    console.error(message)
    return 2


def custom_config_selected() -> bool:
    """Whether ``STENOGRAPHER_CONFIG`` points the command at a non-standard file."""

    return bool(os.environ.get("STENOGRAPHER_CONFIG"))


def load_document(
    console: Console,
    *,
    interrupt_message: str,
    blank_line_before_interrupt: bool,
) -> ConfigDocument | int:
    """Load the active configuration document, or return the exit code to report."""

    from stenographer.lib.config.paths import resolve_config_path

    path = resolve_config_path(create_parent=False)
    try:
        return ConfigDocument.load(path)
    except ConfigError as exc:
        console.error(str(exc))
        return 78
    except ConfigPersistenceError as exc:
        console.error(str(exc))
        return 1
    except KeyboardInterrupt:
        if blank_line_before_interrupt:
            console.write()
        console.error(interrupt_message)
        return 130


def report_save(
    console: Console,
    result: SaveResult,
    *,
    saved_prefix: str,
    unchanged_message: str,
) -> None:
    """Write the save report for *result*."""

    if not result.changed:
        console.write(unchanged_message)
        return
    console.write(f"{saved_prefix} {result.path}")
    if result.backup_path is not None:
        console.write(f"Backup: {result.backup_path}")


def parse_bool(text: str, current: bool) -> bool:
    """Parse yes/no with Enter retaining the current value."""

    value = text.strip().casefold()
    if not value:
        return current
    if value in {"y", "yes", "true", "on", "1"}:
        return True
    if value in {"n", "no", "false", "off", "0"}:
        return False
    raise ValueError("enter yes or no")


def ask_yes_no(console: Console, prompt: str, *, default: bool) -> bool:
    """Prompt until the answer parses, marking the default in the prompt."""

    marker = "Y/n" if default else "y/N"
    return console.validated(f"{prompt} [{marker}]: ", lambda text: parse_bool(text, default))


def restart_service(console: Console) -> bool:
    """Restart the platform service, reporting the outcome."""

    from stenographer.lib.platform import current_platform

    plat = current_platform()
    ok, detail = plat.restart_service()
    name = plat.guidance().service_name
    if not ok:
        console.error(f"could not restart {name}: {detail}")
        return False
    console.write(f"Restarted {name}.")
    return True
