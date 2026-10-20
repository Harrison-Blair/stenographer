# VERIFIED — 42-release-notes-0-14-0

Verifier run on 2026-10-19 at `c6a6d1e`. The worktree has no `.venv`, so the
verifier used a temporary `.venv` symlink to
`/home/penguin/source/stenographer/.venv` and `PYTHONPATH="$PWD/src"`.
`stenographer.__file__` resolved to this worktree's `src/`.

| Item | Result | Observation |
| --- | --- | --- |
| A1 red: `check 0.14.0` on the changelog at `4655773` | pass | `release notes check failed: no release entry for v0.14.0`, exit 1 |
| A1 green: `check 0.14.0 CHANGELOG.md` | pass | `release note found: v0.14.0 (2026-10-19)`, exit 0 |
| A1 `extract 0.14.0 CHANGELOG.md` | pass | exit 0. The output is byte-identical to the block in V2.md (`diff` empty) |
| A2 commit map (V1.md) | pass | V1.md maps each bullet to commits |
| A3 `ruff check .` | pass | `All checks passed!` |
| A3 `ruff format --check .` | pass | `575 files already formatted` |
| A3 `pytest -m "not integration"` | pass | `2545 passed, 2 skipped, 6 deselected` |
| A3 `stenographer --help` | pass | exit 0. The usage lists `live` |
| A4 no tag, push to main, PR, or workflow | pass | Branch has one commit `c6a6d1e` on top of `4655773` |
| R6 only CHANGELOG + evidence changed | pass (see test note) | The diff also changes `tests/test_release_notes.py` (one line) |
| Manager claim 1: Agent semantic guard | pass | The bullet is correct (see below) |
| Manager claim 2: `### Fixed` live bullet | **fail** | It misleads (see below) |

## Test file change

`tests/test_release_notes.py::test_repository_changelog_covers_every_authored_release_note`
asserts the exact list of versions in `CHANGELOG.md`. With the test from
`4655773` (`"v0.13.2"`) and the new changelog it fails:
`At index 0 diff: 'v0.14.0' != 'v0.13.2'`. With the commit's one-line change
(`"v0.14.0"`) it passes (40 passed). The gate cannot pass without this change,
so the change is required.

## Manager claim 1 — Agent output guard

On this branch, `refined_text()` in `src/stenographer/lib/refine/response.py`
sends `RefineProfile.AGENT` replies only to `basic_format()`. That function
refuses only empty output, an empty input, or output that is still wrapped
after one quote/fence pair is removed. The length-ratio and numeral checks in
`guard()` apply to General only. Commit `7f196b6` ("trust Agent rewrites
without semantic checks") removed the semantic guard (−471 lines in
`response.py`). `docs/refine.md` agrees: "Agent has no length-ratio or semantic
checks" and "Agent does not check for semantic changes". The
`RefineRejectedError` in `errors.py` is the refusal for `basic_format`/`guard`.
It is not a meaning check. The old v0.13.2 text described the removed guard.
The new bullet ("the app does not check that the rewrite preserves it") is
correct.

## Manager claim 2 — `### Fixed` bullet (finding, blocking)

The only `### Fixed` bullet says: "Live checks that PipeWire links each capture
input to the current default sink's monitor before recording, and rejects
misrouted capture." Its source commits (`60faa9b`, `58c5030`) fix
`stenographer live`. That command first ships in this same v0.14.0 release
(v0.13.1, the last published release, has no `live`). A v0.14.0 reader cannot
have hit the bug. A `Fixed` entry tells them that something they had is now
repaired, so the bullet **misleads**. The brief folded the worker spawn fix
into the live entry "because live was never released before". The same reason
applies to this routing fix. Repair: move the routing check into the
`stenographer live` bullet as behaviour (for example, "Before recording system
audio, it checks that PipeWire routes capture from the default output's
monitor and refuses misrouted capture"), and drop the empty `### Fixed`
section. Then `check`/`extract` and the test must be run again.

## Verdict

Fail on manager claim 2. Every other item passes.
