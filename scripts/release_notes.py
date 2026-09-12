# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate and extract authored release notes for the release workflow."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_VERSION_RE = re.compile(r"(?:v)?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_HEADING_RE = re.compile(
    r"^## \[(v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\]"
    r" - ([0-9]{4}-[0-9]{2}-[0-9]{2})[ \t]*$",
    re.MULTILINE,
)
_UNRELEASED_HEADING_RE = re.compile(r"^## \[Unreleased\][ \t]*$", re.MULTILINE)
_ANY_HEADING_RE = re.compile(r"^## ", re.MULTILINE)

_SECTION_ORDER = ("Added", "Removed", "Fixed")
_SECTION_HEADER_RE = re.compile(r"^###[ \t]+(.*?)[ \t]*$")
_CODE_SPAN_RE = re.compile(r"`[^`]*`")
_SENTENCE_END_RE = re.compile(r"[.!?](?:\s+(?=[\"'(\[]?[A-Z])|$)")
_BULLET_RE = re.compile(r"^- \S")
_SUB_BULLET_RE = re.compile(r"^ {2}[-*+][ \t]")
_CONTINUATION_RE = re.compile(r"^ {2}(?! )\S")
_NON_PROSE_PREFIXES = ("- ", "* ", "+ ", "#", ">", "|")

_MIN_SENTENCES = 1
_MAX_SENTENCES = 3
_UNRELEASED_LABEL = "[Unreleased]"


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


def _paragraphs(lines: Sequence[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    for line in lines:
        if line.strip():
            if not blocks or not blocks[-1]:
                blocks.append([])
            blocks[-1].append(line)
        elif blocks and blocks[-1]:
            blocks.append([])
    return [block for block in blocks if block]


def _count_sentences(paragraph: Sequence[str]) -> int:
    prose = _CODE_SPAN_RE.sub(" ", " ".join(paragraph))
    return len(_SENTENCE_END_RE.findall(" ".join(prose.split())))


def _validate_synopsis(label: str, lines: Sequence[str]) -> None:
    blocks = _paragraphs(lines)
    if not blocks:
        raise ReleaseNotesError(
            f"{label}: the body must start with a synopsis paragraph of "
            f"{_MIN_SENTENCES} to {_MAX_SENTENCES} sentences"
        )

    first = blocks[0][0]
    if first.startswith(_NON_PROSE_PREFIXES) or first != first.lstrip():
        raise ReleaseNotesError(
            f"{label}: the body must start with a synopsis paragraph, not a bullet or a heading"
        )

    sentences = _count_sentences(blocks[0])
    if not _MIN_SENTENCES <= sentences <= _MAX_SENTENCES:
        raise ReleaseNotesError(
            f"{label}: the synopsis must be {_MIN_SENTENCES} to {_MAX_SENTENCES} "
            f"sentences, found {sentences}"
        )

    if len(blocks) > 1:
        raise ReleaseNotesError(
            f"{label}: unexpected content between the synopsis and the first section header"
        )


def _validate_section(label: str, name: str, lines: Sequence[str]) -> None:
    bullets = list(lines)
    while bullets and not bullets[0].strip():
        bullets.pop(0)
    while bullets and not bullets[-1].strip():
        bullets.pop()

    if not bullets:
        raise ReleaseNotesError(f"{label}: the '### {name}' section needs at least one bullet")

    for index, line in enumerate(bullets):
        if not line.strip() or _BULLET_RE.match(line):
            continue
        if _SUB_BULLET_RE.match(line):
            raise ReleaseNotesError(f"{label}: the '### {name}' section allows no sub-bullets")
        if index and _CONTINUATION_RE.match(line):
            continue
        raise ReleaseNotesError(
            f"{label}: the '### {name}' section allows only '- ' bullets and "
            "two-space continuation lines"
        )

    if any(not line.strip() for line in bullets):
        raise ReleaseNotesError(
            f"{label}: the '### {name}' section allows no blank lines between bullets"
        )


def _section_headers(lines: Sequence[str]) -> list[tuple[int, str]]:
    headers: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = _SECTION_HEADER_RE.match(line)
        if match is not None:
            headers.append((index, match.group(1)))
    return headers


def _validate_body(label: str, body: str, *, require_section: bool) -> None:
    lines = body.splitlines()
    headers = _section_headers(lines)

    _validate_synopsis(label, lines[: headers[0][0]] if headers else lines)

    if not headers:
        if require_section:
            raise ReleaseNotesError(
                f"{label}: needs at least one section "
                f"({', '.join(f'### {name}' for name in _SECTION_ORDER)})"
            )
        return

    seen: list[str] = []
    for position, (start, name) in enumerate(headers):
        if name not in _SECTION_ORDER:
            raise ReleaseNotesError(
                f"{label}: unknown section header '### {name}'; expected "
                f"{', '.join(_SECTION_ORDER)}"
            )
        if name in seen:
            raise ReleaseNotesError(f"{label}: duplicate '### {name}' section")
        if seen and _SECTION_ORDER.index(name) < _SECTION_ORDER.index(seen[-1]):
            raise ReleaseNotesError(
                f"{label}: sections must appear in {', '.join(_SECTION_ORDER)} order"
            )
        seen.append(name)

        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        _validate_section(label, name, lines[start + 1 : end])


def _validate_unreleased(text: str) -> None:
    match = _UNRELEASED_HEADING_RE.search(text)
    if match is None:
        return

    rest = text[match.end() :]
    following = _ANY_HEADING_RE.search(rest)
    body = (rest[: following.start()] if following else rest).strip()
    if body:
        _validate_body(_UNRELEASED_LABEL, body, require_section=False)


def parse_changelog(text: str) -> tuple[ReleaseNote, ...]:
    """Parse all release entries in newest-first order, rejecting malformed ones."""

    _validate_unreleased(text)

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
        _validate_body(version, body, require_section=True)
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
