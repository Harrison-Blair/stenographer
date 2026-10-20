# VERIFIED — 42-release-notes-0-14-0

Second verifier run on 2026-10-19 at `27db0ab`. The first run (at `c6a6d1e`)
failed because the PipeWire routing check was listed under `### Fixed` for a
command that first ships in v0.14.0. Commit `27db0ab` folds it into the live
bullet and removes `### Fixed`.

The worktree has no `.venv`, so the verifier used a temporary `.venv` symlink
to `/home/penguin/source/stenographer/.venv` and `PYTHONPATH="$PWD/src"`.
`stenographer.__file__` resolved to this worktree's `src/`. The symlink was
removed after the run.

| Item | Result | Observation |
| --- | --- | --- |
| A1 red: `check 0.14.0` on `CHANGELOG.md` from `4655773` | pass | `release notes check failed: no release entry for v0.14.0`, exit 1 |
| A1 green: `check 0.14.0 CHANGELOG.md` | pass | `release note found: v0.14.0 (2026-10-19)`, exit 0 |
| A1 `extract 0.14.0 CHANGELOG.md` | pass | exit 0. Output is byte-identical to the block in V2.md (`diff` empty) |
| A2 commit map (V1.md) | pass | Each bullet maps to commits. Every non-internal commit in `origin/main..4655773` is covered |
| A3 `ruff check .` | pass | `All checks passed!` |
| A3 `ruff format --check .` | pass | `575 files already formatted` |
| A3 `pytest -m "not integration"` | pass | `2545 passed, 2 skipped, 6 deselected` (skips: absent public speaker clips) |
| A3 `stenographer --help` | pass | exit 0. The usage lists `live` |
| A4 no tag, push to main, PR, or workflow | pass | No tag on HEAD. Branch has `c6a6d1e`, `7ccfdc2`, `27db0ab` on top of `4655773` |
| R1 single v0.14.0 entry, empty `[Unreleased]` above | pass | `[v0.13.2]` section removed; `## [Unreleased]` is empty |
| R3 live known limit | pass | Over-split, session `20261020T011218Z`, 2–3 voices → 6 labels, `r` merge, 0 failed phrases all stated |
| R4 section order | pass | Synopsis, `### Added`, `### Removed`; no empty `### Fixed` |
| R4 bullet accuracy (spot checks) | pass | Session dirs `0o700` (`session_writer.py`); `available()` returns `(False, reason)` when routing cannot be verified (`system_audio.py`); `r` binds "Rename speaker" (`cli/live/app.py`); secret items via `x-kde-passwordManagerHint` (`clipboard.py`); doctor `clipboard restore` line (`doctor/report.py`); Agent has no semantic check (`7f196b6`) |
| Previous fail: routing under `### Fixed` | pass | Now part of the live bullet under `### Added` |
| R6 only CHANGELOG + evidence changed | pass (noted) | `tests/test_release_notes.py` also changes one line (`"v0.13.2"` → `"v0.14.0"`) in the expected-version list. The gate fails without it, as the first run showed |

## Verdict

Pass. Every item passes.
