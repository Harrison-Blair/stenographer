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

_THREE_SECTION_BODY = """\
This release sharpens dictation delivery. Nothing else changes.

### Added

- Adds a paste fallback for compositors without a focus popup, with a
  two-space continuation line as the file wraps them.

### Removed

- Removes the unused clipboard poller.

### Fixed

- Fixes the overlay flicker on resume."""


def _changelog(body: str, version: str = "v1.0.0", published: str = "2026-09-01") -> str:
    return f"# Changelog\n\n## [{version}] - {published}\n\n{body}\n"


def test_parse_changelog_extracts_adjacent_entries() -> None:
    notes = parse_changelog(
        """# Changelog

## [v1.1.0] - 2026-09-02

Adds one thing.

### Added

- Adds one thing.

## [v1.0.0] - 2026-09-01

Fixes another thing.

### Fixed

- Fixes another thing.
"""
    )

    assert [note.version for note in notes] == ["v1.1.0", "v1.0.0"]
    assert notes[0].body == "Adds one thing.\n\n### Added\n\n- Adds one thing."
    assert notes[1].published == "2026-09-01"


def test_note_for_version_accepts_tag_or_plain_version() -> None:
    changelog = _changelog(_THREE_SECTION_BODY, version="v1.2.3", published="2026-09-03")

    assert note_for_version(changelog, "v1.2.3").body == _THREE_SECTION_BODY
    assert note_for_version(changelog, "1.2.3").version == "v1.2.3"


def test_parse_changelog_accepts_a_full_three_section_entry() -> None:
    notes = parse_changelog(_changelog(_THREE_SECTION_BODY))

    assert notes[0].body == _THREE_SECTION_BODY


@pytest.mark.parametrize(
    "body",
    [
        "Adds a single section.\n\n### Added\n\n- Adds a thing.",
        "Removes a single section.\n\n### Removed\n\n- Removes a thing.",
        "Fixes a single section.\n\n### Fixed\n\n- Fixes a thing.",
        "Adds and fixes.\n\n### Added\n\n- Adds a thing.\n\n### Fixed\n\n- Fixes a thing.",
        "Removes and fixes.\n\n### Removed\n\n- Drops a thing.\n\n### Fixed\n\n- Fixes it.",
    ],
)
def test_parse_changelog_accepts_omitted_sections(body: str) -> None:
    assert parse_changelog(_changelog(body))[0].body == body


@pytest.mark.parametrize(
    "synopsis",
    [
        "One sentence only.",
        "First sentence. Second sentence.",
        "First one. Second one. Third one.",
        "Downloads a model of about `1.5 GB`. Nothing else changes.",
        "Bumps the default to `v0.13.0` for every fresh install.",
        "Waits up to 2.5 seconds for the model. It then gives up.",
    ],
)
def test_parse_changelog_accepts_one_to_three_sentence_synopses(synopsis: str) -> None:
    body = f"{synopsis}\n\n### Added\n\n- Adds a thing."

    assert parse_changelog(_changelog(body))[0].body == body


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            "- Adds a thing without a synopsis.\n\n### Added\n\n- Adds a thing.",
            "must start with a synopsis paragraph",
        ),
        (
            "### Added\n\n- Adds a thing.",
            "must start with a synopsis paragraph",
        ),
        (
            "One. Two. Three. Four.\n\n### Added\n\n- Adds a thing.",
            "synopsis must be 1 to 3 sentences, found 4",
        ),
        (
            "Fixes then adds.\n\n### Fixed\n\n- Fixes a thing.\n\n### Added\n\n- Adds it.",
            "sections must appear in Added, Removed, Fixed order",
        ),
        (
            "Adds twice.\n\n### Added\n\n- Adds a thing.\n\n### Added\n\n- Adds another.",
            r"duplicate '### Added' section",
        ),
        (
            "Changes a thing.\n\n### Changed\n\n- Changes a thing.",
            r"unknown section header '### Changed'",
        ),
        (
            "Adds a thing.\n\n### Added\n\n- Adds a thing.\n\nAnd some prose.",
            r"'### Added' section allows only",
        ),
        (
            "Adds a thing.\n\n- A loose bullet.\n\n### Added\n\n- Adds a thing.",
            "unexpected content between the synopsis and the first section header",
        ),
        (
            "Adds nothing.\n\n### Added\n\n### Fixed\n\n- Fixes a thing.",
            r"'### Added' section needs at least one bullet",
        ),
        (
            "A release with no sections at all.",
            "needs at least one section",
        ),
        (
            "Adds a thing.\n\n### Added\n\n- Adds a thing.\n\n- Adds another thing.",
            r"'### Added' section allows no blank lines between bullets",
        ),
        (
            "Adds a thing.\n\n### Added\n\n- Adds a thing.\n  - And a sub-bullet.",
            r"'### Added' section allows no sub-bullets",
        ),
    ],
)
def test_parse_changelog_rejects_malformed_bodies(body: str, message: str) -> None:
    with pytest.raises(ReleaseNotesError, match=rf"v1\.0\.0: .*{message}"):
        parse_changelog(_changelog(body))


def test_parse_changelog_rejects_a_malformed_entry_for_another_version() -> None:
    changelog = (
        _changelog(_THREE_SECTION_BODY, version="v1.1.0", published="2026-09-02").rstrip("\n")
        + "\n\n## [v1.0.0] - 2026-09-01\n\n### Added\n\n- Adds a thing.\n"
    )

    with pytest.raises(ReleaseNotesError, match=r"v1\.0\.0: .*synopsis"):
        note_for_version(changelog, "1.1.0")


@pytest.mark.parametrize(
    "unreleased",
    [
        "",
        "Nothing is pending yet.",
        "Work is pending.\n\n### Fixed\n\n- Fixes a thing.",
    ],
)
def test_parse_changelog_accepts_a_well_formed_unreleased_section(unreleased: str) -> None:
    changelog = (
        f"# Changelog\n\n## [Unreleased]\n\n{unreleased}\n\n"
        f"## [v1.0.0] - 2026-09-01\n\n{_THREE_SECTION_BODY}\n"
    )

    assert [note.version for note in parse_changelog(changelog)] == ["v1.0.0"]


@pytest.mark.parametrize(
    ("unreleased", "message"),
    [
        ("- A loose bullet.", "must start with a synopsis paragraph"),
        ("One. Two. Three. Four.", "synopsis must be 1 to 3 sentences, found 4"),
        (
            "Work is pending.\n\n### Changed\n\n- Changes a thing.",
            r"unknown section header '### Changed'",
        ),
        ("Work is pending.\n\n### Fixed\n\nProse, not a bullet.", r"allows only"),
    ],
)
def test_parse_changelog_rejects_a_malformed_unreleased_section(
    unreleased: str, message: str
) -> None:
    changelog = (
        f"# Changelog\n\n## [Unreleased]\n\n{unreleased}\n\n"
        f"## [v1.0.0] - 2026-09-01\n\n{_THREE_SECTION_BODY}\n"
    )

    with pytest.raises(ReleaseNotesError, match=rf"\[Unreleased\]: .*{message}"):
        parse_changelog(changelog)


@pytest.mark.parametrize(
    ("changelog", "message"),
    [
        ("# Changelog\n", "no release entries"),
        (
            "## [v1.0.0] - 2026-09-01\n\nFirst.\n\n### Added\n\n- One.\n\n"
            "## [v1.0.0] - 2026-09-02\n\nAgain.\n\n### Added\n\n- Two.\n",
            "duplicate release entry",
        ),
        ("## [v1.0.0] - 2026-09-01\n", "empty release body"),
    ],
)
def test_parse_changelog_rejects_invalid_entries(changelog: str, message: str) -> None:
    with pytest.raises(ReleaseNotesError, match=message):
        parse_changelog(changelog)


def test_note_for_version_rejects_missing_and_malformed_versions() -> None:
    changelog = _changelog(_THREE_SECTION_BODY, version="v1.2.3", published="2026-09-03")

    with pytest.raises(ReleaseNotesError, match="no release entry"):
        note_for_version(changelog, "1.2.4")
    with pytest.raises(ReleaseNotesError, match=r"plain X\.Y\.Z"):
        note_for_version(changelog, "1.2")


def test_repository_changelog_covers_every_published_release() -> None:
    changelog_path = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    notes = parse_changelog(changelog_path.read_text(encoding="utf-8"))

    assert tuple(note.version for note in notes) == _EXPECTED_VERSIONS[::-1]
