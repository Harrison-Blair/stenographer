# 117-changelog-v0150 verification

Verifier: independent re-run on 2026-10-20 against `39e7761` (base
`4720443`). The worktree has no `.venv`, so
`/home/penguin/source/stenographer/.venv` was used with `PYTHONPATH=src`
(`stenographer.__file__` resolved to this worktree's `src/`).

| Item | Result | Observation |
| --- | --- | --- |
| V1 release-note check | pass | Base `CHANGELOG.md` (`git show 4720443:CHANGELOG.md`): `release notes check failed: no release entry for v0.15.0`, exit 1. HEAD: `release note found: v0.15.0 (2026-10-20)`, exit 0. |
| V2 changelog tests | pass | New test file + base `CHANGELOG.md`: `test_repository_changelog_covers_every_authored_release_note` failed (1 failed, 39 passed). HEAD: 40 passed. The test change is justified: the test asserts the exact list of changelog versions, so each release must add its version (v0.14.0 did the same). |
| V3 gate | pass | `ruff check` all passed; `ruff format --check` 732 files formatted; `pytest -m "not integration"` 2694 passed, 2 skipped (absent public speaker clips), 6 deselected; `stenographer --help` exit 0. |
| Heading / link conventions | pass | `## [Unreleased]` left empty above `## [v0.15.0] - 2026-10-20`, same as at the v0.14.0 tag. The file has no link-reference definitions. |
| Bullets vs code (`git log v0.14.0..HEAD`) | fail | See below. |

## Bullet review

Confirmed in code: relabel thresholds (`lib/live/relabel.py`: 0.20, 2.0 s,
15.0 s, 30.0 s, 2/3), the default model
`deepdml/faster-whisper-large-v3-turbo-ct2` (`assets/default_config.toml.in`,
`lib/config/models.py`), the Doctor FFmpeg check
(`lib/diagnostics/additional_checks.py`), the export formats
md/jsonl/srt/txt (`lib/sessions/exporter.py`), and Windows removal. No
user-visible change since v0.14.0 is missing; the ASR bench is a developer
script.

Defects:

1. **`### Fixed` overstates.** All three bullets fix code that did not exist
   in v0.14.0. `src/stenographer/cli/hub/` and `src/stenographer/lib/sessions/`
   are absent from the `v0.14.0` tree. `e6659d5` changes only
   `cli/hub/app.py`; `d00d2c9` changes only `cli/hub/sessions_view.py`;
   `c684d8f` changes only `lib/sessions/reader.py`. A reader would conclude
   that v0.14.0 had these bugs. Remove the section, or fold the behaviour into
   the Added bullets (for example, Sessions shows readable content from
   interrupted sessions).
2. **"Matches all six hub screens to their terminal layouts" is unclear.** The
   hub is new in this release, so it has no previous layout to match. The
   phrase describes the internal development step of matching private design
   boards, and a reader who did not see those boards cannot interpret it.
   Remove the bullet, or keep only the observable part (transparent
   backgrounds, so the terminal theme shows through) and put it in the first
   hub bullet.
