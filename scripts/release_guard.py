# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed version guard for the draft-release workflow."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
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


@dataclass(frozen=True)
class ReleasePlan:
    """Version selected from the stable tag history and requested bump."""

    version: str
    tag: str
    previous_tag: str
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


def _release_fields(release: object) -> tuple[int, str, bool, bool, str]:
    if not isinstance(release, dict):
        raise ReleaseGuardError("malformed GitHub release data: release is not an object")

    release_id = release.get("id")
    tag = release.get("tag_name")
    draft = release.get("draft")
    prerelease = release.get("prerelease")
    target_commitish = release.get("target_commitish")
    if (
        type(release_id) is not int
        or not isinstance(tag, str)
        or type(draft) is not bool
        or type(prerelease) is not bool
        or not isinstance(target_commitish, str)
        or not target_commitish
    ):
        raise ReleaseGuardError("malformed GitHub release data: invalid release fields")
    return release_id, tag, draft, prerelease, target_commitish


def analyze_releases(
    pages: object,
    candidate_version: str,
    expected_target_commit: str | None = None,
) -> ReleaseState:
    """Inspect every paginated GitHub release and decide whether release may proceed."""

    candidate = _parse_version(candidate_version)
    candidate_tag = f"v{candidate_version}"
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ReleaseGuardError("malformed GitHub release data: expected a list of pages")

    published: list[tuple[tuple[int, int, int], str]] = []
    matching_drafts: list[int] = []
    for page in pages:
        for release in page:
            release_id, tag, draft, _prerelease, target_commitish = _release_fields(release)
            if draft:
                if tag != candidate_tag:
                    raise ReleaseGuardError(
                        f"unrelated draft {tag} exists while planning {candidate_tag}"
                    )
                if (
                    expected_target_commit is not None
                    and target_commitish != expected_target_commit
                ):
                    raise ReleaseGuardError(
                        f"draft {tag} targets unexpected commit {target_commitish!r}"
                    )
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


def plan_release(
    tags: list[str], pages: object, bump: str, expected_target_commit: str
) -> ReleasePlan:
    """Select the next version from stable tags and validate GitHub release state."""

    if bump not in {"patch", "minor", "major"}:
        raise ReleaseGuardError("release bump must be patch, minor, or major")
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", expected_target_commit) is None:
        raise ReleaseGuardError("release target must be a full Git commit ID")

    stable: list[tuple[tuple[int, int, int], str]] = []
    for tag in tags:
        if not tag.startswith("v"):
            continue
        try:
            stable.append((_parse_version(tag[1:]), tag))
        except ReleaseGuardError as error:
            raise ReleaseGuardError(f"unrecognized stable Git tag: {tag!r}") from error
    if not stable:
        raise ReleaseGuardError("no stable Git tag found; expected at least one vX.Y.Z tag")

    previous, previous_tag = max(stable)
    major, minor, patch = previous
    if bump == "major":
        candidate = (major + 1, 0, 0)
    elif bump == "minor":
        candidate = (major, minor + 1, 0)
    else:
        candidate = (major, minor, patch + 1)
    version = ".".join(str(part) for part in candidate)

    state = analyze_releases(pages, version, expected_target_commit)
    tag_names = set(tags)
    assert isinstance(pages, list)  # Validated by analyze_releases.
    for page in pages:
        for release in page:
            _release_id, tag, draft, _prerelease, _target = _release_fields(release)
            if not draft and tag not in tag_names:
                raise ReleaseGuardError(f"published release {tag} has no matching stable Git tag")

    return ReleasePlan(
        version=version,
        tag=f"v{version}",
        previous_tag=previous_tag,
        matching_draft_id=state.matching_draft_id,
    )


def _git_output(repository: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReleaseGuardError(f"cannot inspect Git tags in {repository}: {error}") from error
    return result.stdout.strip()


def read_git_tags(repository: Path) -> list[str]:
    """Read every local tag from a fully fetched release checkout."""

    output = _git_output(repository, "tag", "--list")
    return output.splitlines() if output else []


def _write_github_output(path: Path, plan: ReleasePlan, previous_commit: str) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(f"version={plan.version}\n")
        output.write(f"tag={plan.tag}\n")
        output.write(f"previous_tag={plan.previous_tag}\n")
        output.write(f"previous_commit={previous_commit}\n")
        output.write(f"draft_id={plan.matching_draft_id or ''}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("releases", type=Path, help="JSON pages from gh api --paginate --slurp")
    parser.add_argument("bump", choices=("patch", "minor", "major"))
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    try:
        pages = json.loads(args.releases.read_text(encoding="utf-8"))
        plan = plan_release(read_git_tags(args.repository), pages, args.bump, args.target_commit)
        previous_commit = _git_output(
            args.repository,
            "rev-parse",
            "--verify",
            f"refs/tags/{plan.previous_tag}^{{commit}}",
        )
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", previous_commit):
            raise ReleaseGuardError(f"cannot resolve {plan.previous_tag} to a commit")
    except (OSError, json.JSONDecodeError, ReleaseGuardError) as error:
        raise SystemExit(f"release guard failed: {error}") from error

    if args.github_output is not None:
        _write_github_output(args.github_output, plan, previous_commit)
    print(
        f"release guard passed: {plan.tag}; previous={plan.previous_tag}; "
        f"draft={plan.matching_draft_id or 'none'}"
    )


if __name__ == "__main__":
    main()
