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
    assert re.fullmatch(r"\d+\.\d+\.\d+-dev", __version__)


def test_cli_reports_dev_version(capsys) -> None:
    import pytest

    from stenographer._parser import build_parser

    with pytest.raises(SystemExit, match="0"):
        build_parser().parse_args(["--version"])
    reported = capsys.readouterr().out.strip()
    assert re.fullmatch(r"stenographer \d+\.\d+\.\d+-dev", reported)


def test_release_workflow_strips_dev_commits_and_tags_stable_version() -> None:
    import yaml

    raw = (ROOT / ".github/workflows/release.yml").read_text()
    workflow = yaml.safe_load(raw)  # also fails loudly on malformed YAML

    steps = workflow["jobs"]["build-release"]["steps"]
    scripts = "\n".join(step.get("run", "") for step in steps)

    # Refuses to release unless the repo carries an X.Y.Z-dev version ...
    assert r"[0-9]+\.[0-9]+\.[0-9]+-dev$" in scripts
    # ... strips the -dev suffix before building the released artifacts ...
    assert "version=${dev_version%-dev}" in scripts
    # ... commits and tags that stable version so the release tag's source
    # matches the released binary (never self-identifying as -dev) ...
    assert "git commit" in scripts
    assert 'git tag -a "v${VERSION}"' in scripts
    assert 'git push origin "refs/tags/v${VERSION}"' in scripts
    # ... and verifies the built binary reports the stable version.
    assert 'test "${reported}" = "stenographer ${VERSION}"' in scripts


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


def test_standalone_bundle_collects_silero_vad_model() -> None:
    spec = (ROOT / "packaging" / "stenographer.spec").read_text()

    assert "collect_data_files" in spec
    assert '"faster_whisper", includes=["assets/*.onnx"]' in spec


def test_release_installer_verifies_download_integrity() -> None:
    installer = (ROOT / "packaging" / "install.sh").read_text()

    # Downloads must abort on HTTP errors (--fail, so an error page is never
    # saved as the binary) and follow GitHub's release redirects (--location).
    assert "curl --fail --location" in installer
    # The release archive is only trusted after its SHA-256 is checked, and a
    # mismatch must stop the install rather than proceed.
    assert "sha256sum -c" in installer
    assert "SHA-256 verification failed" in installer
