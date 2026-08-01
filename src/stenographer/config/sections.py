# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading one table: the typed accessors (`_Section`) each validator uses, the
`null`-rewrite regex, and the recursive defaults-merge."""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

from stenographer.config.schema import ConfigError

_NULL_VALUE_RE = re.compile(r'(?<=\s=\s)null(?=[^\w"]|\Z)', re.MULTILINE)


@dataclass(frozen=True)
class _Section:
    """A config table bundled with its dotted-path prefix and source file.

    Bundles the ``(table, dotted-prefix, path)`` triple every validator
    needs, so each call passes only the key and the dotted path is derived
    once here (``prefix.key``) rather than duplicated at every call site.
    """

    table: dict
    prefix: str
    path: pathlib.Path

    def _dotted(self, key: str) -> str:
        return f"{self.prefix}.{key}"

    def str(self, key: str) -> str:
        value = self.table.get(key)
        if not isinstance(value, str):
            raise ConfigError(
                self.path,
                self._dotted(key),
                f"expected string, got {type(value).__name__}: {value!r}",
            )
        return value

    def int(self, key: str) -> int:
        value = self.table.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(
                self.path,
                self._dotted(key),
                f"expected int, got {type(value).__name__}: {value!r}",
            )
        return value

    def number(self, key: str) -> float:
        value = self.table.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(
                self.path,
                self._dotted(key),
                f"expected number, got {type(value).__name__}: {value!r}",
            )
        return float(value)

    def bool(self, key: str) -> bool:
        value = self.table.get(key)
        if not isinstance(value, bool):
            raise ConfigError(
                self.path,
                self._dotted(key),
                f"expected bool, got {type(value).__name__}: {value!r}",
            )
        return value

    def optional_int(self, key: str) -> int | None:
        value = self.table.get(key)
        if value is None or value == "":  # `key = null` is rewritten to "" at load
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(
                self.path,
                self._dotted(key),
                f"expected int or null, got {type(value).__name__}: {value!r}",
            )
        return value

    def optional_str(self, key: str) -> str | None:
        value = self.table.get(key)
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ConfigError(
                self.path,
                self._dotted(key),
                f"expected string or null, got {type(value).__name__}: {value!r}",
            )
        return value

    def optional_path(self, key: str) -> str | None:
        value = self.optional_str(key)
        if value is not None and not pathlib.Path(value).exists():
            raise ConfigError(self.path, self._dotted(key), f"path does not exist: {value}")
        return value


def _merge(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result
