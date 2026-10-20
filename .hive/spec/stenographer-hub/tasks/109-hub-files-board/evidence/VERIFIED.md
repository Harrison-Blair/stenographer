# VERIFIED — 109-hub-files-board

**Verdict: fail.** The tests and the gate pass. The independent visual check
finds Files board gaps that `visual-check.md` records as "Matches".

Tools: `/home/penguin/source/stenographer/.venv/bin` with
`PYTHONPATH="$PWD/src"` (the worktree has no `.venv`).

| Item | Result | Observation |
| --- | --- | --- |
| V1 — red run at base | pass | The new `test_files.py` was copied onto a scratch worktree at `d8ad650`. Result: 3 failed, 4 passed. Border test: `assert '' == 'round'`. Options test: `'[x] diarize'` absent (`diarize [x] on`). |
| V1 — green run | pass | `tests/cli/hub/test_files.py` passes on the task branch. |
| V2 — hub tests and no-background test | pass | The no-background tests (`-k background`) passed: 7 passed. The full suite includes all hub tests. |
| V3 — re-render at 150x45 | pass | Verifier pilot with the test fakes, one running job at 58 %, one 3,700 s file. Output: `verifier-after-files.{svg,png}`. |
| V4 — board comparison, gap by gap | **fail** | See the gap table below. |
| V5 — gate | pass | `ruff check`: all checks passed. `ruff format --check`: 692 files already formatted. `pytest -m "not integration"`: 2664 passed, 2 skipped, 6 deselected. `stenographer --help`: exit 0. |

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Files.png`
(source `.../designs/stenographer/Files.dc.html`).

## Gap comparison

| Gap / element | Result | Observation |
| --- | --- | --- |
| F-1 sidebar card | pass | The card shows `engine`, `large-v3-turbo int8`, `cpu` bar. The `profile` row is omitted per decision 12. |
| F-2 panel borders and placement | pass | All four panels are bordered and placed as on the board: browser left, options and queue right, preview below. |
| F-2 panel titles | **fail** | The SVG paints the `browser`, `options`, `queue` and `preview · …` titles with `fill: #3a4150`, the dim border colour. On the board the titles are legible (`#a0a8b8`). Task 108 fixed this for Live (`#live-transcript` has `border-title-color: ansi_default; border-title-style: bold`). The Files panels have no such rule. |
| F-2 browser title | **fail** | The board titles the browser with the current folder (`┤ ~/Recordings ├`). The hub titles it `browser` and prints the folder as body lines. |
| F-2 queue placement | differs (minor) | The board nests the queue in the options panel under a rule. The hub uses a separate bordered panel. This is acceptable if it is recorded as a difference. |
| Browser durations | **fail** | A 3,700 s file shows `61:40`. The board shows `1:02:15` for a file over one hour (format `H:MM:SS`). |
| F-3 selected file | pass | `▶` with bold accent text and no fill (overridden by task 107). |
| F-4 options | **fail (partial)** | The rows and labels match the board. The board colours each chosen value in accent: `[x] diarize`, `auto`, the refine value, `md`. The hub colours only the active format. `refine off` meets the brief's on/off requirement. |
| F-5 queue | pass | Bar, `58%`, `eta 01:40`, `transcribe ✓ · diarize … · save`. |
| F-6 preview | pass | The title is `preview · standup-2026-10-19`. The line shows `00:00:04`, a bold accent `Speaker 1` with no fill, then the text. |
| F-7 key hints | pass | `e open result`, `1-6 sections`. |
| F-8 no background | pass | The no-background pilot passes, and the render paints no fill. |

## Repairs required

1. Give the Files panel border titles a legible colour (the same treatment as
   `#live-transcript`).
2. Title the browser panel with the current folder.
3. Show durations of one hour or more as `H:MM:SS`.
4. Colour the chosen option values in accent (diarize state, speaker count,
   refine value, format).
5. Update `visual-check.md` so that it records each remaining difference (for
   example, the separate queue panel) and does not mark it "Matches".

Note: the worker left uncommitted edits to the before/after evidence files.
The verifier did not change or commit them.
