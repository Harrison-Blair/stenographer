# SPDX-License-Identifier: GPL-3.0-or-later
"""Packaging metadata tests."""

import tomllib
from pathlib import Path


def test_pyproject_version_is_0_8_8():
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    assert data["project"]["version"] == "0.8.8"
