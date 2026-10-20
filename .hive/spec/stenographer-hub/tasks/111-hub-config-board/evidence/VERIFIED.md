# VERIFIED — 111-hub-config-board (fourth verification)

Verifier: t111-verifier-4, 2026-10-20, branch head `7a43d22` (merge of
`origin/dev` `8381ff7`). The worktree has no `.venv`. Every command used
`/home/penguin/source/stenographer/.venv/bin/` with `PYTHONPATH=$PWD/src`.
Scope (manager note): merge-only repair after the third verification. Earlier
verifications are in git history.

**Verdict: pass.**

| Item | Result | Observation |
| --- | --- | --- |
| Merge into `origin/dev` | pass | `origin/dev` `8381ff7` is an ancestor of HEAD; `git merge-tree --write-tree origin/dev HEAD` exits 0. `git diff 8381ff7 HEAD` touches only task files: README.md, docs/hub.md, site/index.html, hub `app.py`, `config_view.py`, `test_config.py`. Dev's Files, Sessions, Setup/Doctor code and tests are unchanged. |
| `app.py` conflict resolution | pass | Keeps dev's `#setup-panel, #doctor-panel` CSS, `setup_panel`/`doctor_panel` widgets and display logic, sessions/files sidebar cards; adds Config's group list, `#main-content`, hotwords and selected-help widgets and `_config_sidebar_card`. |
| `site/index.html` both sides | pass | Hub row has dev's Live, Files and Sessions sentences and the task's Config sentences (group selector, hotwords, path and unsaved count). |
| V1 red at base `d8ad650` | pass | Current `test_config.py` against `git archive d8ad650 src`: **10 failed, 6 passed** (red). |
| All hub tests (green) | pass | `pytest -q tests/cli/hub/`: **99 passed** (app, config, files, sessions, session_jobs, setup_doctor, live_view, handler, no_background). |
| Gate `ruff check .` | pass | `All checks passed!` |
| Gate `ruff format --check .` | pass | `728 files already formatted` |
| Gate `pytest -m "not integration"` | pass | `2694 passed, 2 skipped, 6 deselected` |
| Gate `stenographer --help` | pass | exit 0 |
| Re-render vs board | pass | See below. |
| No painted background | pass | `test_no_background.py` passes; renders show no fill on selected nav, group or key. |

## Re-render

Pilot, fake services, 150x45, `beam_size = 5`, 40 synthetic hotwords. PNGs via
`rsvg-convert` from `app.save_screenshot()` SVG (copy with `xml:space="preserve"`):

- `verifier4-default.png`: ASR group, `model` selected.
- `verifier4-edited.png`: search edit `idle_unload_seconds = 4`.

Board: `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Config.png`.

| Board element | Judgement |
| --- | --- |
| C-1 file card | Matches: `config.toml`, `0 unsaved changes`; after edit `1 unsaved change` in warn colour. |
| C-2 group selector | Matches: bordered `group` panel beside settings, `▶ asr` bold accent, no fill. `delivery` kept, no `live` (req. 4). |
| Settings column | Matches decision 15: one ASR column, compact name/value rows, `●` after non-default values, selected-key help at bottom. |
| C-5 hotwords | Matches: separate area below a divider, `Term0 … Term10 … 40 words ●`. |
| C-4 context | Absent, as directed. |
| Key hints | Match: edit, undo, reset, search, save, group/key. |
| Fills | Overridden by task 107; nothing painted. |
