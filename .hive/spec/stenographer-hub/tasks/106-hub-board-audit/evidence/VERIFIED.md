# VERIFIED — 106 hub-board-audit

Verifier: independent re-run on branch `task/106-hub-board-audit` at 98ca1b6.
The worktree has no `.venv`. Tools came from
`/home/penguin/source/stenographer/.venv/bin` with `PYTHONPATH=$PWD/src`;
`import stenographer` resolved to this worktree's `src/`. Textual 8.2.8.

| Item | Result | What the verifier ran and saw |
| --- | --- | --- |
| V1 Pilot renders | pass | Own pilot script (outside the repo, now deleted) reused the hub test fakes (`tests/cli/hub/test_*.py` FakeServices, FakeFilesEngine, SessionStore fixtures, fake DoctorReport) at `run_test(size=(150, 45))`. It rendered all 8 states and saved SVG and plain text. Each layout matched the committed render: same sidebar, Live engine/REC/MIC/SYSTEM ASCII blocks, `time \| MIC \| SYSTEM` split header, borderless Files and Sessions panes, Config `Groups:` line, Setup single list, and Doctor single report. Only fixture data differed. All 16 committed files exist. No microphone, capture, model load, `live` or `run`. Note: the verifier's Live, Files and Sessions runs used the hub's default Doctor probe (the same read-only probe that the unit tests use); it did not open audio. |
| V2 Screen comparison | pass | Opened all 7 boards. Spot-checked at least 3 gaps per screen against the board lines and the code: Live L-1, L-4, L-7 (`1-6 sections` missing, `app.py:323-324`), LS-1, LS-2; Files F-4, F-5, F-6, F-7 (`e folder` vs `e open result`); Sessions S-1, S-2, S-4, S-5; Config C-1 (`2 unsaved` vs yes/no, `config_view.py:216-220`), C-2, C-3; Setup U-1, U-3, U-5 (`setup_wizard.py:61-89`); Doctor D-1, D-2 (board `grid-template-columns: repeat(2, …)`), D-3, D-7. All the citations that the verifier sampled point at the code that is described. Gap claims hold. |
| V2a Widget-CSS claim | pass (confirmed) | Minimal reproduction in Textual 8.2.8: a `Widget` subclass with class `CSS = "… { border: round red; width: 40 }"` rendered with `border_top=('', …)`, `width=None`, and full size. The same rules in `DEFAULT_CSS` applied (`round`, width 40). In the hub pilot, every child of `FilesPanel` and `SessionsPanel` had an empty `border_top`. Both are `Vertical` subclasses that use `CSS =` (`files_view.py:35`, `sessions_view.py:17`). The claim is correct. |
| V3 Background inventory | pass | Grep of `src/stenographer/cli/hub` and `cli/live/rename_dialog.py` for `background`, `$surface`, `$panel`, `reverse`, `on <colour>` and Rich styles found exactly `app.py:95`, `dialogs.py:27,34`, `config_dialog.py:21,28` and `rename_dialog.py:26`. All are in the inventory. The Textual defaults that the inventory cites (`app.py:305-312`, `screen.py:174-192`, `screen.py:2164-2171`) match the installed source. No Rich `on`/`reverse` style is in hub code. |
| V4 Proposed fix split | pass | One task per screen, Live first. Each row has gap IDs and names the gaps that depend on task 107 (`hub-no-background`, which exists: `hive task show 107-hub-no-background`). |
| V5 Gate and scope | pass | `ruff check .`: all checks passed. `ruff format --check .`: 656 files already formatted. `pytest -m "not integration"`: 2643 passed, 2 skipped (absent public audio fixtures), 6 deselected, 0 failed. `stenographer --help`: exit 0. `git diff --name-only 6e80174 HEAD` has 0 paths outside this task's spec folder. No source, test or doc file changed. |

## Corrections (recorded, not failures)

- **C-4 is not blocked.** The user chose recent-line context OFF on
  2026-10-20 (task 56). No `context from recent lines` setting is expected.
  C-4 is therefore `ok` (board row out of date), not "missing; blocked by
  decision 12". The fix split's Config note "C-4 waits for the decision-12
  benchmark and user choice" is obsolete too.
- Minor omission: the Config board's group list includes `live` and has no
  `delivery`. The hub shows `hotkey audio asr refine feedback analytics
  delivery`. `gaps.md` C-2 records only the selector layout, not this group
  list difference. The Config fix task should check it.
- Format count: the verifier saw 656 formatted files; V5 records 655. Both
  runs passed.
