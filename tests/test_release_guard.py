# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the GitHub release version guard."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from release_guard import ReleaseGuardError, analyze_releases, read_project_version


def _release(tag: str, *, draft: bool = False, prerelease: bool = False, release_id: int = 1):
    return {
        "id": release_id,
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
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


def test_checked_in_version_must_be_one_literal_plain_version(tmp_path) -> None:
    version_file = tmp_path / "_version.py"
    version_file.write_text('__version__ = "0.10.0"\n', encoding="utf-8")

    assert read_project_version(version_file) == "0.10.0"

    version_file.write_text('__version__ = "0.10.0-rc1"\n', encoding="utf-8")
    with pytest.raises(ReleaseGuardError, match=r"plain X\.Y\.Z"):
        read_project_version(version_file)
