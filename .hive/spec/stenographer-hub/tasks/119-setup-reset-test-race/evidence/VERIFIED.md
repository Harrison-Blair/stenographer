# 119-setup-reset-test-race verification

Verifier: independent re-run on 2026-10-20 against `4839960` (fix `e9e9239`,
base `2c80b56`). The worktree has no `.venv`, so
`/home/penguin/source/stenographer/.venv` was used with `PYTHONPATH=src`.
The scratch harnesses were the verifier's own, written in the session
scratchpad; they were not the worker's files.

| Item | Result | Observation |
| --- | --- | --- |
| V1 save path + targeted test | pass | `action_reset_config` (`src/stenographer/cli/hub/app.py:813`) starts `_write_setup_defaults()` with `run_worker(group="setup", exclusive=True)`. The worker awaits `asyncio.to_thread(save_defaults, path)`. Notify and `update_config` run only after the save returns. The diff changes only `tests/cli/hub/test_setup_doctor.py`: it captures the `setup` worker and awaits `worker.wait()`. No sleep, fixed pause, or retry was added. The targeted test passes. |
| V2 deterministic race proof | pass | A verifier harness gated `ConfigDocument.save` on a `threading.Event`. Old sequence (`press shift+d`, one `pilot.pause()`, read inside the coroutine): **failed**, `AudioConfig(input_device='test microphone' ...) != AudioConfig(input_device=None ...)`. New sequence (await the captured worker), with the save held 0.5 s after it started: **passed**; the defaults were saved and the single backup matched the original bytes. Result: `1 failed, 1 passed in 0.96s`. |
| V3 200 targeted runs | pass | Loop over the targeted test, 200 separate pytest runs: `PASS 200/200`. |
| V4 hub tests | pass | `pytest -q tests/cli/hub`: `99 passed in 41.71s`. |
| V5 gate | pass | `ruff check .`: `All checks passed!`. `ruff format --check .`: `740 files already formatted`. `pytest -m "not integration"`: `2694 passed, 2 skipped, 6 deselected in 67.14s`. `stenographer --help`: exit 0. |
| Brief item 3: product race on quit | pass (no product race) | Probe through the real `HubApp.run(headless=True, auto_pilot=...)` path. The save was held 1.0 s after it started; the pilot pressed `5`, `shift+d`, waited until the save began, then pressed `q`. `run()` returned after 1.14 s, only after the save thread finished: Textual cancels the worker task, but `asyncio.to_thread` cannot cancel a running thread, and asyncio's shutdown waits for the default executor. In process and after process exit: `input_device` was `None` (defaults), one backup existed and held `test microphone`. The cancelled worker did skip the success notification and `services.update_config`. Both only affect the hub process that is quitting, so nothing a user keeps is lost. A hard kill mid-save is covered by `ConfigDocument.save`, which writes the backup first and then does an atomic `os.replace`. The race was only in the test, so leaving product code unchanged is correct. |

Verdict: pass.
