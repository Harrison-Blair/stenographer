# VERIFIED — 107-hub-no-background

Verifier run on `fb6f861` (base `6e80174`). Tools: `/home/penguin/source/stenographer/.venv/bin/` with
`PYTHONPATH=<worktree>/src` (the worktree has no `.venv`; imports resolved to the worktree source).
No microphone, audio, `live`/`run`, model download or integration test was used.

| Item | Result | Observation |
| --- | --- | --- |
| V1 regression tests | pass | Green: `tests/cli/hub/test_no_background.py` 2 passed. Red at base: both tests fail (speaker marker, `> 1 Live`). With the speaker-marker asserts removed, the background test at base reports painted cells in every label: Live idle, Live recording, Live split, Files, Sessions, Config, Setup, Doctor, Quit dialog, Config dialog, Speaker dialog, Speaker picker, stenographer live. Mutations on `fb6f861` each turn the suite red: rename dialog `background: $surface`; live `#key-hints` `$boost`; selection accent without bold; hub without `ansi_color=True`. |
| V2 SVG evidence | **fail** | `before-list.svg` is a render of the hub **Live** section (title "Live", sidebar `> 1 Live`, engine/REC/MIC/SYSTEM panels), the same as `before-live.svg` apart from the CPU figure. No before render of a list screen exists, so requirement 5 (before/after of Live **and one list screen**) is not met. `before-live`, `after-live`, `after-list` (Files) and both standalone-live SVGs are correct: the before SVGs hold 446/96 background fills; the after SVGs have only window-chrome fills. |
| V3 gate | pass | `ruff check .` all checks passed; `ruff format --check .` 658 files already formatted; `pytest -m "not integration"` 2645 passed, 2 skipped, 6 deselected; `stenographer --help` exit 0. |

## Independent render comparison (base vs head, 120×36)

| Screen | bg cells base → head | border segments base → head | accent `#5fd7ff` text at head |
| --- | --- | --- | --- |
| hub Live | 4320 → 0 | 153 → 153 | 7 |
| hub Files | 4320 → 0 (6 reverse → 0) | 69 → 69 | 23 |
| hub Sessions | 4320 → 0 | 69 → 69 | 11 |
| hub Config | 4320 → 0 | 138 → 138 | 40 |
| hub Setup | 4320 → 0 | 138 → 138 | 23 |
| hub Doctor | 4320 → 0 | 138 → 138 | 88 |
| `live` app | 4320 → 0 | 0 → 0 | — |
| `live` speaker picker | 4320 → 0 (7 reverse → 0) | 30 → 60 | 120 |

Normal text renders with the terminal default foreground at head (base: `#e3e6ec` / `#e0e0e0`). Borders
(`#3a4150`), dim text (`#a0a8b8`) and the warning accent (`#fea62b`) still render.

Rename flow (keyboard, at base and head): `r` → focus picker → `enter` → `down` → `enter` → `tab` →
type "Alice" → click Rename. Both record `('rename', 'speaker-1', 'Alice')`; the picker shows
"Speaker 1" (no marker leaks into the selected value). `SpeakerSelect`/`SpeakerSelectOverlay` replace
Textual's stock `Select`/`SelectOverlay` only to redraw the highlighted option as `▶` + bold accent.
Values still come from `Select._options`.

## Scope notes (do not affect the verdict on their own)

- `scrollbar-size: 0 0` is set globally in both apps, so scrollbars are hidden. In Files this widens the
  options column by 2 cells. Textual paints the scrollbar thumb as a background, so requirement 1 may
  require this, but scroll position is no longer visible.
- Dialog `Select`, `Input` and `Button` borders change from Textual's fill-based `tall` borders to
  `round` line borders. The fill-based borders cannot render without a background.
- Gutter side effects of `append_line`: Files directory rows lose their alignment with file names
  (`        ../` → `  ../`); unselected Setup steps gain 2 cells of indent; Files queue error lines lose
  their 2-cell indent.
- The CSS override block (~170 lines) is duplicated verbatim in `cli/hub/app.py` and `cli/live/app.py`.
- `Input > .input--cursor` has no fill, so the text cursor is invisible on a blank character. Focus
  stays visible through the accent border.
- `.hive/tmp/` (empty, untracked) remains in the worktree from the worker's renders.
