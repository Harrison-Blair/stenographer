# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the Pages workflow's install-script step under each trigger with a stub curl."""

import os
import re
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_RELEASE_SCRIPT = "released script\n"
_CHECKOUT_SCRIPT = "checkout script\n"


def _step_script() -> str:
    workflow = (_ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    step = workflow[workflow.index("- name: Add the install script") :]
    step = step[: step.index("- name:", 1)]
    return textwrap.dedent(step[step.index("run: |") + len("run: |") :])


def _run_step(tmp_path: Path, event: str, curl: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "_site").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "quick-install.sh").write_text(_CHECKOUT_SCRIPT)
    commands = tmp_path / "commands"
    commands.mkdir()
    stub = commands / "curl"
    stub.write_text(curl)
    stub.chmod(0o755)
    return subprocess.run(
        ["bash", "-e", "-c", _step_script()],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_EVENT_NAME": event,
        },
        capture_output=True,
        text=True,
    )


def test_a_deploy_serves_the_latest_release_script(tmp_path: Path) -> None:
    curl = f"""#!/bin/sh
case "$*" in
    *releases/latest/download/quick-install.sh*) ;;
    *) exit 22 ;;
esac
printf '{_RELEASE_SCRIPT.strip()}\\n' > _site/install.sh
"""
    result = _run_step(tmp_path, "workflow_dispatch", curl)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "_site" / "install.sh").read_text() == _RELEASE_SCRIPT


def test_a_failed_download_fails_the_deploy_instead_of_using_the_checkout(tmp_path: Path) -> None:
    result = _run_step(tmp_path, "workflow_dispatch", "#!/bin/sh\nexit 22\n")

    assert result.returncode != 0
    assert not (tmp_path / "_site" / "install.sh").exists()


def test_a_pull_request_build_uses_the_checkout_script(tmp_path: Path) -> None:
    result = _run_step(tmp_path, "pull_request", "#!/bin/sh\nexit 22\n")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "_site" / "install.sh").read_text() == _CHECKOUT_SCRIPT


@pytest.mark.parametrize(
    ("event", "ref_input", "expected"),
    [
        ("workflow_dispatch", "", "main"),
        ("workflow_dispatch", "v9.9.9", "v9.9.9"),
        # No inputs on a pull request; a null or empty ref makes checkout use the merge ref.
        ("pull_request", None, ""),
    ],
    ids=["dispatch-blank", "dispatch-tag", "pull-request"],
)
def test_the_checkout_ref_follows_the_trigger_not_the_selected_branch(
    event: str, ref_input: str | None, expected: str
) -> None:
    workflow = (_ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    expression = re.search(r"^ +ref: \$\{\{ (.+) \}\}$", workflow, re.MULTILINE).group(1)
    # GitHub's || and && keep operands and treat "" and null as false, as Python's do.
    python_expression = expression.replace("||", "or").replace("&&", "and")

    resolved = eval(
        python_expression,
        {
            "github": SimpleNamespace(event_name=event),
            "inputs": SimpleNamespace(ref=ref_input),
        },
    )

    assert (resolved or "") == expected
