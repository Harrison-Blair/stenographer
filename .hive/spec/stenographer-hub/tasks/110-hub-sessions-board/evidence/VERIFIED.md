# VERIFIED — 110 hub-sessions-board

Verifier run 1, at `cba67fe`. Base = `d8ad650` (dev). Environment:
`/home/penguin/source/stenographer/.venv` with `PYTHONPATH=src` (the worktree has
no `.venv`). Fake services only. No microphone, model, `live` or `run`.

| Item | Result | Observation |
| --- | --- | --- |
| V1 widget CSS regression (red/green) | pass | Base + new tests: `test_sessions_panels_render_borders_and_board_proportions` fails with `assert '' == 'round'` (4 of 5 session tests fail at base). Task head: 5 passed. |
| V2 storage card and list panel | pass | Sidebar card shows `storage / 2 sessions / 696.0 B audio`. The list has its own round border. The selected row is `▶`, bold accent, with no fill. |
| V3 session detail and speaker chips | **fail** | (a) Under the meters, the rule is one character wide (`─`) when Sessions first opens. In `_detail_text`, `separator_width = region.width - 6` is read before layout, so it gives `max(1, …)`. The rule reaches full width only after the selection changes (seen after a down then up key press). The board shows a full-width rule. (b) The panel titles `saved` and the session ID have no `border-title-color` or style. They show in the dim border colour `#3a4150` and can almost not be read. The board shows readable titles. Task 108 fixed the same defect for Live. (c) Label status is on its own line in the panel body. The board puts `labels: re-labelled at stop` at the right of the title row. Not reported in visual-check.md, which says "Matches". |
| V4 existing behaviour + no-background | pass | `pytest tests/cli/hub`: 68 passed. No background fill in my capture. |
| V5 pilot captures + board comparison | **fail** | I made my own capture at 150x45 with the test fixture, which has transcript lines. The transcript lines render: time (dim), speaker (bold colour), text. The view can show a transcript. But the committed `after-sessions.*` captures contain no transcript lines and show the 1-char rule. visual-check.md calls the panel titles and label status "Matches". Defects V3 (a)–(c) do not show in its comparison. The meters are flat full blocks: the fixture audio is a constant 0.1 signal, so this is acceptable. |
| V6 gate | pass | ruff check: all passed. format: 693 files formatted. pytest `-m "not integration"`: 2663 passed, 2 skipped, 6 deselected. `stenographer --help`: printed. |

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Sessions.png`.

## Repair needed

1. Make the transcript rule full width on the first render (and on resize). Add a
   pilot test that fails at the current head.
2. Make the `saved` and session-ID border titles readable: bold, with a non-dim
   colour, as task 108 did for Live. Add a test for it.
3. Put the label status at the right of the detail title row, as on the board,
   or record the reason for the difference in visual-check.md.
4. Re-capture the after screen with synthetic transcript lines visible, so the
   evidence shows the rule and the speaker labels.
