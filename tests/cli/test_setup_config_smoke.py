# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in filesystem checks for setup's durable config persistence."""

from __future__ import annotations

import datetime
import os
from dataclasses import replace

import pytest

from stenographer.cli.setup_config import ConfigChangedError, ConfigDocument
from stenographer.config import Config, resolve_config_path

pytestmark = pytest.mark.integration

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)


def test_missing_config_stays_absent_until_save(tmp_path):
    path = tmp_path / "nested" / "config.toml"

    document = ConfigDocument.load(path)

    assert document.config == Config.defaults()
    assert not path.parent.exists()
    assert not path.exists()

    result = document.save(document.config)

    assert result.changed is True
    assert result.backup_path is None
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text().startswith("# stenographer configuration.")


def test_resolve_path_can_leave_parent_absent(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "config.toml"
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(path))

    assert resolve_config_path(create_parent=False) == path
    assert not path.parent.exists()


def test_present_empty_file_is_backed_up_before_materialization(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(b"")
    document = ConfigDocument.load(path)

    result = document.save(document.config)

    assert result.backup_path is not None
    assert result.backup_path.read_bytes() == b""
    assert Config.load(path) == Config.defaults()


def test_save_creates_exact_backup_and_preserves_mode(tmp_path):
    path = tmp_path / "config.toml"
    original = b"# exact original\n[stenographer.feedback]\nvolume = 0.25 # comment\n"
    path.write_bytes(original)
    path.chmod(0o640)
    document = ConfigDocument.load(path)
    reviewed = replace(document.config, feedback=replace(document.config.feedback, mute=True))

    result = document.save(
        reviewed,
        now=datetime.datetime(2026, 8, 20, 18, 22, 33, 123456, tzinfo=datetime.UTC),
    )

    assert result.changed is True
    assert result.backup_path == tmp_path / "config.toml.bak-20260820T182233123456Z"
    assert result.backup_path.read_bytes() == original
    assert result.backup_path.stat().st_mode & 0o777 == 0o640
    assert path.stat().st_mode & 0o777 == 0o640
    assert Config.load(path) == reviewed


def test_save_never_overwrites_an_existing_backup(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[stenographer.feedback]\nmute = false\n")
    occupied = tmp_path / "config.toml.bak-20260820T182233123456Z"
    occupied.write_text("older backup")
    document = ConfigDocument.load(path)
    reviewed = replace(document.config, feedback=replace(document.config.feedback, mute=True))

    result = document.save(
        reviewed,
        now=datetime.datetime(2026, 8, 20, 18, 22, 33, 123456, tzinfo=datetime.UTC),
    )

    assert occupied.read_text() == "older backup"
    assert result.backup_path == tmp_path / "config.toml.bak-20260820T182233123457Z"


def test_save_follows_symlink_without_replacing_it(tmp_path):
    target = tmp_path / "actual.toml"
    target.write_text("[stenographer.feedback]\nmute = false\n")
    link = tmp_path / "config.toml"
    link.symlink_to(target.name)
    document = ConfigDocument.load(link)
    reviewed = replace(document.config, feedback=replace(document.config.feedback, mute=True))

    result = document.save(reviewed)

    assert link.is_symlink()
    assert result.path == target
    assert Config.load(target) == reviewed
    assert result.backup_path is not None
    assert result.backup_path.parent == link.parent
    assert result.backup_path.name.startswith("config.toml.bak-")


def test_save_refuses_concurrent_content_change(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[stenographer.feedback]\nmute = false\n")
    document = ConfigDocument.load(path)
    path.write_text("[stenographer.feedback]\nmute = true\n")

    with pytest.raises(ConfigChangedError):
        document.save(document.config)

    assert path.read_text() == "[stenographer.feedback]\nmute = true\n"
    assert not list(tmp_path.glob("*.bak-*"))


def test_unchanged_bytes_skip_write_and_backup(tmp_path):
    path = tmp_path / "config.toml"
    Config.write_default(path)
    document = ConfigDocument.load(path)
    before = path.stat().st_ino

    result = document.save(document.config)

    assert result.changed is False
    assert result.backup_path is None
    assert path.stat().st_ino == before
