# VERIFIED — 111-hub-config-board (second verification)

Verifier: t111-verifier-2, 2026-10-20, branch head `3b5b11b`.
Bases: original `d8ad650`, repair `3d8e0e2`. The worktree has no `.venv`, so
every command used `/home/penguin/source/stenographer/.venv/bin/` with
`PYTHONPATH=$PWD/src`. `stenographer.__file__` resolves to this worktree's `src/`.
The first verification (t111-verifier-1, fail at `d610993`) is in git history.

**Verdict: fail.** Red/green and the gate pass. The branch does not merge
cleanly with `origin/dev`, and the visual check finds three defects.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red at original base | pass | `tests/cli/hub/test_config.py` against `git archive d8ad650 src`: **8 failed, 6 passed**. |
| V1 red at repair base | pass | Same tests against `git archive 3d8e0e2 src`: **7 failed, 7 passed**. The five repair tests fail, as V1.md states. Two older tests also fail because they now assert the new structure. |
| V1 green | pass | `test_config.py` + `test_no_background.py` at head: **21 passed**. |
| V1 gap map / group list | pass | Each of C-1, C-2 and C-5 has a fix and a test. The extra C-3 rows follow the manager's scope decision. The groups are `hotkey audio asr refine feedback analytics delivery`; the config has no live group. |
| V3 `ruff check .` | pass | `All checks passed!` |
| V3 `ruff format --check .` | pass | `691 files already formatted` |
| V3 `pytest -m "not integration"` | pass | `2669 passed, 2 skipped, 6 deselected` |
| V3 `stenographer --help` | pass | exit 0 |
| Merge with `origin/dev` (797ed0f, task 112) | **fail** | `git merge-tree --write-tree origin/dev HEAD` exits 1: `CONFLICT (content): Merge conflict in src/stenographer/cli/hub/app.py`. Dev merge needed. |
| V4 visual check | **fail** | See below. |
| No painted background | pass | The no-background test passes. The selected group and selected key have no bgcolor. |

## V4: independent re-capture

Pilot with fake services, 150x45, ASR group. Captures are in this folder:

- `verifier2-default.png`: default config, `beam_size` selected.
- `verifier2-changed.png`: `beam_size = 5` and three hotwords in the file, plus
  a draft edit of `idle_unload_seconds` to 4 (selected).
- `verifier2-search.png`: search result for a draft-edited `cpu_threads`.

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Config.png`
(source `.../designs/stenographer/Config.dc.html`). Decision 15 replaces the
board's two profile columns with one value column.

| Board element | Judgement |
| --- | --- |
| C-1 file card | **Differs.** It shows `config.toml` and a numeric count (`1 unsaved change`), which is correct. On the board, the non-zero count is warn-coloured (`2 unsaved`). The hub renders it with no style (the `rich_style` of the count line is `none`), so a pending change is not marked. |
| C-2 group selector | Matches. A bordered `group` panel sits beside settings. `▶ asr` is bold accent with no fill. `delivery` is kept, as req. 4 directs. |
| Settings title | Matches. `asr` is legible and bold. The first verifier's defect is fixed. |
| Settings table (manager scope: compact name/value, one value column) | **Differs.** The `▶ ` prefix on the selected row shifts the name right by two cells, and the value follows the name instead of staying in the value column: `▶ beam_size1` (default capture) and `▶ idle_unload_seconds4` with no gap (changed capture). Every unselected value starts in one column. The `after-config.png`/`.txt` evidence shows the same defect (`▶ beam_size            1`, offset from the column). |
| `●` changed marker | Matches in behaviour. In `verifier2-changed.png`, a warn-coloured `●` follows `beam_size 5`, `idle_unload_seconds 4` and hotwords. **Evidence gap:** the committed `after-config.*` has no `●` (`grep -c ● after-config.txt` = 0) and `0 unsaved changes`. It does not show the marker or a non-zero count. |
| One help line for the selected key | Matches. One help item sits at the panel bottom for the selected key only. It wraps to two or three lines at 150 cells. |
| C-5 hotwords area | **Differs.** It has a separate area below a divider, which is correct. An empty list reads `(unset) … 0 words`, which should read plainly (for example `none`). The `… N words` suffix also appears when nothing is elided (`Alpha, Beta, Gamma … 3 words`), so the ellipsis is wrong. The board uses `… 45 words` only for a truncated long list. |
| C-5 beam note | Matches. The selected `beam_size` help cites `docs/transcription-experiments.md`, CPU model and context screen, with figures. |
| C-4 context | Absent, as directed. |
| Key hints | Match: edit, save, undo, reset, search, and the group/key navigation hints. |
| Canvas / fills | Overridden by task 107. Nothing is painted. |
| Value display (note) | The board shows `cpu_threads auto`; the hub shows raw `0`. This was not in the manager's scope list and is not a fail reason here. |

## Fail reason

1. Dev merge needed: the branch conflicts with `origin/dev` 797ed0f in
   `src/stenographer/cli/hub/app.py`.
2. The selected settings row loses the value column (`▶ beam_size1`,
   `▶ idle_unload_seconds4`).
3. Hotwords: an empty list reads `(unset) … 0 words` (say `none`). The `… N words`
   suffix appears on a short, untruncated list.
4. The unsaved count is not warn-coloured when it is non-zero. The committed
   after-capture shows no `●` and `0 unsaved changes`. Re-capture with at
   least one changed value and a non-zero unsaved count.
