# VERIFIED — 112 hub-setup-doctor-board

Verifier: independent agent, 2026-10-20, commit 2bc2763. Tools came from
`/home/penguin/source/stenographer/.venv` with `PYTHONPATH="$PWD/src"`, because
this worktree has no `.venv`. `python -c 'import stenographer'` resolves to this
worktree's `src/`.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red run | pass | Base `2bc2763~1` in a scratch worktree with the new test file: `2 failed, 10 deselected`. Setup failed with no `#setup-steps`. Doctor failed with `TypeError` on `checked_at`. |
| V1 green run | pass | `2 passed, 10 deselected`. All of `tests/cli/hub`: `69 passed`. This includes the task 107 no-background pilot and the model-download confirm test. |
| V2 renders and visual check | pass | Independent 150x45 pilot captures with fake services: `verify-setup.png` and `verify-doctor.png`. Compared gap by gap with the board PNGs at their absolute paths (see below). No painted background is visible, and the no-background pilot passes. |
| V3 gate | pass | `ruff check .`: all checks passed. `ruff format --check .`: 692 files already formatted. `pytest -m "not integration"`: 2664 passed, 2 skipped (audio fixtures absent), 6 deselected. `stenographer --help`: usage printed, exit 0. |

## Gap-by-gap comparison

Boards: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Setup.png`
and `.../Doctor.png`.

| Gap | Result | Note |
| --- | --- | --- |
| U-1 wizard layout | matches | Bordered `steps` list on the left, bordered `3 · hotkey` detail on the right, `quick: steps 1-3 only` in the step panel. |
| U-3 hotkey detail | matches | Capture target, mode, hybrid threshold, general binding, cancel binding, device, test status. Differs in form only: capture target is a text row, not the board's dashed callout. Mode shows only the current value, not the three-choice row. Test status follows the fields instead of sitting at the panel bottom. |
| D-1 summary | matches | Sidebar card: `summary / N ok · N warn / N fail / checked HH:MM`. |
| D-2 grouped checks | matches | `input and audio` and `engine and desktop` are bordered and side by side. Rows use `glyph label · detail` as on the board. |
| D-3 issue detail | matches | Bordered `selected issue · <label>` panel under the groups, with detail and fix after `enter`. It keeps the existing collapsed-details behaviour. |
| D-4 recent warnings | matches | Separate bordered `recent warnings · stenographer.log` panel under the issue panel. |
| No background | overridden / passes | No fills. Selected rows use the bold accent `▶`. |

## Manager observations (judged, non-blocking)

1. Redundant status in rows (`· available`, `· cached`): this comes from the worker's capture fixture, which put board detail text into the check labels and then added a detail. The panel renders `label · detail` (the same form as before and as on the board). My capture with distinct label/detail shows no repetition. The worker's `after-doctor.*` evidence is misleading on this point. The code is correct.
2. Glyph colours (green ✓, orange !): not present; the glyphs carry the state. The brief says boards do not set exact colours, so this is not a gap. The worker's visual-check D-6 "matches" overstates this.
3. Issue panel form: the board uses a warn-bordered panel with a bold warn title and one line of text. The hub uses a plain round border with `WARN · label / Detail: / Fix:` lines. The content is the same and the form/colour differs. The selected row repeating the detail matches the board, which also repeats it.
4. Log line form: the hub shows `HH:MM:SS WARNING stenographer.<logger> event` without colour. The board shows `HH:MM:SS WARN event`. This is the existing safe-warning format from earlier tasks. It differs in form, not in panel content or placement.
5. Sidebar badge `1W 0F` vs board `●1`: this is outside the gaps this task fixes (U-1, U-3, D-1..D-4). Earlier tasks kept this form.

Points 2-4 are candidate polish items for a later task. None of them is a gap that this brief requires.

## Verdict

pass
