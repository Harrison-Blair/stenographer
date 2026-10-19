# 31-live-session-store verification

| Item | Value |
| --- | --- |
| Task | 31-live-session-store |
| Commit verified | a2f63bb |
| Date | 2026-10-19 |
| Verifier | t31-verifier-1 (Claude Code, claude-opus-5-5) |
| Tooling | The worktree has no `.venv`. Commands ran with `/home/penguin/source/stenographer/.venv/bin/` and `PYTHONPATH=src`, the same as the worker's evidence. The import path resolves to this worktree's `src/`. |

## Results

| Item | Result | Observation |
| --- | --- | --- |
| V1 Common gate | pass | `ruff check`: All checks passed (exit 0). `ruff format --check`: 549 files already formatted (exit 0). `pytest -m "not integration"`: 1 failed, 2493 passed, 5 deselected. The only failure is `test_keycodes_drift.py::test_generated_table_covers_every_evdev_key_and_button_name`. It also fails on base `8334670` (rerun from `git archive 8334670`: 1 failed). This is the known gate exception. `stenographer --help`: exit 0, usage printed. |
| V2 Tests fail before, pass after | fail | Red run with the worker's stubs (`open` returns `None`, `@dataclass` removed): 8 failed. Green run: 8 passed. This matches V2.md. Then each behavior was broken on its own. Nine breaks failed their matching test: collision suffix, folder mode, UTC conversion, FLAC mode, audio values, silence length, rename record, final labels, text in log. **The lock break did not fail any test.** With `self._lock` replaced by `contextlib.nullcontext()`, `test_audio_and_transcript_writes_are_safe_from_three_threads` passed in 4 of 4 runs (8 passed). |

## V2 failure detail

The thread test cannot detect a writer that is not thread-safe. Its threads write disjoint state: `mic.flac`, `system.flac`, and one thread for `transcript.jsonl`. R2 says the writer is thread-safe and R4 asks for a test of parallel writes. The common rules forbid a test that does not fail when the behavior breaks. The V2.md result claims that the tests cover "concurrent writes from three threads". The output does not support that claim.

The lock is necessary. A stress script (scratch only, not committed) ran 3 threads writing to `mic` and 3 threads appending lines:

| Build | Result over 5 trials |
| --- | --- |
| Lock removed | 5 of 5 trials bad: `FileExistsError(17)` from concurrent first opens of `mic.flac`, and 96000 of 288000 samples written |
| Shipped code (RLock) | 0 of 5 trials bad |

The implementation is correct. The thread test is the defect.

## Repair needed

Make the thread test fail when the lock is removed. For example, have more than one thread write the same source and append lines at the same time, then check the sample counts and the JSONL line counts. Show the test fail with the lock removed and pass with it restored.

## Notes (not failures)

- Audio is stored as FLAC `PCM_24`. Arbitrary float32 values are quantized (step about 1.2e-7). This is within the test tolerance `atol=1e-6`. The spec says FLAC is "lossless" (D3).
- `lib/live/__init__.py` and `tests/lib/live/__init__.py` have the R0 content. The production path is `src/stenographer/lib/live/`, which is this repository's layout.
