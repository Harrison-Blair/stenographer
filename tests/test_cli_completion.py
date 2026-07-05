# SPDX-License-Identifier: GPL-3.0-or-later
"""Bash tab-completion via argcomplete's env-var protocol (no bash needed)."""

import os
import subprocess
import sys

import pytest

pytest.importorskip("argcomplete")

SUBCOMMANDS = {"run", "transcribe", "dictate", "model", "update", "doctor", "devices"}


def _complete(comp_line: str, tmp_path) -> list[str]:
    out_file = tmp_path / "out"
    env = {
        **os.environ,
        "_ARGCOMPLETE": "1",
        "_ARGCOMPLETE_SHELL": "bash",
        "_ARGCOMPLETE_IFS": "\013",
        "COMP_LINE": comp_line,
        "COMP_POINT": str(len(comp_line)),
        "_ARGCOMPLETE_STDOUT_FILENAME": str(out_file),
    }
    subprocess.run(
        [sys.executable, "-m", "stenographer.cli"],
        env=env,
        timeout=10,
        check=False,
    )
    # argcomplete appends a trailing space to a sole completion
    return [c.strip() for c in out_file.read_text().split("\013")]


def test_completes_partial_subcommand(tmp_path):
    assert _complete("stenographer tr", tmp_path) == ["transcribe"]


def test_completes_all_subcommands(tmp_path):
    assert set(_complete("stenographer ", tmp_path)) >= SUBCOMMANDS


def test_completes_update_flags(tmp_path):
    flags = set(_complete("stenographer update --", tmp_path))
    assert {"--check", "--yes", "--no-restart", "--prerelease", "--repo"} <= flags
