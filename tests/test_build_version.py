# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for generation of release build metadata."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_version import BuildVersionError, render_version_file


def test_render_version_file_emits_the_release_version() -> None:
    assert '__version__ = "1.2.3"' in render_version_file("1.2.3")


@pytest.mark.parametrize("version", ["v1.2.3", "1.2", "1.2.3-rc1", "01.2.3"])
def test_render_version_file_rejects_non_release_versions(version: str) -> None:
    with pytest.raises(BuildVersionError, match=r"plain X\.Y\.Z"):
        render_version_file(version)
