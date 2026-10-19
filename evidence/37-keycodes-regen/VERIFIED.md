# 37-keycodes-regen verification

| Item | Value |
| --- | --- |
| Task | 37-keycodes-regen |
| Commit verified | 48aee7e (keycodes change in c550dc0) |
| Base | 8334670 |
| Date | 2026-10-19 |
| Agent | verifier, claude-code, claude-opus-5-5 |
| Environment | temporary `.venv` symlink to `/home/penguin/source/stenographer/.venv`, `PYTHONPATH=$PWD/src` (confirmed `stenographer.__file__` resolves to this worktree); symlink removed afterwards. evdev 1.9.3. |

| Item | Proves | Result | Observation |
| --- | --- | --- | --- |
| V1 gate | AC1 | pass | `ruff check .`: All checks passed (exit 0). `ruff format --check .`: 544 files already formatted (exit 0). `pytest -m "not integration"`: 2486 passed, 5 deselected (exit 0). `stenographer --help`: exit 0. |
| V2 drift test | AC2 | pass | Red: with `keycodes.toml` from 8334670, the drift test fails (exit 1) with missing `BTN_GRIPL`, `BTN_GRIPL2`, `BTN_GRIPR2`, `KEY_ACTION_ON_SELECTION`, `KEY_CONTEXTUAL_INSERT`, `KEY_EPRIVACY_SCREEN_ON`, and more. Green: on the branch, 1 passed (exit 0). `gen_keycodes.py --check`: up to date (exit 0). |
| V3 diff + CI | AC3 | pass | Regenerating from the base file with `gen_keycodes.py` reproduces HEAD byte-for-byte. Diff: +10 `[codes]`, +6 `[names]`, 0 removed, 0 changed entries; one header comment path update. CI (`.github/workflows/test.yml:33`) installs `.[dev]`; `pyproject.toml:15` has `evdev>=1.4` with no upper bound, so CI can resolve a newer evdev and the drift test can fail again. Matches the evidence. |
| AC4 | AC4 | pass | No microphone access and no integration tests were run. |

## Observation (not a failure)

`[names]` has no entries for codes 548–551 (`BTN_GRIP*`). The generator builds `[names]` only from `evdev.ecodes.KEY`, and evdev 1.9.3 lists these codes only in `evdev.ecodes.BTN`. This is the pre-existing generator behavior and outside this task's scope.
