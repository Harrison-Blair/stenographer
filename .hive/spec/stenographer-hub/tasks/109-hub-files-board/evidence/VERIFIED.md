# VERIFIED — 109-hub-files-board (third verification, after the dev merge at a72af96)

**Verdict: pass.**

Tools: `/home/penguin/source/stenographer/.venv/bin` with
`PYTHONPATH="$PWD/src"` (the worktree has no `.venv`). The import path
resolves to this worktree's `src/`.

| Item | Result | Observation |
| --- | --- | --- |
| Merge with `origin/dev` | pass | `git merge-tree --write-tree HEAD origin/dev` (797ed0f) exits 0, so there is no conflict. In merge `e0afe20`, `app.py` keeps task 112's `SetupPanel`/`DoctorPanel` and the doctor sidebar branches. It also keeps the Files title CSS rule, the Files sidebar card, `e open result` and `1-6 sections`. |
| V1 — red run at base `d8ad650` | pass | The branch `test_files.py` on a scratch worktree at `d8ad650`: 15 failed, 3 passed. |
| V1 — red run at merge `e0afe20` (footer) | pass | The same file at `e0afe20`: 4 failed, 14 passed. `test_files_browser_hint_is_pinned_to_panel_bottom` fails with `NoMatches '#files-browser-hint'`. The other 3 fail because the queries changed from `VerticalScroll` to `Vertical`. The worker counted only the footer pilot (1 failed). |
| V1 — green run | pass | `tests/cli/hub/test_files.py`: 18 passed. |
| V2 — hub and no-background tests | pass | `tests/cli/hub`: 82 passed. `-k "setup or doctor"`: 13 passed. `-k background`: 7 passed. |
| V3 — re-render at 150x45 | pass | Verifier pilot with the test fakes. `~/Recordings` holds four silent WAVs. One job is running at 58 % with ETA 100 s and three synthetic lines. Output: `verifier3-after-files.{svg,png}`. |
| V4 — board comparison | pass | See the table below. |
| V5 — gate | pass | `ruff check`: all checks passed. `ruff format --check`: 701 files already formatted. `pytest -m "not integration"`: 2677 passed, 2 skipped (public audio fixtures absent), 6 deselected. `stenographer --help`: exit 0. |

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Files.png`
(source `.../designs/stenographer/Files.dc.html`).

## Gap comparison

| Gap / element | Result | Observation |
| --- | --- | --- |
| F-1 sidebar card | pass | `engine`, `large-v3-turbo int8`, and a `cpu` bar. `profile` is left out per decision 12 (recorded). |
| F-2 panel borders and placement | pass | Four bordered panels: the browser on the left, options and queue on the right, and the preview below. The separate queue panel is a recorded difference. |
| F-2 browser title | pass | `~/Recordings` is in the border title. The body starts with `../`. |
| Browser hint | pass | `/ search · enter queue · space select` is on the last row inside the browser panel, as on the board. The earlier minor note is fixed. |
| Durations | pass | `1:02:15`, `41:07`, `18:42`, `2:31`. |
| F-3 selected file | pass | `▶` with bold accent text and no fill. |
| F-4 options | pass | `[x] diarize`, `count auto`, `[ ] cleanup pass`, `md · jsonl · srt · txt`, and `save to` are present. The chosen values are in the accent colour. |
| F-5 queue | pass | Bar, `58%`, `eta 1:40`, `transcribe ✓ · diarize … · save`. |
| F-6 preview | pass | Title `preview · standup-2026-10-19`. Each line shows the time, a bold accent `Speaker N` with no fill, and the text. |
| F-7 key hints | pass | `e open result`, `1-6 sections`. |
| F-8 no background | pass | The only `<rect>` fill in the SVG is the window frame `#292929`. The no-background pilots pass. |

## Notes (not blocking)

- In the rsvg PNG, `diarize` and `count` look joined. This comes from the PNG
  renderer, as in the second verification.
- In the verifier render, `save to` shows a long scratch path that wraps. The
  render used a temporary output folder. The board shows a short default path.
