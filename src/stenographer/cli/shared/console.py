# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive console bound to caller-owned streams."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import TextIO, TypeVar

T = TypeVar("T")


@dataclasses.dataclass
class Console:
    """Prompt/echo helper bound to one set of streams."""

    stdin: TextIO
    stdout: TextIO
    stderr: TextIO

    @property
    def interactive(self) -> bool:
        """Whether both the input and output ends are a terminal."""

        return bool(self.stdin.isatty() and self.stdout.isatty())

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
