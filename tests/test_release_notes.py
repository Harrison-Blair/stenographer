# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for authored release-note extraction."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from release_notes import ReleaseNotesError, note_for_version, parse_changelog

_EXPECTED_VERSIONS = (
    "v0.6.1",
    "v0.6.3",
    "v0.6.4",
    "v0.6.5",
    "v0.6.6",
    "v0.6.7",
    "v0.6.8",
    "v0.6.9",
    "v0.6.10",
    "v0.7.2",
    "v0.7.3",
    "v0.7.5",
    "v0.7.7",
    "v0.8.3",
    "v0.9.2",
    "v0.9.3",
    "v0.9.4",
    "v0.9.5",
    "v0.10.0",
    "v0.11.0",
    "v0.11.5",
    "v0.11.6",
    "v0.12.1",
    "v0.12.2",
    "v0.12.3",
    "v0.13.0",
)


def test_parse_changelog_extracts_adjacent_entries() -> None:
    notes = parse_changelog(
        """# Changelog

## [v1.1.0] - 2026-09-02

Added one thing.

## [v1.0.0] - 2026-09-01

Fixed another thing.
"""
    )

    assert [note.version for note in notes] == ["v1.1.0", "v1.0.0"]
    assert notes[0].body == "Added one thing."
    assert notes[1].published == "2026-09-01"


def test_note_for_version_accepts_tag_or_plain_version() -> None:
    changelog = """# Changelog

## [v1.2.3] - 2026-09-03

The release body.
"""

    assert note_for_version(changelog, "v1.2.3").body == "The release body."
    assert note_for_version(changelog, "1.2.3").version == "v1.2.3"


@pytest.mark.parametrize(
    ("changelog", "message"),
    [
        ("# Changelog\n", "no release entries"),
        (
            "## [v1.0.0] - 2026-09-01\n\nFirst.\n\n## [v1.0.0] - 2026-09-02\n\nAgain.\n",
            "duplicate release entry",
        ),
        ("## [v1.0.0] - 2026-09-01\n", "empty release body"),
    ],
)
def test_parse_changelog_rejects_invalid_entries(changelog: str, message: str) -> None:
    with pytest.raises(ReleaseNotesError, match=message):
        parse_changelog(changelog)


def test_note_for_version_rejects_missing_and_malformed_versions() -> None:
    changelog = """# Changelog

## [v1.2.3] - 2026-09-03

The release body.
"""

    with pytest.raises(ReleaseNotesError, match="no release entry"):
        note_for_version(changelog, "1.2.4")
    with pytest.raises(ReleaseNotesError, match=r"plain X\.Y\.Z"):
        note_for_version(changelog, "1.2")


def test_repository_changelog_covers_every_published_release() -> None:
    changelog_path = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    notes = parse_changelog(changelog_path.read_text(encoding="utf-8"))

    assert tuple(note.version for note in notes) == _EXPECTED_VERSIONS[::-1]
