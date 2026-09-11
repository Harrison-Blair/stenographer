# SPDX-License-Identifier: GPL-3.0-or-later
"""``python -m stenographer.cli``: the module-execution shim, run for real.

The shim only works as a real process entry point, so these cases start one
rather than importing it: ``__main__`` guards its own body, and the exit code
is what a caller actually sees.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import stenographer


def _run(state: pathlib.Path, *argv: str) -> subprocess.CompletedProcess[str]:
    # The shim opens the logging pipeline, so the child's state and config
    # directories are redirected into the test's own temporary tree; an
    # inherited STENOGRAPHER_CONFIG would point it back out of there.
    environment = {
        **os.environ,
        "XDG_STATE_HOME": str(state / "state"),
        "XDG_CONFIG_HOME": str(state / "config"),
    }
    environment.pop("STENOGRAPHER_CONFIG", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "stenographer.cli", *argv],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        stdout, stderr = process.communicate(timeout=60)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def test_module_execution_reports_the_version_and_exits_zero(tmp_path):
    result = _run(tmp_path, "--version")

    assert result.returncode == 0
    assert result.stdout.strip() == stenographer.__version__


def test_module_execution_propagates_a_parser_failure_as_its_exit_code(tmp_path):
    result = _run(tmp_path, "bogus")

    assert result.returncode == 2
    assert "invalid choice: 'bogus'" in result.stderr
