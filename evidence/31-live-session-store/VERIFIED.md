# 31-live-session-store verification

| Item | Value |
| --- | --- |
| Task | 31-live-session-store |
| Commit verified | a754cb2 |
| Date | 2026-10-19 |
| Verifier | t31-verifier-2 (Claude Code, claude-opus-5-5) |
| Tooling | The worktree has no `.venv`. Commands ran with `/home/penguin/source/stenographer/.venv/bin/` and `PYTHONPATH=src`, as in the worker's evidence. The import path resolves to this worktree's `src/`. Break runs used a `git archive HEAD` copy in the scratchpad, so the worktree was not edited. |

This run re-verifies the task after the repair of the V2 thread test. The earlier verdict (commit a2f63bb) failed V2 because removing the writer lock did not fail any test.

## Results

| Item | Result | Observation |
| --- | --- | --- |
| V1 Common gate | pass | `ruff check .`: All checks passed (exit 0). `ruff format --check .`: 549 files already formatted (exit 0). `pytest -m "not integration"`: 1 failed, 2493 passed, 5 deselected. The only failure is `tests/lib/platform/linux/test_keycodes_drift.py::test_generated_table_covers_every_evdev_key_and_button_name`. It also fails on base `8334670` (`git archive 8334670`, same test: 1 failed). This is the known gate exception. `stenographer --help`: exit 0, usage printed. |
| V2 Tests fail before, pass after | pass | Stub red run (`SessionWriter.open` returns `None`, `@dataclass` on `TranscriptLine` commented out): 8 failed. Lock red run (`self._lock = contextlib.nullcontext()`): `test_audio_and_transcript_writes_are_safe_from_three_threads` failed in 5 of 5 runs, with `FileExistsError: [Errno 17]` on `mic.flac` where shown. Green run in the worktree: 8 passed; the thread test alone passed 5 of 5 runs. The repaired test has three threads write the same `mic` source and append lines after a barrier, then checks 96,960 samples and 300 JSONL records. |

## Notes (not failures)

- `src/stenographer/lib/live/__init__.py` has the two R0 lines. `tests/lib/live/__init__.py` matches `tests/lib/audio/__init__.py`.
- Audio is stored as FLAC `PCM_24`, so float32 values are quantized (step about 1.2e-7), inside the test tolerance `atol=1e-6`. The previous verifier noted this too.
