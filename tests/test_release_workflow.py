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
