# VERIFIED — 111-hub-config-board (third verification)

Verifier: t111-verifier-3, 2026-10-20, branch head `7690ffb`. The worktree has
no `.venv`. Every command used `/home/penguin/source/stenographer/.venv/bin/`
with `PYTHONPATH=$PWD/src`. Earlier verifications (fail at `d610993`, fail at
`3b5b11b`) are in git history.

**Verdict: fail. Dev merge needed (again).** All repair findings of the second
verification are fixed. Red/green and the gate pass. The branch conflicts with
`origin/dev` `8381ff7`.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red at prior head `3b5b11b` | pass | Current `test_config.py` against `git archive 3b5b11b src`: **6 failed, 10 passed**. Failures: board layout, hotwords preview, truncate-to-fit, truncate wide terms, selected-key/warn dot, sidebar count. Matches V1.md. |
| V1 green | pass | `test_config.py` + `test_no_background.py` at head: **23 passed**. |
| V1 gap map / group list | pass | C-1, C-2, C-5 each have a fix and a test. Groups: `hotkey audio asr refine feedback analytics delivery`; no live settings in config, `delivery` kept (req. 4). |
| V3 `ruff check .` | pass | `All checks passed!` |
| V3 `ruff format --check .` | pass | `699 files already formatted` |
| V3 `pytest -m "not integration"` | pass | `2673 passed, 2 skipped, 6 deselected` (skips: absent public speaker clips) |
| V3 `stenographer --help` | pass | exit 0 |
| Merge with `origin/dev` `8381ff7` | **fail** | `git merge-tree --write-tree origin/dev HEAD` exits 1: `CONFLICT (content)` in `src/stenographer/cli/hub/app.py` and `site/index.html`. |
| V2 evidence `after-config.*` | pass | `after-config.txt` shows `▶ beam_size 5 ●`, `idle_unload_seconds 4 ●`, `… 40 words ●`, `1 unsaved change`. The second verifier's evidence gap is closed. |
| V4 visual check (independent re-capture) | pass | See below. |
| No painted background | pass | No-background test passes. Renders show no fill on selected group, key or nav item. |

## V4: independent re-capture

Pilot, fake services, 150x45, ASR group, `beam_size = 5` in the file. PNGs via
`rsvg-convert` from `app.save_screenshot()` SVG (copy with `xml:space="preserve"`):

- `verifier3-short.png`: hotwords `Alpha, Beta, Gamma`, `model` selected.
- `verifier3-empty.png`: hotwords empty.
- `verifier3-long.png`: 40 hotwords, draft edit `idle_unload_seconds = 4` via search.

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Config.png`
(source `.../designs/stenographer/Config.dc.html`). Decision 15 overrides the
two profile columns.

| Board element | Judgement |
| --- | --- |
| C-1 file card | Matches. `config.toml`; `0 unsaved changes` plain; `1 unsaved change` warn-coloured (orange), as the board's `2 unsaved`. |
| C-2 group selector | Matches. Bordered `group` panel beside settings; `▶ asr` bold accent, no fill. `delivery` kept, no `live` (req. 4). |
| Settings title | Matches. `asr` legible bold (`· profiles` dropped per decision 15). |
| Settings rows / value column | Matches. Pilot cell text: `▶ model                deepdml/…` and `  compute_type         int8` — names and values start in the same cells on selected and unselected rows. Search view: `▶ idle_unload_seconds  4 ●` keeps a gap. |
| Manager note: selected name one cell right in PNG | Not a defect; a PNG renderer artifact. In the SVG, the settings row emits `▶ model…` as one `<text>` span at the same x as other rows; rsvg draws `▶` with a fallback glyph wider than one cell, so the rest of that span drifts. The group and nav panels emit `▶ ` as its own span, so their names realign. The cell grid is aligned and the test checks `cell_len("▶ ") == cell_len("  ")` and the value column. A real terminal draws `▶` in one cell. |
| `●` changed marker | Matches. Warn-coloured after `beam_size 5`, the edited value and non-default hotwords. |
| One help line, selected key | Matches. Help for the selected key at panel bottom only. |
| C-5 hotwords area | Matches. Separate area below a divider; empty → `none`; short list in full with no ellipsis; long list truncated to width with `… 40 words`. Beam note cites `docs/transcription-experiments.md`, CPU model and context screen (tests and `after-config.txt`). |
| C-4 context | Absent, as directed. |
| Key hints | Match: edit, undo, reset, search, save, group/key navigation. |
| Canvas / fills | Overridden by task 107. Nothing painted. |

Notes (not fail reasons): in search mode the hotwords area is hidden (the board
has no search state). `cpu_threads` shows `0` where the board shows `auto`
(outside the gap list).

## Fail reason

Dev merge needed (again): the branch conflicts with `origin/dev` `8381ff7` in
`src/stenographer/cli/hub/app.py` and `site/index.html`. No other findings.
After the merge, re-run the hub tests and the gate.
