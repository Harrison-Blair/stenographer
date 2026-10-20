# VERIFIED — task 108 hub-live-board

Verifier re-ran each item from the worktree root on 2026-10-20. Python tools
came from `/home/penguin/source/stenographer/.venv` with `PYTHONPATH=$PWD/src`
(the worktree has no `.venv`). Fake services only; no microphone, model,
`live`, `run`, or integration test.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red run | pass | dev (75971fa) code + new tests in a scratch worktree: 5 failed, 10 passed. `No nodes match '#live-rec'`, `No nodes match '#sidebar-card'`. |
| V1 green run | pass | Included in the full suite below; all hub tests pass. |
| V2 existing behaviour | pass | Full suite green, including task 107 no-background test and task 103 refresh guard. Independent check: 0 segments with a painted background in Live mixed at 150x45. |
| V3 before/after renders | pass | All 18 files present (svg/txt/png for idle, mixed, split, before and after). |
| V4 board comparison (brief req. 8, visual check) | **fail** | Independent re-render (`verifier-live-{idle,mixed,split}.png`) vs `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/StenoB.png` and `LiveSplit.png`. See differences below. |
| V5 gate | pass | ruff check: all passed; ruff format --check: 683 files formatted; pytest -m "not integration": 2655 passed, 2 skipped, 6 deselected; `stenographer --help` prints usage. |

## V4 differences (gap by gap)

| Gap | Verdict | Detail |
| --- | --- | --- |
| L-3 REC time | differs, not justified | Time is bold but normal size. `visual-check.md` says a larger time is impossible in Textual; Textual's `Digits` widget (present in this venv) renders large digits. Board shows a large time. |
| L-6 / LS-3 speaker labels | differs, misreported as "Matches" | Every label uses `#5fd7ff` (`live_view.py` `_mixed_table` and `_split_table`). Board gives each speaker its own colour (You cyan, Alice orange, Speaker 2 purple). Only the fill is overridden by the no-background rule; the distinct colours are not. |
| L-7 / LS-4 key hints | differs, not reported | The whole hint row is one style (`#a0a8b8`); keys are not marked. Board marks each key as a keycap; with the fill overridden, keys should still be distinguishable (for example bold accent key text). Board also shows `view: mixed / split` with the current view bold. |
| L-1 / L-2 sidebar title | differs, not reported | Border title `stenographer` inherits the dim border colour `#3a4150` and is nearly invisible; board shows it bold accent. The `transcript · …` caption is equally faint; board shows it legible. |
| L-5 SYSTEM heading | differs (worker noted) | `Default output monitor` wraps to a second line at 150 cols; board keeps source, state and device on one line. |
| Manager point (a) `MICon` | not a defect | SVG contains `&#160;on&#160;·…`; compositor text is `[m] MIC on · Default input`. The joined look is an rsvg font-metric artefact. |
| Manager point (f) broken corners | not a defect | Compositor text shows closed `╮`/`╯` corners; the gap is the same rsvg glyph artefact. |
| LS-1, LS-2 split columns and `·` | matches | Time column, captioned `MIC · what you said` / `SYSTEM · everyone else` in distinct colours, `·` in empty cells. |
| No painted background | matches | 0 painted segments; no-background test passes. |

## Verdict

Fail on V4: L-3, L-6/LS-3, L-7/LS-4 and the faint titles differ from the
boards, and `visual-check.md` marks L-3 and LS-3 as justified or matching when
they are not.
