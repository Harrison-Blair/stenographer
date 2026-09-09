# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify the wheel and sdist shared by release publication and its PR rehearsal."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path

from sound_asset_guard import check_sound_assets

COMPLETIONS = ("stenographer.bash", "_stenographer", "stenographer.fish")


def verify_distributions(dist_dir: Path, version: str) -> None:
    """Require the named archives and their completions, license, and sound packs."""
    wheel = dist_dir / f"stenographer-{version}-py3-none-any.whl"
    sdist = dist_dir / f"stenographer-{version}.tar.gz"
    with zipfile.ZipFile(wheel) as archive:
        names = {info.filename for info in archive.infolist() if not info.is_dir()}
    _require(names, {f"stenographer/assets/completions/{name}" for name in COMPLETIONS})
    check_sound_assets(wheel, "stenographer/assets/sounds")
    with tarfile.open(sdist, "r:gz") as archive:
        names = {info.name for info in archive.getmembers() if info.isfile()}
    root = f"stenographer-{version}"
    _require(
        names,
        {f"{root}/LICENSE"}
        | {f"{root}/src/stenographer/assets/completions/{name}" for name in COMPLETIONS},
    )
    check_sound_assets(sdist, f"{root}/src/stenographer/assets/sounds")


def _require(actual: set[str], required: set[str]) -> None:
    missing = required - actual
    if missing:
        raise ValueError(f"missing distribution files: {sorted(missing)!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("version")
    args = parser.parse_args()
    try:
        verify_distributions(args.dist_dir, args.version)
    except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
        parser.exit(1, f"distribution verification failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
