# VERIFIED — 65-hub-setup-doctor

Date: 2026-10-20
Verifier: independent re-run of V1 to V5 at commit e951730 (base 2bd86d2).

The worktree has no local `.venv`. Each command used
`/home/penguin/source/stenographer/.venv/bin/` with `PYTHONPATH=src`;
`import stenographer` resolved to this worktree's `src/`. Red runs used a
detached scratch worktree at base `2bd86d2` with the new test files copied in.
Sabotage runs used a separate scratch worktree at `e951730`. Both scratch
worktrees were removed afterwards.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red (base) | pass | `tests/lib/diagnostics/test_additional_checks.py`: collection error, `ImportError: cannot import name 'additional_checks'`. Matches V1. |
| V1 green | pass | 4 passed. Matches V1. |
| V1 sabotage | pass | `ffmpeg_check` forced to `ok` → 1 failed. |
| V2 red (base) | pass | `tests/cli/doctor/test_report.py` at base: 2 failed (`test_render_includes_optional_checks_as_warnings`, `test_run_shows_optional_warnings_without_changing_exit_code`), 34 passed. Matches V2. |
| V2 green | pass | 36 passed. Matches V2. `report.py` diff keeps `return 78 if missing_required(caps) else 0` unchanged. |
| V2 sabotage | pass | `run()` returns 78 when an optional check warns → 3 failed. |
| V3 red (base) | pass | `tests/cli/hub/test_setup_doctor.py` at base: collection error, `No module named 'stenographer.cli.hub.doctor_view'`. |
| V3 green | pass | Combined suite (diagnostics, doctor report, hub app, setup doctor, setup workflow/handler/smoke): 212 passed, 3 skipped. Matches V3. |
| V3 sabotage | pass | Model download without the confirm prompt → `test_pilot_setup_keys_and_confirmed_model_download` failed. Download that ignores an `n` answer → same test failed. |
| V4 red (base) | pass | Same collection error as V3 (`doctor_view` absent). Matches V4. |
| V4 green | pass | Same 212 passed, 3 skipped run. |
| V4 sabotage | pass | Sidebar badge fixed at `0W 0F` → 1 failed in `test_setup_doctor.py`. |
| V5 gate | pass | `ruff check .`: All checks passed. `ruff format --check .`: 607 files already formatted. `pytest -m "not integration"`: 2590 passed, 2 skipped (absent local audio samples), 6 deselected. `stenographer --help`: exit 0. Matches V5. |

No integration tests, microphone, `live`, `run`, `doctor` on the host, or
model downloads were used. The task worktree was not modified except for this
file.
