# SPDX-License-Identifier: GPL-3.0-or-later
"""The integration opt-in in :mod:`tests.conftest` guarding itself.

Each case runs real pytest on a probe file with the suite's conftest loaded, so
the probe stands in for a test that would record audio or dial a server. The
probe body leaves a file behind: a gate that fails to stop it is seen here
without any real integration test having run.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

PROBE = """
from pathlib import Path

import pytest

{mark}
def test_probe():
    Path(__file__).with_name("body-ran").touch()
"""


def _run_probe(tmp_path: Path, mark: str, opt_in: str | None) -> tuple[bool, str]:
    """Run the probe and report whether its body ran, with pytest's output."""

    (tmp_path / "test_probe.py").write_text(PROBE.format(mark=mark), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "STENOGRAPHER_INTEGRATION"}
    if opt_in is not None:
        env["STENOGRAPHER_INTEGRATION"] = opt_in
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.conftest",
            "--rootdir",
            str(tmp_path),
            "-q",
            "-rs",
            str(tmp_path / "test_probe.py"),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return (tmp_path / "body-ran").exists(), result.stdout


@pytest.mark.parametrize("opt_in", [None, "0", ""])
def test_a_marked_test_does_not_run_without_the_opt_in(tmp_path, opt_in):
    ran, output = _run_probe(tmp_path, "@pytest.mark.integration", opt_in)

    assert not ran
    assert "1 skipped" in output
    assert "STENOGRAPHER_INTEGRATION=1" in output


def test_a_marked_test_runs_with_the_opt_in(tmp_path):
    ran, output = _run_probe(tmp_path, "@pytest.mark.integration", "1")

    assert ran
    assert "1 passed" in output


def test_an_unmarked_test_runs_without_the_opt_in(tmp_path):
    ran, output = _run_probe(tmp_path, "", None)

    assert ran
    assert "1 passed" in output
