# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed TOML readers with key-scoped validation errors."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from stenographer.lib.config.constants import (
    MAX_SPECTRUM_FLOOR_DBFS,
    MIN_SPECTRUM_FLOOR_DBFS,
    SpectrumFloor,
)
from stenographer.lib.config.errors import ConfigError
from stenographer.lib.contracts.constants import SPECTRUM_BANDS


@dataclass(frozen=True)
class _Reader:
    """Typed accessors over one TOML table, raising a dotted ConfigError."""

    table: dict
    path: pathlib.Path
    prefix: str

    def _err(self, key: str, reason: str) -> ConfigError:
        return ConfigError(self.path, f"{self.prefix}.{key}", reason)

    def str(self, key: str) -> str:
        value = self.table.get(key)
        if not isinstance(value, str):
            raise self._err(key, f"expected string, got {type(value).__name__}: {value!r}")
        return value

    def bool(self, key: str) -> bool:
        value = self.table.get(key)
        if not isinstance(value, bool):
            raise self._err(key, f"expected bool, got {type(value).__name__}: {value!r}")
        return value

    def optional_str(self, key: str) -> str | None:
        value = self.table.get(key)
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise self._err(key, f"expected string, got {type(value).__name__}: {value!r}")
        return value

    def _in_range(self, key: str, value: float, lo: float, hi: float) -> None:
        if not lo <= value <= hi:
            raise self._err(key, f"must be in [{lo}, {hi}], got {value}")

    def ranged_int(self, key: str, lo: int, hi: int) -> int:
        value = self.table.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise self._err(key, f"expected int, got {type(value).__name__}: {value!r}")
        self._in_range(key, value, lo, hi)
        return value

    def ranged_number(self, key: str, lo: float, hi: float) -> float:
        value = self.table.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self._err(key, f"expected number, got {type(value).__name__}: {value!r}")
        self._in_range(key, value, lo, hi)
        return float(value)

    def choice(self, key: str, allowed: frozenset[str]) -> str:
        value = self.str(key)
        if value not in allowed:
            raise self._err(key, f"must be one of {sorted(allowed)}, got {value!r}")
        return value

    def folded_choice(self, key: str, allowed: frozenset[str]) -> str:
        """A choice matched case-insensitively; the canonical lower-case name is kept."""
        raw = self.str(key)
        value = raw.casefold()
        if value not in allowed:
            raise self._err(key, f"must be one of {sorted(allowed)}, got {raw!r}")
        return value

    def spectrum_floor(self, key: str) -> SpectrumFloor:
        value = self.table.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            floor = float(value)
            if MIN_SPECTRUM_FLOOR_DBFS <= floor <= MAX_SPECTRUM_FLOOR_DBFS:
                return floor
            raise self._err(
                key,
                f"must be in [{MIN_SPECTRUM_FLOOR_DBFS}, {MAX_SPECTRUM_FLOOR_DBFS}], got {value}",
            )
        if not isinstance(value, list) or len(value) != SPECTRUM_BANDS:
            raise self._err(key, f"expected a number or exactly {SPECTRUM_BANDS} numbers")
        floors: list[float] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int | float):
                raise self._err(key, f"expected a number or exactly {SPECTRUM_BANDS} numbers")
            floor = float(item)
            if not MIN_SPECTRUM_FLOOR_DBFS <= floor <= MAX_SPECTRUM_FLOOR_DBFS:
                raise self._err(
                    key,
                    f"each band must be in "
                    f"[{MIN_SPECTRUM_FLOOR_DBFS}, {MAX_SPECTRUM_FLOOR_DBFS}], got {item}",
                )
            floors.append(floor)
        return tuple(floors)
