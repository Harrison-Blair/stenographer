# SPDX-License-Identifier: GPL-3.0-or-later
"""Packaging metadata tests."""

import tomllib
from pathlib import Path

from stenographer import __version__

ROOT = Path(__file__).parent.parent


def test_version_has_one_source_of_truth():
    pyproject = ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())

    assert "version" not in data["project"]
    assert "version" in data["project"]["dynamic"]
    assert data["tool"]["hatch"]["version"]["path"] == "src/stenographer/_version.py"
    assert __version__
