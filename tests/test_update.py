# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tarfile
from typing import Any
from unittest.mock import patch

import pytest

from stenographer.config import UpdateConfig
from stenographer.errors import UpdateError
from stenographer.update import (
    UpdateInfo,
    _parse_tag,
    _pick_release,
    check_for_update,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _release(
    tag: str,
    *,
    prerelease: bool = False,
    asset_name: str | None = None,
    sha_name: str | None = None,
) -> dict[str, Any]:
    """Build a minimal GitHub release dict for tests."""
    if asset_name is None:
        asset_name = f"stenographer-{tag.lstrip('v')}-linux-x86_64.tar.gz"
    if sha_name is None:
        sha_name = f"{asset_name}.sha256"
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "body": f"Release notes for {tag}",
        "assets": [
            {
                "name": asset_name,
                "browser_download_url": f"https://example.invalid/dl/{asset_name}",
                "size": 1024,
            },
            {
                "name": sha_name,
                "browser_download_url": f"https://example.invalid/dl/{sha_name}",
                "size": 64,
            },
        ],
    }


_DEFAULT_CFG = UpdateConfig(
    repo="Harrison-Blair/stenographer",
    channel="stable",
    base_url="https://api.github.com",
    asset_pattern="stenographer-{version}-linux-x86_64.tar.gz",
    timeout_seconds=60,
)


# ---------------------------------------------------------------------------
# Tag parsing
# ---------------------------------------------------------------------------


def test_parse_tag_strips_v() -> None:
    from packaging.version import Version

    assert _parse_tag("v0.7.0") == Version("0.7.0")


def test_parse_tag_accepts_pre_release() -> None:
    from packaging.version import Version

    assert _parse_tag("v0.7.0-rc.1") == Version("0.7.0rc1")


def test_parse_tag_invalid_raises() -> None:
    with pytest.raises(UpdateError, match="cannot parse tag"):
        _parse_tag("vnot-a-version")


# ---------------------------------------------------------------------------
# Release picking
# ---------------------------------------------------------------------------


def test_pick_release_stable_skips_pre_releases() -> None:
    from packaging.version import Version

    releases = [
        _release("v0.6.0"),
        _release("v0.7.0-rc.1", prerelease=True),
        _release("v0.7.0-rc.2", prerelease=True),
    ]
    chosen = _pick_release(releases, channel="stable", current=Version("0.5.0"))
    assert chosen["tag_name"] == "v0.6.0"


def test_pick_release_stable_with_only_pre_releases_raises() -> None:
    from packaging.version import Version

    releases = [
        _release("v0.7.0-rc.1", prerelease=True),
        _release("v0.7.0-rc.2", prerelease=True),
    ]
    with pytest.raises(UpdateError, match="no newer release"):
        _pick_release(releases, channel="stable", current=Version("0.6.0"))


def test_pick_release_latest_includes_pre_releases() -> None:
    from packaging.version import Version

    releases = [
        _release("v0.6.0"),
        _release("v0.7.0-rc.2", prerelease=True),
    ]
    chosen = _pick_release(releases, channel="latest", current=Version("0.6.0"))
    assert chosen["tag_name"] == "v0.7.0-rc.2"


def test_pick_release_picks_highest() -> None:
    from packaging.version import Version

    releases = [
        _release("v0.6.0"),
        _release("v0.7.0"),
        _release("v0.7.1"),
    ]
    chosen = _pick_release(releases, channel="stable", current=Version("0.6.0"))
    assert chosen["tag_name"] == "v0.7.1"


def test_pick_release_skips_current_and_older() -> None:
    from packaging.version import Version

    releases = [_release("v0.5.0"), _release("v0.6.0")]
    with pytest.raises(UpdateError, match="no newer release"):
        _pick_release(releases, channel="stable", current=Version("0.6.0"))


def test_pick_release_skips_unparseable_tags() -> None:
    from packaging.version import Version

    releases = [
        _release("v0.6.0"),
        _release("vnot-a-version"),
        _release("v0.7.0"),
    ]
    chosen = _pick_release(releases, channel="stable", current=Version("0.6.0"))
    assert chosen["tag_name"] == "v0.7.0"


def test_pick_release_ten_dot_zero_greater_than_nine() -> None:
    from packaging.version import Version

    releases = [_release("v0.9.0"), _release("v0.10.0")]
    chosen = _pick_release(releases, channel="stable", current=Version("0.9.0"))
    assert chosen["tag_name"] == "v0.10.0"


# ---------------------------------------------------------------------------
# check_for_update (with mocked HTTP)
# ---------------------------------------------------------------------------


def _fake_http_get_json(releases: list[dict]) -> Any:
    def _get_json(url: str, *, timeout: int) -> Any:
        if "/repos/" not in url or "/releases" not in url:
            raise UpdateError(f"unexpected url: {url}")
        return releases

    return _get_json


def test_check_for_update_returns_info_when_newer() -> None:
    releases = [_release("v0.7.0")]
    with patch("stenographer.update._http_get_json", _fake_http_get_json(releases)):
        info = check_for_update(_DEFAULT_CFG, current_version="0.6.0")
    assert isinstance(info, UpdateInfo)
    assert info.current_version == "0.6.0"
    assert info.latest_version == "0.7.0"
    assert info.tag_name == "v0.7.0"
    assert info.asset_url.endswith("stenographer-0.7.0-linux-x86_64.tar.gz")
    assert info.sha256_url.endswith("stenographer-0.7.0-linux-x86_64.tar.gz.sha256")
    assert info.prerelease is False


def test_check_for_update_up_to_date_raises() -> None:
    releases = [_release("v0.6.0")]
    with (
        patch("stenographer.update._http_get_json", _fake_http_get_json(releases)),
        pytest.raises(UpdateError, match="no newer release"),
    ):
        check_for_update(_DEFAULT_CFG, current_version="0.6.0")


def test_check_for_update_prerelease_flag_widens() -> None:
    releases = [_release("v0.7.0-rc.1", prerelease=True)]
    with patch("stenographer.update._http_get_json", _fake_http_get_json(releases)):
        info = check_for_update(_DEFAULT_CFG, current_version="0.6.0", prerelease=True)
    assert info.latest_version == "0.7.0-rc.1"
    assert info.prerelease is True


def test_check_for_update_missing_asset_raises() -> None:
    releases = [_release("v0.7.0", asset_name="wrong-name.tar.gz")]
    with (
        patch("stenographer.update._http_get_json", _fake_http_get_json(releases)),
        pytest.raises(UpdateError, match="missing the asset"),
    ):
        check_for_update(_DEFAULT_CFG, current_version="0.6.0")


def test_check_for_update_missing_sha_raises() -> None:
    releases = [_release("v0.7.0", sha_name="wrong-sha")]
    with (
        patch("stenographer.update._http_get_json", _fake_http_get_json(releases)),
        pytest.raises(UpdateError, match="missing the asset"),
    ):
        check_for_update(_DEFAULT_CFG, current_version="0.6.0")


def test_check_for_update_network_error_wrapped() -> None:
    def _raise(url: str, *, timeout: int) -> Any:
        raise UpdateError("update: network error on ...: Name or service not known")

    with (
        patch("stenographer.update._http_get_json", _raise),
        pytest.raises(UpdateError, match="network error"),
    ):
        check_for_update(_DEFAULT_CFG, current_version="0.6.0")


def test_check_for_update_invalid_current_version_raises() -> None:
    with pytest.raises(UpdateError, match="cannot parse current version"):
        check_for_update(_DEFAULT_CFG, current_version="not-a-version")


# ---------------------------------------------------------------------------
# download_update + apply_update (with tarball fixture)
# ---------------------------------------------------------------------------


def _make_tarball(tarball: pathlib.Path, *, contents: dict[str, bytes] | None = None) -> None:
    contents = contents or {
        "stenographer/stenographer": b"#!/bin/sh\necho hi\n",
        "stenographer/_internal/stenographer/__init__.py": b"__version__ = '0.7.0'\n",
    }
    with tarfile.open(tarball, "w:gz") as tf:
        for name, data in contents.items():
            import io

            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_download_update_streams_and_verifies(tmp_path: pathlib.Path) -> None:
    tarball = tmp_path / "stenographer-0.7.0.tar.gz"
    _make_tarball(tarball)
    digest = hashlib.sha256(tarball.read_bytes()).hexdigest()
    sha_text = f"{digest}  stenographer-0.7.0-linux-x86_64.tar.gz\n".encode()

    info = UpdateInfo(
        current_version="0.6.0",
        latest_version="0.7.0",
        tag_name="v0.7.0",
        asset_url="https://example.invalid/tarball",
        asset_size=tarball.stat().st_size,
        sha256_url="https://example.invalid/sha",
        release_notes="notes",
        prerelease=False,
    )

    def _dl(url: str, dest: pathlib.Path, *, timeout: int) -> None:
        dest.write_bytes(tarball.read_bytes())

    def _get(url: str, *, timeout: int) -> bytes:
        return sha_text

    from stenographer import update as update_mod

    with patch.object(update_mod, "_download_to", _dl), patch.object(update_mod, "_http_get", _get):
        out = update_mod.download_update(info, _DEFAULT_CFG, staging_dir=tmp_path)

    assert out == tmp_path / "stenographer-0.7.0.tar.gz"
    assert out.is_file()


def test_download_update_sha_mismatch_raises(tmp_path: pathlib.Path) -> None:
    tarball = tmp_path / "stenographer-0.7.0.tar.gz"
    _make_tarball(tarball)
    bad_sha = b"0" * 64 + b"  stenographer-0.7.0-linux-x86_64.tar.gz\n"
    info = UpdateInfo(
        current_version="0.6.0",
        latest_version="0.7.0",
        tag_name="v0.7.0",
        asset_url="https://example.invalid/tarball",
        asset_size=tarball.stat().st_size,
        sha256_url="https://example.invalid/sha",
        release_notes="notes",
        prerelease=False,
    )

    def _dl(url: str, dest: pathlib.Path, *, timeout: int) -> None:
        dest.write_bytes(tarball.read_bytes())

    def _get(url: str, *, timeout: int) -> bytes:
        return bad_sha

    from stenographer import update as update_mod

    with (
        patch.object(update_mod, "_download_to", _dl),
        patch.object(update_mod, "_http_get", _get),
        pytest.raises(UpdateError, match="sha256 mismatch"),
    ):
        update_mod.download_update(info, _DEFAULT_CFG, staging_dir=tmp_path)


def test_download_update_sha_star_format_accepted(tmp_path: pathlib.Path) -> None:
    tarball = tmp_path / "stenographer-0.7.0.tar.gz"
    _make_tarball(tarball)
    digest = hashlib.sha256(tarball.read_bytes()).hexdigest()
    sha_text = f"{digest} *stenographer-0.7.0-linux-x86_64.tar.gz\n".encode()
    info = UpdateInfo(
        current_version="0.6.0",
        latest_version="0.7.0",
        tag_name="v0.7.0",
        asset_url="https://example.invalid/tarball",
        asset_size=tarball.stat().st_size,
        sha256_url="https://example.invalid/sha",
        release_notes="notes",
        prerelease=False,
    )

    def _dl(url: str, dest: pathlib.Path, *, timeout: int) -> None:
        dest.write_bytes(tarball.read_bytes())

    def _get(url: str, *, timeout: int) -> bytes:
        return sha_text

    from stenographer import update as update_mod

    with patch.object(update_mod, "_download_to", _dl), patch.object(update_mod, "_http_get", _get):
        update_mod.download_update(info, _DEFAULT_CFG, staging_dir=tmp_path)


# ---------------------------------------------------------------------------
# extract_to_staging + apply_update
# ---------------------------------------------------------------------------


def test_extract_to_staging_creates_bundle(tmp_path: pathlib.Path) -> None:
    tarball = tmp_path / "t.tar.gz"
    _make_tarball(tarball)
    install_root = tmp_path / "stenographer"
    install_root.mkdir()
    from stenographer.update import extract_to_staging

    bundle = extract_to_staging(tarball, install_root)
    expected_parent = install_root.with_name(f"{install_root.name}.new.{os.getpid()}")
    assert bundle == expected_parent / "stenographer"
    assert (bundle / "stenographer").is_file()
    assert (bundle / "_internal" / "stenographer" / "__init__.py").is_file()


def test_extract_to_staging_missing_top_dir_raises(tmp_path: pathlib.Path) -> None:
    tarball = tmp_path / "t.tar.gz"
    import io

    with tarfile.open(tarball, "w:gz") as tf:
        info = tarfile.TarInfo(name="not-stenographer/foo")
        info.size = 3
        tf.addfile(info, io.BytesIO(b"bar"))
    install_root = tmp_path / "stenographer"
    install_root.mkdir()
    from stenographer.update import extract_to_staging

    with pytest.raises(UpdateError, match="missing the 'stenographer/' directory"):
        extract_to_staging(tarball, install_root)


def test_apply_update_atomic_swap(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_root = tmp_path / "stenographer"
    install_root.mkdir()
    (install_root / "old").write_text("old")
    new_bundle_parent = install_root.with_name(f"{install_root.name}.new.{os.getpid()}")
    new_bundle_parent.mkdir()
    bundle = new_bundle_parent / "stenographer"
    bundle.mkdir()
    (bundle / "stenographer").write_text("#!/bin/sh\n")
    (bundle / "_internal" / "stenographer").mkdir(parents=True)
    (bundle / "_internal" / "stenographer" / "__init__.py").write_text("__version__ = '0.7.0'\n")

    from stenographer.update import apply_update

    apply_update(bundle, install_root)
    assert (install_root / "stenographer" / "stenographer").is_file()
    assert (install_root / "stenographer" / "_internal" / "stenographer" / "__init__.py").is_file()
    assert not new_bundle_parent.exists()


def test_apply_update_sanity_check_fails(tmp_path: pathlib.Path) -> None:
    install_root = tmp_path / "stenographer"
    install_root.mkdir()
    new_bundle_parent = install_root.with_name(f"{install_root.name}.new.{os.getpid()}")
    new_bundle_parent.mkdir()
    bundle = new_bundle_parent / "stenographer"
    bundle.mkdir()
    (bundle / "stenographer").write_text("#!/bin/sh\n")
    # missing _internal/stenographer/__init__.py
    from stenographer.update import apply_update

    with pytest.raises(UpdateError, match=r"missing _internal/stenographer/__init__.py"):
        apply_update(bundle, install_root)


def test_apply_update_cross_filesystem_raises(tmp_path: pathlib.Path) -> None:
    install_root = tmp_path / "stenographer"
    install_root.mkdir()
    other_parent = tmp_path / "other"
    other_parent.mkdir()
    new_bundle_parent = other_parent / "different-name"
    new_bundle_parent.mkdir()
    bundle = new_bundle_parent / "stenographer"
    bundle.mkdir()
    (bundle / "stenographer").write_text("#!/bin/sh\n")
    (bundle / "_internal" / "stenographer").mkdir(parents=True)
    (bundle / "_internal" / "stenographer" / "__init__.py").write_text("__version__ = '0.7.0'\n")

    from stenographer.update import apply_update

    with pytest.raises(UpdateError, match="cross-filesystem"):
        apply_update(bundle, install_root)


# ---------------------------------------------------------------------------
# detect_install_root
# ---------------------------------------------------------------------------


def test_detect_install_root_finds_onedir(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stenographer.update as update_mod

    bundle = tmp_path / "stenographer"
    bundle.mkdir()
    (bundle / "_internal").mkdir()
    (bundle / "stenographer").write_text("#!/bin/sh\n")
    fake_argv0 = str(bundle / "stenographer")
    monkeypatch.setattr(update_mod.sys, "argv", [fake_argv0])
    assert update_mod.detect_install_root() == bundle


def test_detect_install_root_falls_back_to_parent_for_wheel(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stenographer.update as update_mod

    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    (site_packages / "stenographer").mkdir()
    fake_argv0 = str(site_packages / "stenographer" / "__main__.py")
    monkeypatch.setattr(update_mod.sys, "argv", [fake_argv0])
    assert update_mod.detect_install_root() == site_packages / "stenographer"


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


def test_acquire_update_lock_succeeds_then_blocks(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stenographer.update as update_mod

    monkeypatch.setattr(update_mod, "_runtime_dir", lambda: tmp_path)
    fd1 = update_mod.acquire_update_lock()
    assert fd1 is not None
    try:
        fd2 = update_mod.acquire_update_lock()
        assert fd2 is None
    finally:
        os.close(fd1)


# ---------------------------------------------------------------------------
# Stop / start daemon
# ---------------------------------------------------------------------------


def test_stop_daemon_returns_false_when_systemctl_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stenographer.update as update_mod

    monkeypatch.setattr(update_mod.shutil, "which", lambda _: None)
    assert update_mod.stop_daemon() is False


def test_start_daemon_returns_false_when_unit_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stenographer.update as update_mod

    monkeypatch.setattr(update_mod.shutil, "which", lambda _: "/usr/bin/systemctl")

    class _R:
        returncode = 1

    monkeypatch.setattr(update_mod.subprocess, "run", lambda *a, **kw: _R())
    assert update_mod.start_daemon() is False


def test_stop_daemon_returns_true_when_active(monkeypatch: pytest.MonkeyPatch) -> None:
    import stenographer.update as update_mod

    monkeypatch.setattr(update_mod.shutil, "which", lambda _: "/usr/bin/systemctl")
    calls: list[tuple] = []

    def _run(args, check=False, **kw):
        calls.append(args)

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(update_mod.subprocess, "run", _run)
    assert update_mod.stop_daemon() is True
    assert calls[0] == [
        "systemctl",
        "--user",
        "is-active",
        "--quiet",
        "stenographer.service",
    ]
    assert calls[1] == ["systemctl", "--user", "stop", "stenographer.service"]


# ---------------------------------------------------------------------------
# Sanity: not a real "github" test, but make sure json loads works
# ---------------------------------------------------------------------------


def test_release_fixture_serializes_to_json() -> None:
    releases = [_release("v0.7.0")]
    blob = json.dumps(releases)
    parsed = json.loads(blob)
    assert parsed[0]["tag_name"] == "v0.7.0"
    assert parsed[0]["assets"][0]["name"].endswith(".tar.gz")
