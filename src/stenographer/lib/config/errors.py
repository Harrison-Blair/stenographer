# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration validation, preservation, and conflict errors."""

from __future__ import annotations

import pathlib


class ConfigPersistenceError(Exception):
    """A configuration document could not be safely persisted."""


class ConfigChangedError(ConfigPersistenceError):
    """The source document changed since setup loaded it."""


class ConfigError(Exception):
    """A validation error tied to a specific dotted config key."""

    def __init__(self, path: pathlib.Path, key: str, reason: str) -> None:
        self.path = path
        self.key = key
        self.reason = reason
        super().__init__(f"{path}: {key}: {reason}")
