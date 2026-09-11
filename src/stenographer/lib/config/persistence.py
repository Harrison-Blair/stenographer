# SPDX-License-Identifier: GPL-3.0-or-later
"""Filesystem operations for preserved configuration saves and backups."""

from __future__ import annotations

import contextlib
import datetime
import os
import pathlib
import stat
import tempfile

from stenographer.lib.config.errors import ConfigPersistenceError


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
