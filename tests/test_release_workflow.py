# SPDX-License-Identifier: GPL-3.0-or-later
"""Contracts for the release mutation step, static and run against a stub ``gh``."""

import os
import subprocess
import textwrap
from pathlib import Path

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
_SHA = "c" * 40
_PREVIOUS_COMMIT = "a" * 40
_VERSION = "9.9.9"
_TAG = f"v{_VERSION}"
_ASSETS = [
    f"stenographer-{_VERSION}-linux-x86_64.tar.gz",
    f"stenographer-{_VERSION}-linux-aarch64.tar.gz",
    f"stenographer-{_VERSION}-py3-none-any.whl",
    f"stenographer-{_VERSION}.tar.gz",
    "SHA256SUMS",
    "quick-install.sh",
]
# Models the release endpoint: a POST or PATCH sets the draft flag, and an upload
# adds the assets that the next read reports. A write answers with the release
# unless the caller filters it down to the ID. PUBLISH_REFUSED leaves a release a
# draft.
_GH = r"""#!/bin/bash
printf '%s\n' "$*" >> "$GH_LOG"
release() {
    jq -n --arg tag "$PLANNED_TAG" --arg sha "$GITHUB_SHA" \
        --argjson draft "$(cat "$DRAFT_STATE")" --rawfile uploaded "$UPLOADED" \
        '{draft: $draft, tag_name: $tag, target_commitish: $sha,
          assets: ($uploaded | split("\n") | map(select(. != "")) | map({name: .}))}'
}
case "$*" in
    "api --paginate --slurp "*) echo '[[]]' ;;
    "api -X POST "*|"api -X PATCH "*)
        for argument in "$@"; do
            case "${argument}" in
                draft=true) echo true > "$DRAFT_STATE" ;;
                draft=false) [[ -n "$PUBLISH_REFUSED" ]] || echo false > "$DRAFT_STATE" ;;
            esac
        done
        case " $* " in
            *" --jq .id "*) echo 42 ;;
            *) release ;;
        esac
        ;;
    "release upload "*)
        shift 3
        for path in "$@"; do
            name=$(basename "${path}")
            [[ "${name}" == "$LOSE_UPLOAD" ]] || echo "${name}" >> "$UPLOADED"
        done
        ;;
    "api repos/owner/name/releases/42") release ;;
    *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
"""
# Stands in for .venv/bin/python running release_guard.py: writes the planned release.
_GUARD = r"""#!/bin/bash
while [[ "$1" != "--github-output" ]]; do shift; done
{
    echo "tag=$EXPECTED_TAG"
    echo "version=$EXPECTED_VERSION"
    echo "previous_tag=$EXPECTED_PREVIOUS_TAG"
    echo "previous_commit=$EXPECTED_PREVIOUS_COMMIT"
    echo "draft_id=$PLANNED_DRAFT_ID"
} >> "$2"
"""


def _publish_step_script() -> str:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    step = workflow[workflow.index("- name: Final guard") :]
    step = step[: step.index("- name:", 1)]
    body = step[step.index("run: |") + len("run: |") :]
    return textwrap.dedent(body).replace("${{ inputs.bump }}", "patch")


def _run_publish_step(
    tmp_path: Path, *, draft_id: str = "", lose_upload: str = "", publish_refused: str = ""
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    commands = tmp_path / "commands"
    commands.mkdir()
    gh = commands / "gh"
    gh.write_text(_GH)
    git = commands / "git"
    git.write_text("#!/bin/sh\n")
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(_GUARD)
    for stub in (gh, git, python):
        stub.chmod(0o755)
    (tmp_path / "uploaded").touch()
    (tmp_path / "draft-state").write_text("true\n")
    (tmp_path / "gh-log").touch()
    result = subprocess.run(
        ["bash", "-e", "-c", _publish_step_script()],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "owner/name",
            "GITHUB_SHA": _SHA,
            "RUNNER_TEMP": str(tmp_path),
            "GH_LOG": str(tmp_path / "gh-log"),
            "DRAFT_STATE": str(tmp_path / "draft-state"),
            "UPLOADED": str(tmp_path / "uploaded"),
            "LOSE_UPLOAD": lose_upload,
            "PUBLISH_REFUSED": publish_refused,
            "PLANNED_TAG": _TAG,
            "PLANNED_DRAFT_ID": draft_id,
            "EXPECTED_TAG": _TAG,
            "EXPECTED_VERSION": _VERSION,
            "EXPECTED_PREVIOUS_TAG": "v9.9.8",
            "EXPECTED_PREVIOUS_COMMIT": _PREVIOUS_COMMIT,
        },
        capture_output=True,
        text=True,
    )
    return result, (tmp_path / "gh-log").read_text().splitlines()


def test_a_new_release_gets_generated_notes_and_publishes_after_every_upload(
    tmp_path: Path,
) -> None:
    result, calls = _run_publish_step(tmp_path)

    assert result.returncode == 0, result.stderr
    create = next(call for call in calls if call.startswith("api -X POST"))
    assert "generate_release_notes=true" in create
    assert "draft=true" in create
    assert "body" not in create
    upload = next(i for i, call in enumerate(calls) if call.startswith("release upload"))
    assert all(f"release/{name}" in calls[upload] for name in _ASSETS)
    publish = next(i for i, call in enumerate(calls) if "draft=false" in call)
    assert upload < publish
    assert calls[publish].startswith("api -X PATCH")
    # A failed read after publication would strand the release and its site deploy.
    assert publish == len(calls) - 1


def test_a_retry_refreshes_the_draft_and_leaves_its_notes_alone(tmp_path: Path) -> None:
    result, calls = _run_publish_step(tmp_path, draft_id="42")

    assert result.returncode == 0, result.stderr
    assert not any(call.startswith("api -X POST") for call in calls)
    refresh = next(call for call in calls if call.startswith("api -X PATCH"))
    assert "draft=true" in refresh
    assert "generate_release_notes" not in refresh
    assert "body" not in refresh
    assert any("draft=false" in call for call in calls)


def test_a_draft_missing_an_asset_is_never_published(tmp_path: Path) -> None:
    result, calls = _run_publish_step(tmp_path, lose_upload="quick-install.sh")

    assert result.returncode != 0
    assert not any("draft=false" in call for call in calls)


def test_a_publish_response_that_is_still_a_draft_fails_the_run(tmp_path: Path) -> None:
    result, calls = _run_publish_step(tmp_path, publish_refused="1")

    assert result.returncode != 0
    assert any("draft=false" in call for call in calls)


def test_the_install_script_is_attested_but_not_listed_in_the_checksums() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    checksums = workflow.index('sha256sum "${artifacts[@]}" > SHA256SUMS')
    copy = workflow.index("cp scripts/quick-install.sh release/quick-install.sh")
    attest = workflow.index("uses: actions/attest@")
    assert checksums < copy < attest


def test_the_site_deploy_starts_after_publishing_with_a_permission_on_that_job_only() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    assert workflow.index("-F draft=false") < workflow.index(
        'gh workflow run pages.yml --ref main -f ref="${TAG}"'
    )
    assert workflow.count("actions: write") == 1
    assert workflow.index("name: create or refresh draft release") < workflow.index(
        "actions: write"
    )


def test_draft_refresh_never_retargets_the_existing_release() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    patch = workflow.index("gh api -X PATCH")
    create = workflow.index("gh api -X POST", patch)
    target = workflow.index('-f "target_commitish=${GITHUB_SHA}"')
    assert target > create


def test_every_release_guard_call_checks_the_draft_target_commit() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    calls = workflow.split("scripts/release_guard.py")[1:]
    assert len(calls) == 3
    for call in calls:
        lines = call.splitlines()
        end = next(i for i, line in enumerate(lines) if not line.rstrip().endswith("\\"))
        command = "\n".join(lines[: end + 1])
        assert '--target-commit "${GITHUB_SHA}"' in command
        assert "--skip-" not in command
