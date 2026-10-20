# Task: changelog-v0150 — add the v0.15.0 entry to CHANGELOG.md

| Item | Value |
| --- | --- |
| Tier | small |
| Grant | `grants.md 2026-10-20 v0.15.0 changelog and retry` (merge to `dev` only) |

## Overview

The `draft release` workflow (bump minor, version 0.15.0) failed at release
preflight: `release notes check failed: no release entry for v0.15.0`. The
release notes for this release already exist under `## [Unreleased]` in
`CHANGELOG.md` on `dev`.

## Requirements

1. Turn the current `## [Unreleased]` content into the v0.15.0 entry, using
   the same heading form as earlier entries (`## [v0.15.0] - 2026-10-20`), and
   leave an `## [Unreleased]` heading in place above it if earlier releases
   did (follow the file's and `docs/building.md`'s conventions; check
   `scripts/release_notes.py` for what it accepts).
2. Check the entry covers the user-visible changes merged since v0.14.0
   (`git log v0.14.0..origin/dev`): the hub and its screens, the board-match
   and no-background work, the default ASR model change, diarization changes,
   Windows removal, and any fix that changes behaviour. Add any missing
   user-visible item; keep the file's style (synopsis, then `### Added`,
   `### Removed`, `### Fixed`; observable behaviour only, no internal
   planning, no commit lists). No transcript text or recording content.
3. Any link-reference definitions at the bottom of the file (if the file
   uses them) are updated consistently.
4. Proof: `.venv/bin/python scripts/release_notes.py check 0.15.0 CHANGELOG.md`
   exits 0 (record the output), and fails at the base commit (record that
   too). Also run any changelog tests in `tests/` and the full gate from
   AGENTS.md.
5. Change only `CHANGELOG.md` (and a test only if one must change). Commit
   with a conventional message (`docs(changelog): ...`), no trailers, push,
   `hive task complete`.

Evidence folder: `.hive/spec/stenographer-hub/tasks/117-changelog-v0150/evidence/`.

Never signal a process or close a tab, pane or workspace that you did not
start. Never work in workspace wBC (the hive session).
