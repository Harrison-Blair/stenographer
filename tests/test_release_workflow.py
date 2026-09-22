# SPDX-License-Identifier: GPL-3.0-or-later
"""Static safety contracts for the draft-release mutation step."""

from pathlib import Path


def test_draft_refresh_never_retargets_the_existing_release() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
    ).read_text(encoding="utf-8")

    patch = workflow.index("gh api -X PATCH")
    create = workflow.index("gh api -X POST", patch)
    target = workflow.index('-f "target_commitish=${GITHUB_SHA}"')
    assert target > create


def test_every_release_guard_call_checks_the_draft_target_commit() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
    ).read_text(encoding="utf-8")

    calls = workflow.split("scripts/release_guard.py")[1:]
    assert len(calls) == 3
    for call in calls:
        lines = call.splitlines()
        end = next(i for i, line in enumerate(lines) if not line.rstrip().endswith("\\"))
        command = "\n".join(lines[: end + 1])
        assert '--target-commit "${GITHUB_SHA}"' in command
        assert "--skip-" not in command
