# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the preflight guard step's shell under each trigger with a stub guard."""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release-preflight.yml"
_SHA = "c" * 40


def _guard_step_script() -> str:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    step = workflow[workflow.index("- name: Check release versions") :]
    step = step[: step.index("- name:", 1)]
    body = step[step.index("run: |") + len("run: |") :]
    return textwrap.dedent(body).replace("${{ inputs.bump || 'patch' }}", "patch")


def _guard_arguments(tmp_path: Path, event: str, ref: str) -> list[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    (bin_dir / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    venv_python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    for stub in (bin_dir / "python", venv_python):
        stub.chmod(0o755)
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _guard_step_script()],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_EVENT_NAME": event,
            "GITHUB_REF": ref,
            "GITHUB_SHA": _SHA,
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "RUNNER_TEMP": str(tmp_path),
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()[1:]


@pytest.mark.parametrize(
    ("event", "ref", "expected", "absent"),
    [
        ("pull_request", "refs/pull/7/merge", ["--skip-draft-checks"], "--target-commit"),
        ("workflow_dispatch", "refs/heads/main", ["--target-commit", _SHA], "--skip-"),
        ("workflow_dispatch", "refs/heads/dev", ["--skip-target-check"], "--target-commit"),
    ],
    ids=["pull-request", "dispatch-main", "dispatch-non-main"],
)
def test_preflight_guard_mode_follows_the_trigger(
    tmp_path: Path, event: str, ref: str, expected: list[str], absent: str
) -> None:
    arguments = _guard_arguments(tmp_path, event, ref)

    assert arguments[0].endswith("releases.json")
    assert arguments[1] == "patch"
    position = arguments.index(expected[0])
    assert arguments[position : position + len(expected)] == expected
    assert not any(argument.startswith(absent) for argument in arguments)
