# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail closed unless a tree or archive contains exactly the bundled sound packs."""

from __future__ import annotations

import argparse
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

BUNDLED_PACKS = ("legacy", "warm-desk", "soft-electronic", "minimal-ui")
CUE_NAMES = ("record_start", "record_stop", "delivered", "error")
EXPECTED_PATHS = tuple(f"{pack}/{cue}.wav" for pack in BUNDLED_PACKS for cue in CUE_NAMES)


class SoundAssetGuardError(ValueError):
    """A package boundary has missing, extra, or unsafe sound assets."""


def _relative_archive_path(name: str, prefix: str) -> str | None:
    path = PurePosixPath(name)
    normalized_prefix = PurePosixPath(prefix) if prefix else PurePosixPath()
    try:
        relative = path.relative_to(normalized_prefix)
    except ValueError:
        return None
    if not relative.parts:
        return None
    return relative.as_posix()


def _directory_entries(root: Path) -> list[str]:
    if not root.is_dir():
        raise SoundAssetGuardError(f"sound asset directory does not exist: {root}")
    if root.is_symlink():
        raise SoundAssetGuardError(f"sound asset directory must not be a symlink: {root}")

    entries: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise SoundAssetGuardError(f"bundled sound assets must not be symlinks: {relative}")
        elif path.is_file():
            entries.append(relative)
    directories = {path.name for path in root.iterdir() if path.is_dir() and not path.is_symlink()}
    if directories != set(BUNDLED_PACKS):
        raise SoundAssetGuardError(
            f"bundled pack directories differ: expected {list(BUNDLED_PACKS)!r}, "
            f"found {sorted(directories)!r}"
        )
    return entries


def _zip_entries(path: Path, prefix: str) -> list[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            entries: list[str] = []
            for info in archive.infolist():
                relative = _relative_archive_path(info.filename, prefix)
                if relative is None or info.is_dir():
                    continue
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise SoundAssetGuardError(
                        f"sound assets in ZIP archives must not be symlinks: {relative}"
                    )
                entries.append(relative)
            return entries
    except (OSError, zipfile.BadZipFile) as error:
        raise SoundAssetGuardError(f"cannot inspect ZIP archive {path}: {error}") from error


def _tar_entries(path: Path, prefix: str) -> list[str]:
    try:
        with tarfile.open(path, "r:*") as archive:
            entries: list[str] = []
            for member in archive.getmembers():
                relative = _relative_archive_path(member.name, prefix)
                if relative is None or member.isdir():
                    continue
                if not member.isfile():
                    raise SoundAssetGuardError(
                        f"sound assets in tar archives must be regular files: {relative}"
                    )
                entries.append(relative)
            return entries
    except (OSError, tarfile.TarError) as error:
        raise SoundAssetGuardError(f"cannot inspect tar archive {path}: {error}") from error


def sound_asset_entries(location: Path, prefix: str = "") -> list[str]:
    """Return sound-root-relative entries from a directory, wheel/ZIP, or tar archive."""

    if location.is_dir():
        if prefix:
            raise SoundAssetGuardError("--prefix applies only to archives")
        return _directory_entries(location)
    try:
        if zipfile.is_zipfile(location):
            return _zip_entries(location, prefix)
        if tarfile.is_tarfile(location):
            return _tar_entries(location, prefix)
    except OSError as error:
        raise SoundAssetGuardError(
            f"cannot inspect package boundary {location}: {error}"
        ) from error
    raise SoundAssetGuardError(f"unsupported or missing package boundary: {location}")


def check_sound_assets(location: Path, prefix: str = "") -> None:
    """Require all 16 expected WAVs, no duplicates, and no other nested entries."""

    actual = sorted(sound_asset_entries(location, prefix))
    expected = sorted(EXPECTED_PATHS)
    if actual != expected:
        missing = sorted(set(expected).difference(actual))
        extra = sorted(set(actual).difference(expected))
        duplicates = sorted({entry for entry in actual if actual.count(entry) > 1})
        details = []
        if missing:
            details.append(f"missing={missing!r}")
        if extra:
            details.append(f"extra={extra!r}")
        if duplicates:
            details.append(f"duplicates={duplicates!r}")
        raise SoundAssetGuardError("bundled sound asset set differs: " + "; ".join(details))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("location", type=Path, help="sound directory, wheel/ZIP, or tar archive")
    parser.add_argument(
        "--prefix",
        default="",
        help="archive path whose contents are the sound root",
    )
    args = parser.parse_args()
    try:
        check_sound_assets(args.location, args.prefix)
    except SoundAssetGuardError as error:
        parser.exit(1, f"sound asset guard failed: {error}\n")
    print(f"sound asset guard passed: {len(EXPECTED_PATHS)} WAVs in {args.location}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
