# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the package version module for an official release build."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_VERSION_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


class BuildVersionError(ValueError):
    """A requested build version is not a stable release version."""


def render_version_file(version: str) -> str:
    """Render a generated module after strict stable-version validation."""

    if _VERSION_RE.fullmatch(version) is None:
        raise BuildVersionError(f"build version {version!r} must be plain X.Y.Z")
    return (
        "# SPDX-License-Identifier: GPL-3.0-or-later\n"
        '"""Generated release build version; do not edit by hand."""\n\n'
        f'__version__ = "{version}"\n'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        content = render_version_file(args.version)
        args.output.write_text(content, encoding="utf-8")
    except (BuildVersionError, OSError) as error:
        raise SystemExit(f"build version generation failed: {error}") from error
    print(f"generated {args.output} for {args.version}")


if __name__ == "__main__":
    main()
