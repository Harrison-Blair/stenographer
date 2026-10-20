# VERIFIED — task 108 hub-live-board (third verification, head bda35a6)

Verifier re-ran each item from the worktree root on 2026-10-20. Python tools
came from `/home/penguin/source/stenographer/.venv` with `PYTHONPATH=$PWD/src`
(the worktree has no `.venv`). Fake services only; no microphone, model,
`live`, `run`, or integration test.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red run | pass | HEAD hub tests on scratch worktrees: dev base 75971fa → 12 failed, 55 passed; prior head 18a2ed0 → 4 failed, 63 passed (card lacks `medium.en int8`; REC border title; view hint lacks `mixed / split`). |
| V1 green run | pass | `pytest tests/cli/hub` at HEAD: 67 passed. |
| V2 existing behaviour | pass | 67 hub tests pass, incl. task 103 refresh guard and task 107 no-background test. Independent count: 0 segments with a non-default bgcolor in Live idle, mixed and split at 150x45. |
| V3 before/after renders | pass | All 18 before/after svg/txt/png files present. |
| V4 board comparison (req. 8, visual check) | pass | Independent pilot re-render (`verifier-live-{idle,mixed,split}.png`, regenerated now) vs `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/StenoB.png` and `LiveSplit.png`. Table below. |
| V5 gate | pass | ruff check: all passed; ruff format --check: 685 files formatted; pytest -m "not integration": 2662 passed, 2 skipped, 6 deselected; `stenographer --help` prints usage. |

## V4 gap by gap

| Gap | Verdict | Detail |
| --- | --- | --- |
| L-1 sidebar + card | matches | Six sections above a bordered card: `engine / medium.en int8 / queue 2 · failed 1 / cpu ▕…▏ N%`. The idle render uses the host config model (`large-v3-turbo-ct2`), so `int8` wraps to the next line; content is right. |
| L-2 selected row | matches | Bold accent `▶ 1 Live`, no fill (fill overridden by the no-background rule). |
| L-3 REC panel | matches | One `● REC` label (screen text has exactly one `REC`), no border title, large `Digits` elapsed time. |
| L-4 / L-5 MIC, SYSTEM | matches | Source, state, device on one line, waveform meter, dBFS. |
| L-6 / LS-3 speaker labels | matches / overridden | Bold distinct accent colours, no chip fill (no-background rule). |
| L-7 / LS-4 key hints | matches | `v view: mixed / split`; `mixed` bold in mixed view, `split` bold in split view; `1-6 sections` present. Key-chip fills overridden by the no-background rule. |
| L-8 canvas | overridden | No-background rule; 0 painted segments. |
| LS-1 / LS-2 split columns | matches | Time column, `MIC · what you said`, `SYSTEM · everyone else`, `·` in empty cells. |
| Transcript title | minor, accepted | Screen shows `transcript · mixed · 2 speakers`; the board's mixed title omits `mixed`. Consistent with the split board title; not a gap. |

The PNG renderer (rsvg-convert) joins some adjacent styled runs and shifts
split-row cells; the compositor text shows correct spacing and row alignment
(`00:00:01 You  mic words … ·`, `00:00:02 · … Speaker 2  system words`).

## Verdict

Pass. The three findings of the second verification (L-1 compute type, L-3
duplicate REC, L-7 view hint) are fixed and covered by tests that fail at
18a2ed0.
