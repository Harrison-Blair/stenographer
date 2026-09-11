# SPDX-License-Identifier: GPL-3.0-or-later
"""Round-trip configuration document, rendering, and conflict-aware saves."""

from __future__ import annotations

import datetime
import pathlib
from dataclasses import asdict, dataclass

import tomlkit
from tomlkit.exceptions import ParseError
from tomlkit.toml_document import TOMLDocument

from stenographer.lib.config.defaults import default_toml
from stenographer.lib.config.errors import ConfigChangedError, ConfigError, ConfigPersistenceError
from stenographer.lib.config.models import Config
from stenographer.lib.config.persistence import (
    _atomic_replace,
    _existing_mode,
    _read_current,
    _resolve_target,
    _write_backup,
)
from stenographer.lib.config.save_result import SaveResult


@dataclass(frozen=True)
class ConfigDocument:
    """One editable config plus the source snapshot used for safe persistence."""

    path: pathlib.Path
    config: Config
    _document: TOMLDocument
    _source_bytes: bytes | None
    _target: pathlib.Path

    @classmethod
    def load(cls, path: pathlib.Path) -> ConfigDocument:
        """Load an existing config, or annotated defaults when it is absent."""

        path = pathlib.Path(path)
        target = _resolve_target(path)
        try:
            source = path.read_bytes()
        except FileNotFoundError:
            source = None
            content = default_toml()
        except OSError as e:
            raise ConfigError(path, "<file>", f"cannot read: {e}") from e
        else:
            try:
                content = source.decode("utf-8")
            except UnicodeDecodeError as e:
                raise ConfigError(path, "<file>", f"cannot decode as UTF-8: {e}") from e

        return cls._from_content(path, content, source, target)

    @classmethod
    def loads(
        cls,
        content: str,
        path: pathlib.Path = pathlib.Path("<memory>"),
    ) -> ConfigDocument:
        """Build a round-trip document entirely in memory."""

        path = pathlib.Path(path)
        return cls._from_content(path, content, content.encode("utf-8"), _resolve_target(path))

    @classmethod
    def defaults(cls, path: pathlib.Path) -> ConfigDocument:
        """Stage the annotated default template over whatever *path* holds now.

        The document is the template, so a save writes exactly it; the source
        snapshot is the current file, so existing bytes are still backed up and
        an already-default file is left untouched. Nothing parses that current
        content — this is the one path that must work against a config too
        broken to load.
        """

        path = pathlib.Path(path)
        return cls._from_content(path, default_toml(), _read_current(path), _resolve_target(path))

    @classmethod
    def _from_content(
        cls,
        path: pathlib.Path,
        content: str,
        source: bytes | None,
        target: pathlib.Path,
    ) -> ConfigDocument:
        config = Config.loads(content, path)
        # Production validation above gives stable, key-scoped errors. This parse
        # should therefore only fail if tomlkit and tomllib disagree on valid TOML.
        try:
            document = tomlkit.parse(content)
        except ParseError as e:
            raise ConfigError(path, "<toml>", f"cannot preserve TOML document: {e}") from e
        return cls(path, config, document, source, target)

    def render(self, config: Config) -> str:
        """Materialize every known key without disturbing unrelated TOML."""

        document = tomlkit.parse(tomlkit.dumps(self._document))
        root = document.get("stenographer")
        if root is None:
            root = tomlkit.table()
            document["stenographer"] = root

        values = asdict(config)
        for section_name in values:
            section = root.get(section_name)
            if section is None:
                section = tomlkit.table()
                root[section_name] = section
            for key, value in values[section_name].items():
                rendered_value = (
                    "" if value is None else list(value) if isinstance(value, tuple) else value
                )
                if key not in section or section[key] != rendered_value:
                    section[key] = rendered_value

        rendered = tomlkit.dumps(document)
        reloaded = Config.loads(rendered, self.path)
        if reloaded != config:
            raise ConfigPersistenceError(
                "rendered configuration does not match the reviewed configuration"
            )
        return rendered

    def save(
        self,
        config: Config,
        *,
        now: datetime.datetime | None = None,
    ) -> SaveResult:
        """Validate, back up, and atomically persist a reviewed configuration."""

        rendered = self.render(config).encode("utf-8")
        target = _resolve_target(self.path)
        if target != self._target:
            raise ConfigChangedError(f"{self.path} changed while setup was running")

        current = _read_current(self.path)
        if current != self._source_bytes:
            raise ConfigChangedError(f"{self.path} changed while setup was running")
        if _resolve_target(self.path) != target:
            raise ConfigChangedError(f"{self.path} changed while setup was running")
        if current == rendered:
            return SaveResult(False, target)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ConfigPersistenceError(f"cannot create {target.parent}: {e}") from e
        mode = _existing_mode(target)
        backup = None
        if current is not None:
            backup = _write_backup(self.path, current, mode, now)
        _atomic_replace(target, rendered, mode)
        return SaveResult(True, target, backup)
