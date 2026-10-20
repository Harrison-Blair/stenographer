# VERIFIED — 72-tui-input-first

Independent verifier re-run on 2026-10-20 at task head `99ca82e`; base is
`origin/dev` at `06bd0d3`. Environment: `/home/penguin/source/stenographer/.venv/bin/`
with `PYTHONPATH=src` (confirmed it imports the task worktree source). No
microphone, `live`, `run`, model download, or integration test was used.

| Item | Result | Observation |
| --- | --- | --- |
| V1 hub work in workers | pass | Red: task tests copied onto a base worktree; `slow_recording_start`, `slow_recording_save`, `slow_files_cancel` failed (status text `Starting recording...`, `Saving recording...`, `Canceling Files job...` absent). Mutation: task `app.py` with start work awaited inline in the action → `WaitForScreenTimeout` on the section key, so the test catches a blocked input loop. Green: all pass on task head. |
| V2 `q` / `ctrl+c` confirm | pass | Red at base: both `test_pilot_quit_keys_confirm_recording_prompt[ctrl+c]` and `[q]` failed (`[] == ['stop-recording']`). Green: 2 passed. `QuitConfirm` binds `q` and `ctrl+c` to confirm. |
| V3 spec README | pass | The four assertions passed. Input-first rule text and pending row removed; row 72 added; Files-job quit prompt kept. |
| V4 gate | pass | `ruff check .`: All checks passed. `ruff format --check .`: 616 files already formatted. `pytest -m "not integration"`: 2607 passed, 2 skipped (absent local audio fixtures), 6 deselected. `stenographer --help`: exit 0. |
| V5 live stop in worker | pass | Red at base: `test_second_q_skips_relabel_and_stop_progress_is_visible` failed (status showed `REC ...`, no `Saving...`). Green: `tests/cli/hub/test_app.py` + `tests/cli/live/test_app.py` 15 passed. |

Temporary base worktree in the session scratchpad was removed after the runs.
