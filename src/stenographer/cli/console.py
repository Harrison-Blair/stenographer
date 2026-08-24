# SPDX-License-Identifier: GPL-3.0-or-later
"""The interactive-terminal frame shared by ``setup`` and ``sounds``.

Stream defaulting, the TTY gate, the config-document load ladder, save
reporting, and the service-restart prompt live here so both commands share one
implementation. The line-building and gate decisions are pure; the console
itself only owns the three streams it was handed.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import sys
from collections.abc import Callable
from typing import TextIO, TypeVar

from stenographer.cli.setup_config import ConfigDocument, ConfigPersistenceError, SaveResult
from stenographer.config import ConfigError

T = TypeVar("T")

#: Exit code for a command that needs a terminal and did not get one.
NOT_A_TERMINAL = 2
#: Exit code for a rejected configuration.
CONFIG_REJECTED = 78
#: Exit code for an operational failure.
FAILED = 1
#: Exit code for an interrupted interactive session.
INTERRUPTED = 130


@dataclasses.dataclass
class Console:
    """Prompt/echo helper bound to one set of streams."""

    stdin: TextIO
    stdout: TextIO
    stderr: TextIO

    @property
    def interactive(self) -> bool:
        """Whether both the input and output ends are a terminal."""

        return streams_interactive(self.stdin, self.stdout)

    def write(self, message: str = "") -> None:
        print(message, file=self.stdout)

    def error(self, message: str) -> None:
        print(f"stenographer: {message}", file=self.stderr)

    def ask(self, prompt: str) -> str:
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        if line == "":
            raise EOFError
        return line.rstrip("\r\n")

    def validated(self, prompt: str, parser: Callable[[str], T]) -> T:
        while True:
            try:
                return parser(self.ask(prompt))
            except ValueError as exc:
                self.error(str(exc))


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


def streams_interactive(stdin: TextIO, stdout: TextIO) -> bool:
    """Both ends must be a terminal before a command may prompt."""

    return bool(stdin.isatty() and stdout.isatty())


def require_interactive(console: Console, message: str, *, when: bool = True) -> int | None:
    """Report *message* and return the exit code when the gate applies and fails."""

    if not when or console.interactive:
        return None
    console.error(message)
    return NOT_A_TERMINAL


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

    from stenographer.config import resolve_config_path

    path = resolve_config_path(create_parent=False)
    try:
        return ConfigDocument.load(path)
    except ConfigError as exc:
        console.error(str(exc))
        return CONFIG_REJECTED
    except ConfigPersistenceError as exc:
        console.error(str(exc))
        return FAILED
    except KeyboardInterrupt:
        if blank_line_before_interrupt:
            console.write()
        console.error(interrupt_message)
        return INTERRUPTED


def save_report_lines(
    *,
    changed: bool,
    path: pathlib.PurePath,
    backup_path: pathlib.PurePath | None,
    saved_prefix: str,
    unchanged_message: str,
) -> list[str]:
    """Render what a save attempt did: the saved path, any backup, or no write."""

    if not changed:
        return [unchanged_message]
    lines = [f"{saved_prefix} {path}"]
    if backup_path is not None:
        lines.append(f"Backup: {backup_path}")
    return lines


def report_save(
    console: Console,
    result: SaveResult,
    *,
    saved_prefix: str,
    unchanged_message: str,
) -> None:
    """Write the save report for *result*."""

    for line in save_report_lines(
        changed=result.changed,
        path=result.path,
        backup_path=result.backup_path,
        saved_prefix=saved_prefix,
        unchanged_message=unchanged_message,
    ):
        console.write(line)


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

    from stenographer.platform import current_platform

    plat = current_platform()
    ok, detail = plat.restart_service()
    name = plat.guidance().service_name
    if not ok:
        console.error(f"could not restart {name}: {detail}")
        return False
    console.write(f"Restarted {name}.")
    return True
