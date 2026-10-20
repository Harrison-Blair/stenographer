# VERIFIED — 64-hub-config

Date: 2026-10-20
Verifier: independent re-run of V1 and V2 at commit 041f4aa.

The worktree has no local `.venv`. Each command used
`/home/penguin/source/stenographer/.venv/bin/` with `PYTHONPATH=src`;
`import stenographer` resolved to this worktree's `src/`.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red (base) | pass | With `src/stenographer/cli/hub` restored to `041f4aa~1`, `tests/cli/hub/test_config.py`: 7 failed. Source restored afterwards. |
| V1 red (sabotage) | pass | Each temporary break failed its test, then was reverted: undo disabled → `test_edit_undo_and_reset…` failed; reset disabled → same test failed; edit skips `Config.loads` validation → `test_invalid_edit_is_rejected…` failed; save writes the file directly (no preservation layer) → save/backup and conflict tests failed; document reloaded before save (no conflict check) → `test_conflict_keeps…` failed; invalid file treated as defaults → `test_invalid_config_is_read_only…` failed; unsaved-change prompt disabled → `test_search_selects…asks_for_discard` failed. |
| V1 green | pass | `pytest tests/test_architecture.py::test_ordinary_classes_have_dedicated_files tests/cli/hub -q`: 20 passed (matches V1). |
| V2 gate | pass | `ruff check .`: All checks passed. `ruff format --check .`: 600 files already formatted. `pytest -m "not integration"`: 2574 passed, 2 skipped (absent local audio samples), 6 deselected. `stenographer --help`: exit 0. Matches V2. |

No integration tests, microphone, `live`, `run`, or model downloads were used.
Working tree was clean after all sabotage runs.
