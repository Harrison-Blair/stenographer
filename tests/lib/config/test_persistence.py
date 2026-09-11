# SPDX-License-Identifier: GPL-3.0-or-later
"""Real-filesystem behavior of the preserved-save primitives."""

from __future__ import annotations

import datetime
import os
import pathlib

import pytest

from stenographer.lib.config.errors import ConfigPersistenceError
from stenographer.lib.config.persistence import (
    _atomic_replace,
    _existing_mode,
    _read_current,
    _resolve_target,
    _timestamp,
    _write_backup,
)


def _symlink_loop(directory: pathlib.Path) -> pathlib.Path:
    """A path that exists as a name but cannot be stat'ed or read."""
    first = directory / "loop-a"
    second = directory / "loop-b"
    first.symlink_to(second.name)
    second.symlink_to(first.name)
    return first


def test_backup_timestamps_are_always_utc():
    naive = datetime.datetime(2026, 8, 20, 18, 22, 33, 123456)
    east = datetime.timezone(datetime.timedelta(hours=2))
    aware = datetime.datetime(2026, 8, 20, 20, 22, 33, 123456, tzinfo=east)

    assert _timestamp(naive) == naive.replace(tzinfo=datetime.UTC)
    assert _timestamp(aware) == naive.replace(tzinfo=datetime.UTC)
    assert _timestamp(None).tzinfo is datetime.UTC


@pytest.mark.skipif(os.name != "posix", reason="Windows cannot remove the working directory")
def test_a_relative_path_that_cannot_be_resolved_refuses_the_save(tmp_path, monkeypatch):
    # ``STENOGRAPHER_CONFIG`` reaches here exactly as the user wrote it, so a
    # relative path is resolved against a working directory that may be gone.
    gone = tmp_path / "gone"
    gone.mkdir()
    monkeypatch.chdir(gone)
    gone.rmdir()

    with pytest.raises(ConfigPersistenceError) as failure:
        _resolve_target(pathlib.Path("config.toml"))

    assert "cannot resolve" in str(failure.value)


def test_an_absolute_path_resolves_through_its_symlinks(tmp_path):
    target = tmp_path / "actual.toml"
    target.write_bytes(b"current")
    link = tmp_path / "config.toml"
    link.symlink_to(target.name)

    assert _resolve_target(link) == target.resolve()
    assert _resolve_target(tmp_path / "absent.toml") == (tmp_path / "absent.toml").resolve()


def test_a_missing_config_reads_as_absent_rather_than_failing(tmp_path):
    assert _read_current(tmp_path / "config.toml") is None


def test_an_unreadable_config_refuses_the_save(tmp_path):
    directory = tmp_path / "config.toml"
    directory.mkdir()

    with pytest.raises(ConfigPersistenceError) as failure:
        _read_current(directory)

    assert "cannot re-read" in str(failure.value)


def test_an_absent_target_has_no_mode_to_preserve(tmp_path):
    assert _existing_mode(tmp_path / "config.toml") is None


def test_an_uninspectable_target_refuses_the_save(tmp_path):
    with pytest.raises(ConfigPersistenceError) as failure:
        _existing_mode(_symlink_loop(tmp_path))

    assert "cannot inspect" in str(failure.value)


def test_a_backup_never_overwrites_one_taken_in_the_same_microsecond(tmp_path):
    target = tmp_path / "config.toml"
    target.write_bytes(b"current")
    instant = datetime.datetime(2026, 8, 20, 18, 22, 33, 123456, tzinfo=datetime.UTC)
    occupied = tmp_path / "config.toml.bak-20260820T182233123456Z"
    occupied.write_bytes(b"older backup")

    backup = _write_backup(target, b"current", None, instant)

    assert backup == tmp_path / "config.toml.bak-20260820T182233123457Z"
    assert backup.read_bytes() == b"current"
    assert occupied.read_bytes() == b"older backup"


def test_a_backup_that_cannot_be_created_refuses_the_save(tmp_path):
    target = tmp_path / "ghost" / "config.toml"

    with pytest.raises(ConfigPersistenceError) as failure:
        _write_backup(target, b"current", None, None)

    assert "cannot create backup" in str(failure.value)
    assert not (tmp_path / "ghost").exists()


def test_an_atomic_replace_leaves_no_temporary_behind_when_it_fails(tmp_path):
    # A directory in the target's place is the mode-independent way for the
    # rename itself to fail after the temporary file already exists.
    target = tmp_path / "config.toml"
    target.mkdir()
    (target / "occupant").write_text("unrelated", encoding="utf-8")

    with pytest.raises(ConfigPersistenceError) as failure:
        _atomic_replace(target, b"rendered", None)

    assert "cannot replace" in str(failure.value)
    assert [entry.name for entry in target.iterdir()] == ["occupant"]
    assert list(tmp_path.glob(".config.toml.*.tmp")) == []


def test_an_atomic_replace_into_a_missing_directory_refuses_the_save(tmp_path):
    with pytest.raises(ConfigPersistenceError) as failure:
        _atomic_replace(tmp_path / "ghost" / "config.toml", b"rendered", None)

    assert "cannot replace" in str(failure.value)
    assert not (tmp_path / "ghost").exists()


@pytest.mark.parametrize("mode", [None, 0o640])
def test_an_atomic_replace_preserves_content_and_leaves_no_temporary(tmp_path, mode):
    target = tmp_path / "config.toml"
    target.write_bytes(b"old")

    _atomic_replace(target, b"new content", mode)

    assert target.read_bytes() == b"new content"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_an_atomic_replace_preserves_the_requested_mode(tmp_path):
    target = tmp_path / "config.toml"
    target.write_bytes(b"old")

    _atomic_replace(target, b"new content", 0o640)

    assert target.stat().st_mode & 0o777 == 0o640
