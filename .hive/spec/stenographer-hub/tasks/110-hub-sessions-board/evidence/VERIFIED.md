# VERIFIED — 110 hub-sessions-board

## Verifier run 2, at `c33a633`

Base = `d8ad650` (merge-base with dev). Environment:
`/home/penguin/source/stenographer/.venv` with `PYTHONPATH=src`. Fake services only. No
microphone, model, `live` or `run`. My capture: `verify-sessions.png` (150x45 pilot,
test fixtures: three sessions, one interrupted).
Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Sessions.png`.

| Item | Result | Observation |
| --- | --- | --- |
| V1 widget CSS regression (red/green) | pass | `tests/cli/hub/test_sessions.py` at HEAD against `src@d8ad650`: 8 failed, 1 passed (`assert '' == 'round'` for borders). At HEAD: 9 passed. |
| V2 storage card and list panel | **fail** | The sidebar card shows `storage / 3 sessions / 1.1 KB audio`. The list has its own round border with a bold `saved` title. The selected row uses `▶` and bold accent text with no fill. But the interrupted row wraps: `  2026-10-19 14:05  0:03  2 spk  ! interrupted` is 45 characters, the list content width is 40, and `interrupted` goes onto its own line under the row. This is in my capture and in the committed `after-sessions.png` (the manager saw it too). No test covers it. |
| V3 session detail and speaker chips | pass | Repair items from run 1 are fixed. Tests at HEAD against `src@cba67fe`: 7 failed, 2 passed (missing rule, title, and labels widgets; transparent title colour). At HEAD all pass. The rule fills the detail width on first render. Panel titles are bold, default foreground. The title row has the session ID and, right-aligned, `labels: live`. The transcript keeps `time  speaker  text` with two spaces (checked in `Text.plain`). In the PNG the speaker and text look joined (`Speaker 1first`). The cause is that rsvg-convert drops leading `&#160;` in the SVG. The app is correct. |
| V4 existing behaviour + no-background | pass | `pytest tests/cli/hub`: 72 passed. Removed assertions in `test_sessions.py` moved to the new widgets (`labels: re-labelled at stop`, transcript lines, storage in the sidebar card). None was dropped. `screen.get_style_at` over all 150x45 cells found no background colour. |
| V5 pilot captures + board comparison | **fail** | Panels, order, sidebar card, title row, talk-time chips, mic/sys rows, rule, transcript and key hints match the board in layout and content. Chip fills are overridden by task 107. But `visual-check.md` says the saved list panel "Matches", and the committed `after-sessions.png` shows the wrapped `! interrupted` row. |
| V6 gate | pass | `ruff check`: all checks passed. `ruff format --check`: 694 files already formatted. `pytest -m "not integration"`: 2667 passed, 2 skipped, 6 deselected. `stenographer --help`: printed. |
| Dev merge | **fail** | `origin/dev` is at `797ed0f` (task 112 merged). `git merge-tree HEAD origin/dev` gives a conflict in `src/stenographer/cli/hub/app.py`. |

## Repair needed

1. Merge `origin/dev` (`797ed0f`) into the task branch. Resolve the conflict in
   `src/stenographer/cli/hub/app.py`. Re-run the gate.
2. Keep each saved-session row on one line at 150x45, including `! interrupted`.
   For example, widen the list panel toward the board ratio, shorten the marker,
   or crop with no wrap. Add a pilot test that fails at the current head.
3. Re-capture `after-sessions.*` and fix the saved-list row in `visual-check.md`.

## Verifier run 1, at `cba67fe`

Failed V3 (rule width on first render, dim panel titles, label status placement)
and V5 (captures without transcript lines). The worker repaired these in `c33a633`.
Run 2 confirms the repair.
