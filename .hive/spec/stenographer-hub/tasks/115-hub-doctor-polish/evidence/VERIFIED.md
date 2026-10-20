# VERIFIED — 115-hub-doctor-polish

Verifier run on 2026-10-20 at `8da7ad3`. The worktree has no `.venv`. I used
`/home/penguin/source/stenographer/.venv/bin` with `PYTHONPATH=src`, and confirmed
that `stenographer` imports from this worktree's `src/`.

Board PNGs (cited, not committed):
`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Doctor.png`,
`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Setup.png`.

Independent renders (my own pilot, 150×45, fake services, synthetic checks, no audio or model):
`verifier-doctor-warn.png` (warn selected, enter pressed), `verifier-doctor-fail.png`
(fail selected), `verifier-setup.png` (hotkey step, test recorded).

## Items

| # | Item | Result | Observation |
| --- | --- | --- | --- |
| 1 | Check glyphs coloured by state | pass | `✓` green, `!` warn colour, `✗` red; rows stay `glyph label · detail`. Glyph changed from `x` to `✗`. |
| 2 | Selected-issue panel | pass | Border is the state colour (orange for warn, red for fail). Bold state-coloured title `overlay unavailable`. One line `No X display. Set DISPLAY or enable XWayland.` No `WARN ·`, `Detail:` or `Fix:`. Matches Doctor.png. |
| 3 | Selected row shows detail once | pass | The view prints label and detail once each. The repeat came from the task 112 fixture (label `overlay · no X display`). Row renders `▶ ! overlay · No X display.` |
| 4 | Recent-warnings lines | pass | Dim `HH:MM:SS`, `WARN` orange / `ERROR` red, then event. Logger name gone. `safe_warning_lines` still drops message fields (tests assert `SENSITIVE` absent). |
| 5 | Setup hotkey detail | pass | `mode: ● hybrid  ○ hold  ○ toggle`, current mode bold accent and marked `●`. Test status in its own widget at the bottom of the panel. Capture target stays a text row (allowed). |
| 6 | Realistic, distinct fixtures | pass | After-captures and new tests use distinct labels and details. |
| 7 | Keep keys, behaviour, tests | pass | `app.py` change is CSS only; bindings unchanged. No test function removed; existing asserts updated for the new forms. Full suite green. |
| 8 | Evidence and red/green tests | pass | Before/after SVG, text and PNG present at 150×45. Red: new `tests/cli/hub/test_setup_doctor.py` against base `797ed0f` source → `5 failed, 8 passed`. Green at HEAD → `13 passed`. `visual-check.md` present. |
| 9 | Re-render, compare boards, no background | pass | My renders match both boards for every required element (see below). SVGs hold one `rect fill` only, the screenshot frame `#292929`; no panel or canvas fill. `test_no_background.py` passes in the full run. |
| G | Gate | pass | `ruff check .` all passed; `ruff format --check .` 698 files formatted; `pytest -m "not integration"` 2665 passed, 2 skipped, 6 deselected; `stenographer --help` exit 0. |

## Colourblind rule (overrides/colourblind-ui.md)

- Check rows: each state has a glyph (`✓ ! ✗`); colour adds to it.
- Warnings: level word `WARN` / `ERROR` carries the state.
- Setup mode: `●` / `○` carries the current choice.
- Issue panel: the title is `<label> unavailable` for both warn and fail, so
  inside that panel only colour separates warn from fail. The selected row
  directly above still shows the glyph (`▶ !` or `▶ ✗`), so the state is never
  colour-only on screen. This matches the board's form. Noted for the manager;
  not a fail.

## Observations (not failures)

- The title suffix `unavailable` is fixed. For some real checks it reads
  awkwardly, e.g. `ASR model cached · medium.en unavailable` or
  `systemd unit unavailable` for an inactive service.
- Sidebar badge (`1W 1F`) and keycap fills still differ from the board, as
  `visual-check.md` records (badge outside scope; fills overridden by task 107).
