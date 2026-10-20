# VERIFIED — task 108 hub-live-board (second verification, head 9f3337e)

Verifier re-ran each item from the worktree root on 2026-10-20. Python tools
came from `/home/penguin/source/stenographer/.venv` with `PYTHONPATH=$PWD/src`
(the worktree has no `.venv`). Fake services only; no microphone, model,
`live`, `run`, or integration test.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red run | pass | HEAD hub tests on dev (75971fa) code in a scratch worktree: 10 failed, 55 passed (`No nodes match '#live-rec'`, `'#sidebar-card'`). On the pre-repair head 2d5d13c: 7 failed, 58 passed. |
| V1 green run | pass | `pytest tests/cli/hub` at HEAD: 65 passed. |
| V2 existing behaviour | pass | 65 hub tests pass, including the task 103 refresh guard and task 107 no-background test. Independent count: 0 painted-background segments in Live idle, mixed and split at 150x45. |
| V3 before/after renders | pass | All 18 before/after svg/txt/png files present. |
| V4 board comparison (req. 8, visual check) | **fail** | Independent pilot re-render (`verifier-live-{idle,mixed,split}.png`, regenerated now) vs `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/StenoB.png` and `LiveSplit.png`. Three differences below. |
| V5 gate | pass | ruff check: all passed; ruff format --check: 685 files formatted; pytest -m "not integration": 2660 passed, 2 skipped, 6 deselected; `stenographer --help` prints usage. |

## V4 gap by gap

| Gap | Verdict | Detail |
| --- | --- | --- |
| L-1 sidebar + card | differs | Card shows `engine / test-model / queue 2 · failed 1 / cpu`. The board shows `medium.en int8`: model plus compute type. `_live_sidebar_card` (`src/stenographer/cli/hub/app.py:473`) uses only `session.model_name` (= `cfg.asr.model`, no compute type). The earlier render's `test-model int8` came from the old fixture string, not from code; the compute type was never displayed. |
| L-2 selected row | matches | Bold accent `▶ 1 Live`, no fill. Sidebar title is legible accent. |
| L-3 REC panel | differs | `REC` appears twice: border title ` REC ` (bold #ff875f) plus `● REC` inside. The board shows only `● REC`; MIC and SYSTEM panels have no border title. Large `Digits` time now matches. |
| L-4 / L-5 MIC, SYSTEM | matches | Source, state, device on one line (`Default output…` truncated), waveform meter, dBFS. |
| L-6 / LS-3 speaker labels | matches | Bold, distinct colours (You #5fd7ff, Speaker 2 #d787ff), no fill. |
| L-7 / LS-4 key hints | differs | Keys are now bold accent, descriptions default foreground (fixed). The board's view hint is `v view: mixed / split` with the current view bold; the screen shows only `v view`. The first verifier reported this; it is unchanged and `visual-check.md` marks L-7 "Matches". |
| L-8 canvas | overridden | No-background rule; 0 painted segments. |
| LS-1 / LS-2 split columns | matches | Time column, `MIC · what you said`, `SYSTEM · everyone else`, `·` in empty cells. |
| Manager point: `spacepause/resume`, `mmic`, `MICon`, `Youmic` | not a defect | Compositor segments are `'space'` then `' pause/resume'`, `'m'` then `' mic'`; plain text reads `space pause/resume   m mic`, `[m] MIC on`, `You  mic words`. The joined look is an rsvg-convert font-metric artefact. |

## Verdict

Fail on V4: duplicate REC label (L-3), engine card lacks the compute type
shown on the board (L-1), and the view hint lacks `view: mixed / split` with
the current view bold (L-7/LS-4). `visual-check.md` marks all three "Matches".
