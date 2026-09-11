# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure packaging-boundary tests for the bundled sound asset guard."""

from __future__ import annotations

import hashlib
import io
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from sound_asset_guard import EXPECTED_PATHS, SoundAssetGuardError, check_sound_assets
from verify_distributions import COMPLETIONS, verify_distributions

_LEGACY_SHA256 = {
    "delivered.wav": "3cdd176f8914da7c3d9d298ea2c4793d4d43bf3ce3e7c6cdf1bbe749a0f2f5c9",
    "error.wav": "1e3694e12197380d2c61252dd9fb0e4c320b6c0a520cecad31560bea2042e24b",
    "record_start.wav": "1e89f6e90125b9c400fffe601ad8e14475d2623d655c8d8471659596838154e2",
    "record_stop.wav": "4651f22fd28bf74648078dce862c61d49c26bac2a773f98e7c8e97db123a4148",
}


def _write_tree(root: Path) -> None:
    for relative in EXPECTED_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"RIFFtest")


def test_checked_in_sound_tree_has_exactly_four_complete_packs() -> None:
    root = Path(__file__).resolve().parents[1] / "src/stenographer/assets/sounds"

    check_sound_assets(root)


def test_legacy_pack_preserves_the_original_wav_bytes() -> None:
    root = Path(__file__).resolve().parents[1] / "src/stenographer/assets/sounds/legacy"

    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.glob("*.wav")
    }
    assert actual == _LEGACY_SHA256


def test_directory_guard_rejects_missing_and_extra_assets(tmp_path: Path) -> None:
    root = tmp_path / "sounds"
    _write_tree(root)
    (root / EXPECTED_PATHS[0]).unlink()
    (root / "legacy/extra.wav").write_bytes(b"RIFFtest")

    with pytest.raises(SoundAssetGuardError, match=r"missing=.*extra="):
        check_sound_assets(root)


def test_directory_guard_rejects_symlinked_assets(tmp_path: Path) -> None:
    root = tmp_path / "sounds"
    _write_tree(root)
    (root / EXPECTED_PATHS[0]).unlink()
    try:
        (root / EXPECTED_PATHS[0]).symlink_to(root / EXPECTED_PATHS[1])
    except OSError as exc:  # unprivileged Windows has no symlink permission
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(SoundAssetGuardError, match="must not be symlinks"):
        check_sound_assets(root)


def test_wheel_guard_accepts_only_the_exact_prefixed_asset_set(tmp_path: Path) -> None:
    wheel = tmp_path / "stenographer.whl"
    prefix = "stenographer/assets/sounds"
    with zipfile.ZipFile(wheel, "w") as archive:
        for relative in EXPECTED_PATHS:
            archive.writestr(f"{prefix}/{relative}", b"RIFFtest")
        archive.writestr("stenographer/assets/icons/stenographer.png", b"PNG")

    check_sound_assets(wheel, prefix)


def test_archive_guard_rejects_nonregular_expected_sound_entry(tmp_path: Path) -> None:
    archive_path = tmp_path / "stenographer.tar.gz"
    prefix = "stenographer/_internal/stenographer/assets/sounds"
    with tarfile.open(archive_path, "w:gz") as archive:
        for relative in EXPECTED_PATHS:
            if relative == EXPECTED_PATHS[0]:
                continue
            info = tarfile.TarInfo(f"{prefix}/{relative}")
            info.size = len(b"RIFFtest")
            archive.addfile(info, io.BytesIO(b"RIFFtest"))
        link = tarfile.TarInfo(f"{prefix}/{EXPECTED_PATHS[0]}")
        link.type = tarfile.SYMTYPE
        link.linkname = "record_start.wav"
        archive.addfile(link)

    with pytest.raises(SoundAssetGuardError, match="must be regular files"):
        check_sound_assets(archive_path, prefix)


def test_wheel_guard_rejects_symlinked_expected_sound_entry(tmp_path: Path) -> None:
    wheel = tmp_path / "stenographer.whl"
    prefix = "stenographer/assets/sounds"
    with zipfile.ZipFile(wheel, "w") as archive:
        for relative in EXPECTED_PATHS[1:]:
            archive.writestr(f"{prefix}/{relative}", b"RIFFtest")
        link = zipfile.ZipInfo(f"{prefix}/{EXPECTED_PATHS[0]}")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "record_start.wav")

    with pytest.raises(SoundAssetGuardError, match="must not be symlinks"):
        check_sound_assets(wheel, prefix)


@pytest.mark.parametrize(
    "missing", [None, "wheel_completion", "sdist_completion", "license", "sound", "archive"]
)
def test_distribution_contract(tmp_path: Path, missing: str | None) -> None:
    version = "1.2.3"
    wheel_names = [f"stenographer/assets/completions/{name}" for name in COMPLETIONS]
    wheel_names.append("stenographer/assets/keycodes.toml")
    wheel_names.append("stenographer/assets/default_config.toml.in")
    wheel_names += [f"stenographer/assets/sounds/{name}" for name in EXPECTED_PATHS]
    sdist_names = [f"stenographer-{version}/src/{name}" for name in wheel_names]
    sdist_names.append(f"stenographer-{version}/LICENSE")
    if missing == "wheel_completion":
        wheel_names.pop(0)
    elif missing == "sdist_completion":
        sdist_names.pop(0)
    elif missing == "license":
        sdist_names.pop()
    elif missing == "sound":
        wheel_names.pop()
    with zipfile.ZipFile(tmp_path / f"stenographer-{version}-py3-none-any.whl", "w") as archive:
        for name in wheel_names:
            archive.writestr(name, b"fixture")
    with tarfile.open(tmp_path / f"stenographer-{version}.tar.gz", "w:gz") as archive:
        for name in sdist_names:
            info = tarfile.TarInfo(name)
            info.size = 7
            archive.addfile(info, io.BytesIO(b"fixture"))
    if missing is None:
        verify_distributions(tmp_path, version)
    else:
        with pytest.raises((ValueError, OSError)):
            verify_distributions(tmp_path, "9.9.9" if missing == "archive" else version)
