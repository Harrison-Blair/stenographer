# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests plus the real-git invocation for the release version guard."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from release_guard import ReleaseGuardError, analyze_releases, plan_release

_TARGET = "a" * 40
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release_guard.py"


def _release(
    tag: str,
    *,
    draft: bool = False,
    prerelease: bool = False,
    release_id: int = 1,
    target: str = _TARGET,
):
    return {
        "id": release_id,
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "target_commitish": target,
    }


def test_lower_published_releases_report_the_highest_previous_tag() -> None:
    state = analyze_releases(
        [[_release("v0.8.9"), _release("v0.9.5", prerelease=True)]],
        "0.10.0",
    )

    assert state.highest_published_tag == "v0.9.5"
    assert state.matching_draft_id is None


@pytest.mark.parametrize("tag", ["v0.10.0", "v0.11.0"])
def test_equal_or_higher_published_release_blocks_the_candidate(tag: str) -> None:
    with pytest.raises(ReleaseGuardError, match="equal to or newer"):
        analyze_releases([[_release(tag)]], "0.10.0")


def test_equal_prerelease_blocks_the_candidate() -> None:
    with pytest.raises(ReleaseGuardError, match="equal to or newer"):
        analyze_releases([[_release("v0.10.0", prerelease=True)]], "0.10.0")


def test_matching_draft_is_reported_but_does_not_block_refresh() -> None:
    state = analyze_releases(
        [[_release("v0.10.0", draft=True, release_id=42)]],
        "0.10.0",
    )

    assert state.highest_published_tag is None
    assert state.matching_draft_id == 42


def test_duplicate_matching_drafts_fail_closed() -> None:
    releases = [
        [
            _release("v0.10.0", draft=True, release_id=42),
            _release("v0.10.0", draft=True, release_id=43),
        ]
    ]

    with pytest.raises(ReleaseGuardError, match="multiple drafts"):
        analyze_releases(releases, "0.10.0")


@pytest.mark.parametrize("tag", ["0.9.5", "release-0.9.5", "v0.9", "v0.9.5-rc.1"])
def test_unrecognized_published_tag_fails_closed(tag: str) -> None:
    with pytest.raises(ReleaseGuardError, match="unrecognized published release tag"):
        analyze_releases([[_release(tag)]], "0.10.0")


def test_paginated_release_data_is_fully_considered() -> None:
    pages = [
        [_release("v0.8.0")],
        [_release("v0.9.5"), _release("v0.10.0", draft=True, release_id=42)],
    ]

    state = analyze_releases(pages, "0.10.0")

    assert state.highest_published_tag == "v0.9.5"
    assert state.matching_draft_id == 42


@pytest.mark.parametrize("version", ["v0.10.0", "0.10", "0.10.0-rc1", "00.10.0"])
def test_candidate_version_must_be_plain_semver(version: str) -> None:
    with pytest.raises(ReleaseGuardError, match=r"plain X\.Y\.Z"):
        analyze_releases([[]], version)


@pytest.mark.parametrize(
    "pages",
    [
        {},
        [[{"id": 1, "tag_name": "v0.9.5", "draft": "false", "prerelease": False}]],
        [[{"id": 1, "tag_name": "v0.9.5", "draft": False}]],
    ],
)
def test_malformed_release_data_fails_closed(pages: object) -> None:
    with pytest.raises(ReleaseGuardError, match="malformed GitHub release data"):
        analyze_releases(pages, "0.10.0")


@pytest.mark.parametrize(
    ("bump", "candidate"),
    [("patch", "1.4.6"), ("minor", "1.5.0"), ("major", "2.0.0")],
)
def test_release_plan_bumps_the_highest_stable_tag(bump: str, candidate: str) -> None:
    plan = plan_release(
        ["v1.3.9", "v1.4.5", "notes"],
        [[_release("v1.3.9"), _release("v1.4.5")]],
        bump,
        _TARGET,
    )

    assert plan.previous_tag == "v1.4.5"
    assert plan.version == candidate
    assert plan.tag == f"v{candidate}"


def test_release_plan_uses_tags_even_when_the_latest_has_no_release() -> None:
    plan = plan_release(["v1.4.5"], [[]], "patch", _TARGET)

    assert plan.version == "1.4.6"


@pytest.mark.parametrize("tags", [[], ["v1.2"], ["v01.2.3"], ["v1.2.3-rc1"]])
def test_release_plan_fails_closed_without_an_unambiguous_stable_tag(tags: list[str]) -> None:
    with pytest.raises(ReleaseGuardError, match="stable Git tag"):
        plan_release(tags, [[]], "patch", _TARGET)


def test_published_release_without_its_immutable_tag_fails_closed() -> None:
    with pytest.raises(ReleaseGuardError, match="has no matching stable Git tag"):
        plan_release(["v1.4.5"], [[_release("v1.4.4")]], "patch", _TARGET)


def test_release_plan_preserves_matching_draft_for_retry() -> None:
    plan = plan_release(
        ["v1.4.5"],
        [[_release("v1.4.6", draft=True, release_id=42)]],
        "patch",
        _TARGET,
    )

    assert plan.matching_draft_id == 42


@pytest.mark.parametrize("bump", ["", "micro", "PATCH"])
def test_release_plan_rejects_unknown_bump(bump: str) -> None:
    with pytest.raises(ReleaseGuardError, match="patch, minor, or major"):
        plan_release(["v1.4.5"], [[]], bump, _TARGET)


def test_release_plan_rejects_an_unrelated_draft() -> None:
    with pytest.raises(ReleaseGuardError, match="unrelated draft"):
        plan_release(
            ["v1.4.5"],
            [[_release("v9.0.0", draft=True)]],
            "patch",
            _TARGET,
        )


def test_release_plan_rejects_a_matching_draft_for_another_commit() -> None:
    with pytest.raises(ReleaseGuardError, match="unexpected commit"):
        plan_release(
            ["v1.4.5"],
            [[_release("v1.4.6", draft=True, target="b" * 40)]],
            "patch",
            _TARGET,
        )


# --- The real Git invocation -------------------------------------------------
# The version guard shells out to git; a mocked subprocess would happily pass
# for a command git itself rejects, so these run the script against a real
# temporary repository.


def _release_repo(tmp_path: Path, *, annotated: bool) -> tuple[Path, str, str]:
    """A two-commit repo tagging v0.13.0 on the first commit; returns the repo,
    the tagged commit, and the dispatch head."""
    repo = tmp_path / "repo"
    repo.mkdir()
    hooks = tmp_path / "hooks"
    hooks.mkdir()  # Neutralize any global core.hooksPath.

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    git("config", "user.email", "guard@example.com")
    git("config", "user.name", "Release Guard Test")
    git("config", "core.hooksPath", str(hooks))
    (repo / "tracked.txt").write_text("release\n", encoding="utf-8")
    git("add", "tracked.txt")
    git("commit", "-q", "-m", "first")
    tagged = git("rev-parse", "HEAD")
    if annotated:
        git("tag", "-a", "-m", "release", "v0.13.0")
    else:
        git("tag", "v0.13.0")
    (repo / "tracked.txt").write_text("dispatch\n", encoding="utf-8")
    git("add", "tracked.txt")
    git("commit", "-q", "-m", "second")
    return repo, tagged, git("rev-parse", "HEAD")


@pytest.mark.parametrize("annotated", [False, True], ids=["lightweight", "annotated"])
def test_main_resolves_the_previous_tag_to_its_commit(tmp_path: Path, annotated: bool) -> None:
    """The previous tag resolves to a commit, not a tag object or a failure."""
    repo, tagged, head = _release_repo(tmp_path, annotated=annotated)
    pages = tmp_path / "releases.json"
    pages.write_text(json.dumps([[_release("v0.13.0", target=tagged)]]), encoding="utf-8")
    github_output = tmp_path / "github_output.txt"

    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            str(pages),
            "patch",
            "--target-commit",
            head,
            "--repository",
            str(repo),
            "--github-output",
            str(github_output),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "release guard passed: v0.13.1" in result.stdout
    assert f"previous_commit={tagged}" in github_output.read_text(encoding="utf-8")
    assert "previous_tag=v0.13.0" in github_output.read_text(encoding="utf-8")
