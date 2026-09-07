# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-user development bundle installation on Windows and macOS.

Copies both independent launchers; creates no unsupported dictation service.
The macOS application is deliberately unsigned. Signing/notarization and
Windows installer signing remain release gates, not claimed by this script.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    suffix = ".exe" if sys.platform == "win32" else ""
    for name in ("stenographer", "stenographer-ui"):
        if not (bundle / f"{name}{suffix}").is_file():
            parser.error(f"Bundle is missing {name}{suffix}")
    if sys.platform == "win32":
        destination = args.destination or Path(os.environ["LOCALAPPDATA"]) / "Stenographer"
    elif sys.platform == "darwin":
        destination = args.destination or Path.home() / "Applications" / "Stenographer.app"
    else:
        parser.error("Use the source distribution's scripts/install.sh on Linux.")
    destination = destination.resolve()
    if destination == bundle or destination in bundle.parents or bundle in destination.parents:
        parser.error("Installation and source bundle must be separate directories.")
    target = destination / "Contents" / "MacOS" if sys.platform == "darwin" else destination
    if destination.exists():
        parser.error("Destination already exists; remove the previous development bundle first.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bundle, target)
    if sys.platform == "darwin":
        info = {
            "CFBundleExecutable": "stenographer-ui",
            "CFBundleIdentifier": "org.stenographer.desktop",
            "CFBundleName": "Stenographer",
            "CFBundlePackageType": "APPL",
            "NSMicrophoneUsageDescription": (
                "Capture audio only when you explicitly start calibration."
            ),
            "NSHighResolutionCapable": True,
        }
        with (destination / "Contents" / "Info.plist").open("wb") as stream:
            plistlib.dump(info, stream)
    else:
        # Explicit arguments travel through the environment, never shell interpolation.
        env = dict(os.environ)
        env["STENOGRAPHER_INSTALL_TARGET"] = str(target / "stenographer-ui.exe")
        command = (
            "$w=New-Object -ComObject WScript.Shell;"
            "$p=[Environment]::GetFolderPath('Programs');"
            "$s=$w.CreateShortcut((Join-Path $p 'Stenographer.lnk'));"
            "$s.TargetPath=$env:STENOGRAPHER_INSTALL_TARGET;$s.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            env=env,
            check=True,
            timeout=15,
        )
    print(f"Installed development desktop and CLI: {destination}")
    print("Unsigned; interactive platform acceptance remains pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
