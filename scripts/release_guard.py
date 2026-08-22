# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed version guard for the draft-release workflow."""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

_VERSION_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


class ReleaseGuardError(ValueError):
    """Release state is unsafe or cannot be interpreted confidently."""


@dataclass(frozen=True)
class ReleaseState:
    """Published-version boundary and optional refreshable draft."""

    highest_published_tag: str | None
    matching_draft_id: int | None


def _parse_version(version: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        raise ReleaseGuardError(f"candidate version {version!r} must be plain X.Y.Z")
    return tuple(int(part) for part in match.groups())


def _published_version(tag: str) -> tuple[int, int, int]:
    if not tag.startswith("v"):
        raise ReleaseGuardError(f"unrecognized published release tag: {tag!r}")
    try:
        return _parse_version(tag[1:])
    except ReleaseGuardError as error:
        raise ReleaseGuardError(f"unrecognized published release tag: {tag!r}") from error


def _release_fields(release: object) -> tuple[int, str, bool, bool]:
    if not isinstance(release, dict):
        raise ReleaseGuardError("malformed GitHub release data: release is not an object")

    release_id = release.get("id")
    tag = release.get("tag_name")
    draft = release.get("draft")
    prerelease = release.get("prerelease")
    if (
        type(release_id) is not int
        or not isinstance(tag, str)
        or type(draft) is not bool
        or type(prerelease) is not bool
    ):
        raise ReleaseGuardError("malformed GitHub release data: invalid release fields")
    return release_id, tag, draft, prerelease


def analyze_releases(pages: object, candidate_version: str) -> ReleaseState:
    """Inspect every paginated GitHub release and decide whether release may proceed."""

    candidate = _parse_version(candidate_version)
    candidate_tag = f"v{candidate_version}"
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ReleaseGuardError("malformed GitHub release data: expected a list of pages")

    published: list[tuple[tuple[int, int, int], str]] = []
    matching_drafts: list[int] = []
    for page in pages:
        for release in page:
            release_id, tag, draft, _prerelease = _release_fields(release)
            if draft:
                if tag == candidate_tag:
                    matching_drafts.append(release_id)
                continue

            version = _published_version(tag)
            if version >= candidate:
                raise ReleaseGuardError(
                    f"published release {tag} is equal to or newer than {candidate_tag}"
                )
            published.append((version, tag))

    if len(matching_drafts) > 1:
        raise ReleaseGuardError(f"multiple drafts exist for {candidate_tag}")

    highest_tag = max(published)[1] if published else None
    draft_id = matching_drafts[0] if matching_drafts else None
    return ReleaseState(highest_published_tag=highest_tag, matching_draft_id=draft_id)


def read_project_version(path: Path) -> str:
    """Read the sole literal ``__version__`` assignment without importing the project."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as error:
        raise ReleaseGuardError(f"cannot read version file {path}: {error}") from error

    values: list[object] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        is_version = any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
        if is_version:
            values.append(node.value.value if isinstance(node.value, ast.Constant) else None)
    if len(values) != 1 or not isinstance(values[0], str):
        raise ReleaseGuardError(f"{path} must contain one literal __version__ assignment")
    _parse_version(values[0])
    return values[0]


def _write_github_output(path: Path, version: str, state: ReleaseState) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(f"version={version}\n")
        output.write(f"tag=v{version}\n")
        output.write(f"previous_tag={state.highest_published_tag or ''}\n")
        output.write(f"draft_id={state.matching_draft_id or ''}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("releases", type=Path, help="JSON pages from gh api --paginate --slurp")
    parser.add_argument("version_file", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    try:
        version = read_project_version(args.version_file)
        pages = json.loads(args.releases.read_text(encoding="utf-8"))
        state = analyze_releases(pages, version)
    except (OSError, json.JSONDecodeError, ReleaseGuardError) as error:
        raise SystemExit(f"release guard failed: {error}") from error

    if args.github_output is not None:
        _write_github_output(args.github_output, version, state)
    print(
        f"release guard passed: v{version}; "
        f"previous={state.highest_published_tag or 'none'}; "
        f"draft={state.matching_draft_id or 'none'}"
    )


if __name__ == "__main__":
    main()
