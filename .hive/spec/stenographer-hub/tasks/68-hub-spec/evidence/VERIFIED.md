# VERIFIED — 68-hub-spec

Verifier: independent re-run on 2026-10-20 at commit `60a5308` on
`task/68-hub-spec`. The worktree has no `.venv`; commands used
`/home/penguin/source/stenographer/.venv/bin` with `PYTHONPATH=src`
(`import stenographer` resolved to this worktree's `src/`).

| Item | Check | Result |
| --- | --- | --- |
| R1 / V1 | `.hive/spec/stenographer-hub/README.md` compared with the goal (decisions 1–15), `overrides/tui-input-first-class.md`, the plan review, and the briefs of 54–66 | pass |
| R2 / V2 | Git allowlist, sdist, wheel, PyInstaller exclusion | pass |
| R3 / V3 | `docs/building.md` line; `AGENTS.md` unchanged | pass |
| R4 | Evidence in `.hive/spec/stenographer-hub/tasks/68-hub-spec/evidence/` | pass |
| Gate | ruff check, ruff format, pytest, `--help` | pass |

## R1 — spec content

- Decisions 1–15 match the goal file. Decision 1's "without a TTY it prints
  help" comes from the plan review (line 16).
- The input rule is included, with these stenographer details: a quit prompt
  only while recording, `ctrl+c` twice exits, and `q` types in text input.
- The accepted assumptions are all present: soundfile, and system `ffmpeg`
  through a pipe instead of PyAV, with a Doctor warning; the recent-line
  context opt-in; the 1.08 GB corpus consent; the 5.65 h four-speaker
  recording, never committed; `live` flags; `config.toml.bak-<time>`; Doctor
  warnings; `pw-play`.
- The task table matches `hive task list` and each brief's "Depends on". The
  briefs number tasks 01–12, which map to 54–65. 54, 57, and 60 are verified
  (landed); 55 and 58 are assigned (running). `tui-input-first` is listed as
  pending with no ID.
- The design-board path is named and the boards are not copied.
  `git ls-files .hive` lists only the README, the brief, and evidence.
- No transcript text. The README has no session quotes (the goal's quoted
  phrases were left out).

## R2 — allowlist and build

```text
$ git check-ignore -v --no-index .hive/spec/stenographer-hub/README.md .hive/tmp/x .hive/other
.gitignore:10:!/.hive/spec/**   .hive/spec/stenographer-hub/README.md
.gitignore:8:/.hive/*           .hive/tmp/x
.gitignore:8:/.hive/*           .hive/other
```

- `pyproject.toml` is unchanged since `033be49`. Hatch's exclude starts with
  `"*"` and has no `.hive` exception. `tests/` and `scripts/` have no
  Git/Hatch allowlist test.
- `python -m build --sdist --wheel`: both built. The sdist has 637 paths, 0
  of them `.hive`. The wheel has 0 `.hive` paths.
  `scripts/verify_distributions.py <dist> 0.0.0+source` exited 0.
- `pyinstaller packaging/stenographer.spec` (scratch dist/work paths): build
  complete. 0 `.hive` paths in the output tree and in `Analysis-00.toc`. The
  bundled `stenographer --help` exited 0.

## R3 — docs

`git diff 033be49 -- docs/building.md` adds the `.hive/spec/` sentence
(tracked, not shipped by Hatch or PyInstaller) and the repository-only
exception to the mirrored-allowlist rule. `AGENTS.md` has no diff.

## Gate

```text
ruff check .                  All checks passed!
ruff format --check .         592 files already formatted
pytest -m "not integration"   2555 passed, 2 skipped, 6 deselected
stenographer --help           exit 0
```

The 2 skips need public speaker clips that are absent.
