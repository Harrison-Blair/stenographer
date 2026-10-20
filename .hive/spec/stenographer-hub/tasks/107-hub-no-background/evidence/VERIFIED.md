# VERIFIED — 107-hub-no-background (re-verification after repair 82efb22)

Verifier run on `82efb22` (base `6e80174`, pre-repair `c9d7955`). Tools:
`/home/penguin/source/stenographer/.venv/bin/` with `PYTHONPATH=<worktree>/src` (the worktree has no
`.venv`; `stenographer.__file__` resolved to the worktree source). Red runs and mutations ran in
temporary detached worktrees, removed afterwards. No microphone, audio, `live`/`run`, model download or
integration test was used.

| Item | Result | Observation |
| --- | --- | --- |
| V1 regression tests | pass | Green: `tests/cli/hub/test_no_background.py` 7 passed. Red at base `6e80174` (HEAD test file): 4 failed, 3 passed. The background test reports painted cells (`#0b0d12` in Live idle/recording/split, `#1b1b1b` in `stenographer live`); the cursor, scrollbar-thumb and selected-marker tests also fail. The three alignment tests pass at base, as expected. Red at `c9d7955`: 5 failed (Files `../` alignment, Setup indent, queue error indent, Input cursor, scrollbar thumb). |
| V1 scrollbar exception (user decision) | pass | `NO_BACKGROUND_CSS` keeps `scrollbar-size: 1 1`, with transparent tracks and corners and `scrollbar-color: #5fd7ff`. On Files with 50 files, ScrollBar segments render as `default on default` (track) and `reverse #5fd7ff on default` (thumb). The test exempts only reverse segments whose cells all belong to a `ScrollBar`, and asserts that thumb cells > 0. Mutations: `#sidebar { background: #5fd7ff; }` fails the test (`'╭' has Color('#5fd7ff')`); accent scrollbar *track* fails it (`Files scrolling, row 6: ' ' has Color('#5fd7ff')`). |
| V1 Input cursor | pass | `.input--cursor` is `background: transparent; color: #5fd7ff; text-style: bold underline`. The test checks the underline, accent colour, no bgcolor and no reverse on a blank cursor. Mutation `bold underline` → `bold reverse` fails 2 tests. |
| V1 alignment vs base | pass | Directory rows `     {name}/` give `       ../` (base alignment); unselected Setup steps use `selectable=selected` (`○ 2 microphone`); queue errors are `  {error}`. Each test fails at `c9d7955` and passes at head. |
| V2 SVG evidence | pass | `before-list.svg`: HubApp Files screen with base marker style (`> 2 Files`, `▸ [ ] sample.wav`), 334 filled rects. `after-list.svg`: Files with `▶ 2 Files` / `▶ [ ] sample.wav`, 1 filled rect (window chrome). Live and standalone-live before/after: 447/108 → 1 filled rect. |
| Docs | pass | `docs/hub.md`: "Scrollbars stay visible. Their thin accent-colour thumbs are the only exception to the no-background rule; tracks and corners stay transparent." |
| Layout rule for shared CSS | **fail** | The CSS block exists once, in `src/stenographer/cli/no_background_css.py`, imported by `cli/hub/app.py` and `cli/live/app.py`. `tests/test_architecture.py` passes (4 passed), but that test does not check the `cli/` root. AGENTS.md says production code lives in `cli/<command>/`. The only other `cli/` root modules are the entry point and parser (`entry.py`, `parser.py`, `__main__.py`). Code shared between commands lives in `cli/shared/`: docs/architecture.md names `cli/shared/`, and `cli/shared/terminal.py` is shared by `setup` and `sounds`. The module should move to `cli/shared/` (e.g. `cli/shared/no_background_css.py`). |
| V3 gate | pass | `ruff check .` All checks passed; `ruff format --check .` 660 files already formatted; `pytest -m "not integration"` 2650 passed, 2 skipped, 6 deselected; `stenographer --help` exit 0. |

Verdict: **fail**. The only failing item is the layout of the shared CSS module. Every behavioural item passes.
