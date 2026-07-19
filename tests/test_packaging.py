# SPDX-License-Identifier: GPL-3.0-or-later
"""Packaging metadata tests."""

import re
import tomllib
from pathlib import Path

from stenographer import __version__
from stenographer.config import Config

ROOT = Path(__file__).parent.parent


def test_version_has_one_source_of_truth():
    pyproject = ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())

    assert "version" not in data["project"]
    assert "version" in data["project"]["dynamic"]
    assert data["tool"]["hatch"]["version"]["path"] == "src/stenographer/_version.py"
    assert __version__


def test_model_download_scripts_match_the_config_default():
    default_model = Config.defaults().asr.model
    installer = (ROOT / "packaging" / "install.sh").read_text()
    standalone = (ROOT / "scripts" / "download_model.py").read_text()

    first_choice = re.search(r'MODEL_CHOICES=\(\s*"([^|]+)\|', installer)
    script_default = re.search(r'default="([^"]+)"', standalone)

    assert first_choice is not None
    assert first_choice.group(1) == default_model
    assert script_default is not None
    assert script_default.group(1) == default_model
