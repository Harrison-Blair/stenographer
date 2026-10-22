# Task: changelog-v0160 — turn [Unreleased] into the v0.16.0 entry

| Item | Value |
| --- | --- |
| Tier | small |
| Grant | `2026-10-21: stenographer delivery on dev` (merge to dev only); release grant `2026-10-22: stenographer release v0.16.0` |
| Base | origin/dev 32f7806 |
| Pattern | task 117 (`.hive/spec/stenographer-hub/tasks/117-changelog-v0150/brief.md`) |

## Overview

The user approved release v0.16.0 (minor bump). The `draft release` workflow will
run on main after the owner merges dev to main. Its preflight requires a CHANGELOG
entry for v0.16.0. Prepare that entry on dev.

## Requirements

1. Rename `## [Unreleased]` to `## [v0.16.0] - 2026-10-22`, in the same heading form
   as earlier entries. Leave an empty `## [Unreleased]` heading above it only if the
   file's convention, `docs/building.md` and `scripts/release_notes.py` expect it
   (check what they accept; earlier releases are the guide).
2. The entry must be true for origin/dev now. Read `git log v0.15.0..origin/dev`. The
   current text covers only Bark Pro. Add the other user-visible changes since
   v0.15.0, at least:
   - the hub Files browser opens in your recordings folder (`<data_dir>/sessions`)
     and falls back to your home folder when it is missing (cc9ffde);
   - optional speaker diarization for the microphone in Live
     (`stenographer.live.diarize_mic`, default off, `--diarize-mic/--no-diarize-mic`,
     Room N labels; 6e7e8ad with its fix 7fdcff6), and its Sessions re-diarize effect
     (check docs/usage.md and docs/live.md for the true wording).
   Check every claim in the Bark text against the code and docs on dev (the download
   size, 10 GiB disk, about 10.2 GiB RAM, removed keys, removed surfaces).
   The user's 7b4700f (byte-identical encoder conversion across CPUs): Bark Pro was
   never released, so this is part of the new feature, not a Fixed item. Mention it
   only if the user sees it (for example, the download works the same on any CPU).
   FIX.md was temporary and is gone; do not mention it.
3. Keep the file's shape: synopsis, then `### Added`, `### Removed`, `### Fixed` in that
   order, omitting empty sections; observable behaviour only, no planning or commit
   lists, second person where the file uses it. No transcript text or recording
   content. Update link-reference definitions if the file uses them.
4. Proof: `.venv/bin/python scripts/release_notes.py check 0.16.0 CHANGELOG.md` exits 0
   (record the output), and fails at the base commit (record that too). Run the
   release-notes tests in `tests/` and the full AGENTS.md gate.
5. Change only `CHANGELOG.md` (and a test only if one must change). Commit
   `docs(changelog): add the v0.16.0 release notes`, no trailers, push the task
   branch, `hive task complete`.

Evidence folder: `.hive/spec/bark-pro-asr/tasks/57-changelog-v0160/evidence/`.

## Rules

- Your worktree has no `.venv`. Agents never create the repo venv: ask the manager
  through `hive inbox send --to manager-stenographer` so the user runs
  `! python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'` in your pane. Write
  the entry meanwhile. Ask all questions through the inbox.
- Never run any git stash command (stash@{0} is the user's WIP). Never run sudo.
- Do not push dev or main, open a PR, run a workflow, or touch tags.
- Never signal a process or close a pane you did not start. Never work in wBC.
- Gate before `hive task complete`, zero failures, in the worktree `.venv`:
  `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`,
  `.venv/bin/pytest -m "not integration"`, `.venv/bin/stenographer --help`.
  Known timing flakes: tests/cli/hub/test_sessions.py::test_session_playback_toggles_and_jobs_run_without_blocking_navigation
  and tests/cli/hub/test_app.py::test_pilot_lifecycle_worker_finishes_after_hub_screen_unmount_without_failure;
  if one fails, rerun it alone 5 times and record that.
