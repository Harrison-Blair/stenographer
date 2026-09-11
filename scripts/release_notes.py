# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate and extract authored release notes for the release workflow."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_VERSION_RE = re.compile(r"(?:v)?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_HEADING_RE = re.compile(
    r"^## \[(v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\]"
    r" - ([0-9]{4}-[0-9]{2}-[0-9]{2})[ \t]*$",
    re.MULTILINE,
)


class ReleaseNotesError(ValueError):
    """The changelog is unsafe or cannot be interpreted confidently."""


@dataclass(frozen=True)
class ReleaseNote:
    """One dated release note and the body sent to GitHub."""

    version: str
    published: str
    body: str


def _normalize_version(version: str) -> str:
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        raise ReleaseNotesError(f"version {version!r} must be plain X.Y.Z")
    return f"v{match.group(1)}.{match.group(2)}.{match.group(3)}"


def parse_changelog(text: str) -> tuple[ReleaseNote, ...]:
    """Parse all release entries in newest-first order."""

    matches = tuple(_HEADING_RE.finditer(text))
    if not matches:
        raise ReleaseNotesError("no release entries found")

    notes: list[ReleaseNote] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        version = match.group(1)
        if version in seen:
            raise ReleaseNotesError(f"duplicate release entry for {version}")
        seen.add(version)

        published = match.group(2)
        try:
            date.fromisoformat(published)
        except ValueError as error:
            raise ReleaseNotesError(f"invalid publication date for {version}") from error

        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : body_end].strip()
        if not body:
            raise ReleaseNotesError(f"empty release body for {version}")
        notes.append(ReleaseNote(version=version, published=published, body=body))

    return tuple(notes)


def note_for_version(text: str, version: str) -> ReleaseNote:
    """Return one release note, accepting either ``vX.Y.Z`` or ``X.Y.Z``."""

    normalized = _normalize_version(version)
    for note in parse_changelog(text):
        if note.version == normalized:
            return note
    raise ReleaseNotesError(f"no release entry for {normalized}")


def _read_changelog(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ReleaseNotesError(f"cannot read changelog {path}: {error}") from error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("check", "extract"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("version", help="release version, as X.Y.Z or vX.Y.Z")
        command_parser.add_argument("changelog", type=Path)

    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        note = note_for_version(_read_changelog(args.changelog), args.version)
    except ReleaseNotesError as error:
        raise SystemExit(f"release notes check failed: {error}") from error

    if args.command == "check":
        print(f"release note found: {note.version} ({note.published})")
    else:
        print(note.body)


if __name__ == "__main__":
    main()
