# 117-changelog-v0150 verification

Verifier: second independent re-run on 2026-10-20 against `de2e238` (base
`4720443`), after the repair of the first verification's defects. The
worktree has no `.venv`, so `/home/penguin/source/stenographer/.venv` was
used with `PYTHONPATH=src` (`stenographer.__file__` resolved to this
worktree's `src/`).

| Item | Result | Observation |
| --- | --- | --- |
| V1 release-note check | pass | Base `CHANGELOG.md` (`git show 4720443:CHANGELOG.md`): `release notes check failed: no release entry for v0.15.0`, exit 1. HEAD: `release note found: v0.15.0 (2026-10-20)`, exit 0. |
| V2 changelog tests | pass | HEAD test file with base `CHANGELOG.md`: `test_repository_changelog_covers_every_authored_release_note` failed (1 failed, 39 passed). HEAD: 40 passed. The one-line test change adds `v0.15.0` to the exact version list, as each earlier release did. |
| V3 gate | pass | `ruff check .`: All checks passed!; `ruff format --check .`: 734 files already formatted; `pytest -m "not integration"`: 2694 passed, 2 skipped, 6 deselected; `stenographer --help`: exit 0. |
| Heading / link conventions | pass | Empty `## [Unreleased]` above `## [v0.15.0] - 2026-10-20`, as at the v0.14.0 tag. The file has no link-reference definitions. Only `CHANGELOG.md`, the test, and evidence files changed. |
| Bullets vs code (`git log v0.14.0..HEAD`) | pass | See below. |

## Bullet review

Both defects from the first verification are repaired:

1. The `### Fixed` section is gone. The behaviour of the three hub/session
   fixes (scrolling Live transcript, interrupted rows within the list,
   readable text from an incomplete final row) is now described in the Added
   bullets as features of the new hub, which does not imply a v0.14.0 bug.
2. The "matches the terminal layouts" bullet is replaced by observable
   behaviour: no painted background (`fb6f861`, `82efb22`) and a bold `▶`
   selection marker (`cli/hub/selection.py`: `"▶ "` with `_ACCENT_BOLD`).

New claims checked against code and commits: Files speaker colours
(`6621bf5`), `soundfile`-unreadable formats decoded through system FFmpeg
(`lib/platform/linux/ffmpeg_decoder.py`, `5d778d4`) with the Doctor warning
(`8be2796`, `bb0a169`), transcript revisions kept on reprocessing
(`211ad36`, `lib/sessions/store.py`), Doctor fixes shown
(`cli/hub/doctor_view.py`: `Fix: ...`), unique batch speaker labels
(`ee05019`). Earlier-confirmed items (relabel thresholds, default model,
export formats, Windows removal) are unchanged. Nothing overstated; no
missing user-visible change found; no transcript or recording content.

Spelling (non-blocking): the new bullet uses "colour" while the same entry
uses "colors". The file is already mixed: the v0.13.x entry spells "colour"
twice ("Loading colour", "Refining colour"), while most prose uses US
spelling ("behavior"). The release-note check and tests do not depend on
it. It is a style nit, not a defect against the brief; changing it to
"color" is optional.
