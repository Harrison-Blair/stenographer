# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify the wheel and sdist shared by release publication and its PR rehearsal."""

from __future__ import annotations

import argparse
import re
import tarfile
import zipfile
from pathlib import Path

from sound_asset_guard import check_sound_assets

COMPLETIONS = ("stenographer.bash", "_stenographer", "stenographer.fish")
KEYCODES = "keycodes.toml"
CONFIG_TEMPLATE = "default_config.toml.in"


def verify_distributions(dist_dir: Path, version: str) -> None:
    """Require the archives and their completions, key table, config template, license, sounds."""
    wheel = dist_dir / f"stenographer-{version}-py3-none-any.whl"
    sdist = dist_dir / f"stenographer-{version}.tar.gz"
    wheel_metadata = f"stenographer-{version}.dist-info/METADATA"
    with zipfile.ZipFile(wheel) as archive:
        names = {info.filename for info in archive.infolist() if not info.is_dir()}
        _require(
            names,
            {f"stenographer/assets/completions/{name}" for name in COMPLETIONS}
            | {
                f"stenographer/assets/{KEYCODES}",
                f"stenographer/assets/{CONFIG_TEMPLATE}",
                "stenographer/_version.py",
                wheel_metadata,
            },
        )
        _require_metadata_version(archive.read(wheel_metadata), version, "wheel metadata")
        _require_module_version(archive.read("stenographer/_version.py"), version, "wheel")
    check_sound_assets(wheel, "stenographer/assets/sounds")
    with tarfile.open(sdist, "r:gz") as archive:
        names = {info.name for info in archive.getmembers() if info.isfile()}
        root = f"stenographer-{version}"
        version_module = f"{root}/src/stenographer/_version.py"
        package_metadata = f"{root}/PKG-INFO"
        _require(
            names,
            {
                f"{root}/LICENSE",
                f"{root}/src/stenographer/assets/{KEYCODES}",
                f"{root}/src/stenographer/assets/{CONFIG_TEMPLATE}",
                version_module,
                package_metadata,
            }
            | {f"{root}/src/stenographer/assets/completions/{name}" for name in COMPLETIONS},
        )
        metadata = archive.extractfile(package_metadata)
        module = archive.extractfile(version_module)
        if metadata is None or module is None:
            raise ValueError("distribution version files must be regular files")
        _require_metadata_version(metadata.read(), version, "source distribution metadata")
        _require_module_version(module.read(), version, "source distribution")
    check_sound_assets(sdist, f"{root}/src/stenographer/assets/sounds")


def _require(actual: set[str], required: set[str]) -> None:
    missing = required - actual
    if missing:
        raise ValueError(f"missing distribution files: {sorted(missing)!r}")


def _require_metadata_version(content: bytes, version: str, label: str) -> None:
    expected = f"Version: {version}"
    if expected not in content.decode("utf-8").splitlines():
        raise ValueError(f"{label} does not declare {expected}")


def _require_module_version(content: bytes, version: str, label: str) -> None:
    pattern = rf'^__version__ = "{re.escape(version)}"$'
    if re.search(pattern, content.decode("utf-8"), flags=re.MULTILINE) is None:
        raise ValueError(f"{label} does not contain generated version {version}")


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
