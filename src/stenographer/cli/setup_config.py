# SPDX-License-Identifier: GPL-3.0-or-later
"""Round-trip-safe configuration rendering and persistence for setup."""

from __future__ import annotations

import contextlib
import datetime
import os
import pathlib
import stat
import tempfile
from dataclasses import asdict, dataclass

import tomlkit
from tomlkit.exceptions import ParseError
from tomlkit.toml_document import TOMLDocument

from stenographer.config import _DEFAULT_TOML, Config, ConfigError


class ConfigPersistenceError(Exception):
    """A configuration document could not be safely persisted."""


class ConfigChangedError(ConfigPersistenceError):
    """The source document changed since setup loaded it."""


@dataclass(frozen=True)
class SaveResult:
    """The observable result of attempting to persist a reviewed config."""

    changed: bool
    path: pathlib.Path
    backup_path: pathlib.Path | None = None


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
            content = _DEFAULT_TOML
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
        for section_name in ("hotkey", "audio", "asr", "feedback"):
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


def _resolve_target(path: pathlib.Path) -> pathlib.Path:
    try:
        return path.resolve(strict=False)
    except OSError as e:
        raise ConfigPersistenceError(f"cannot resolve {path}: {e}") from e


def _read_current(path: pathlib.Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise ConfigPersistenceError(f"cannot re-read {path}: {e}") from e


def _existing_mode(path: pathlib.Path) -> int | None:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise ConfigPersistenceError(f"cannot inspect {path}: {e}") from e


def _timestamp(now: datetime.datetime | None) -> datetime.datetime:
    if now is None:
        return datetime.datetime.now(datetime.UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=datetime.UTC)
    return now.astimezone(datetime.UTC)


def _write_backup(
    target: pathlib.Path,
    content: bytes,
    mode: int | None,
    now: datetime.datetime | None,
) -> pathlib.Path:
    instant = _timestamp(now)
    while True:
        suffix = instant.strftime("%Y%m%dT%H%M%S%fZ")
        backup = target.with_name(f"{target.name}.bak-{suffix}")
        try:
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode or 0o600)
        except FileExistsError:
            instant += datetime.timedelta(microseconds=1)
            continue
        except OSError as e:
            raise ConfigPersistenceError(f"cannot create backup {backup}: {e}") from e
        break

    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            backup.chmod(mode)
    except OSError as e:
        with contextlib.suppress(OSError):
            backup.unlink()
        raise ConfigPersistenceError(f"cannot write backup {backup}: {e}") from e
    return backup


def _atomic_replace(target: pathlib.Path, content: bytes, mode: int | None) -> None:
    temporary: pathlib.Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        temporary = pathlib.Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            temporary.chmod(mode)
        os.replace(temporary, target)
        temporary = None
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as e:
        raise ConfigPersistenceError(f"cannot replace {target}: {e}") from e
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink()
