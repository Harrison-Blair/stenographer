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


def test_local_version_retains_dev_suffix() -> None:
    assert __version__ == "0.9.4-dev"


def test_cli_reports_exact_dev_version(capsys) -> None:
    import pytest

    from stenographer._parser import build_parser

    with pytest.raises(SystemExit, match="0"):
        build_parser().parse_args(["--version"])
    assert capsys.readouterr().out.strip() == "stenographer 0.9.4-dev"


def test_release_workflow_strips_dev_and_verifies_binary() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    assert "X.Y.Z-dev" in workflow
    assert "version=${dev_version%-dev}" in workflow
    assert 'test "${reported}" = "stenographer ${VERSION}"' in workflow


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


def test_release_installer_shows_download_and_phase_progress() -> None:
    installer = (ROOT / "packaging" / "install.sh").read_text()

    assert "curl --fail --location --show-error --progress-bar" in installer
    assert "wget --progress=bar:force:noscroll" in installer
    assert 'info "[1/6] Checking system dependencies ..."' in installer
    assert 'info "[6/6] Setting up the background service ..."' in installer
    assert 'ok "binary archive downloaded"' in installer
    assert 'ok "bundle files installed"' in installer
