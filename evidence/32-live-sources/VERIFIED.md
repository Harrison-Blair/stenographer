# 32-live-sources verification

| Item | Value |
| --- | --- |
| Task | 32-live-sources |
| Commit verified | 7a0dbc0 |
| Date | 2026-10-19 |
| Verdict | pass |

Environment: the worktree has no `.venv`. Each run used
`/home/penguin/source/stenographer/.venv/bin/` with `PYTHONPATH="$PWD/src"`.
`stenographer.__file__` resolved to this worktree's `src/`.

This run follows the earlier fail at `cad5439` (V1: the retention assertion
ran after `stop()`). The repair `7a0dbc0` moves the assertion before `stop()`.

## Results

| Item | Result | Observation |
| --- | --- | --- |
| V1 Recorder streaming (R1, R4) | pass | Red: 2 failed, 61 passed (`TypeError: Recorder.__init__() got an unexpected keyword argument 'streaming'`). Green: 63 passed. Mutation M3 is now detected. M1 is detected. |
| V2 System audio capture (R2, R4) | pass | Red: collection error, `ImportError: cannot import name 'SystemAudioCaptureError' from 'stenographer.lib.platform.errors'`. Green: 6 passed. Mutations M4 and M5 are detected. |
| V3 Phrase segmenter (R3, R4) | pass | Red: `ModuleNotFoundError: No module named 'stenographer.lib.live.phrase'`. Green: 1 passed, 1 skipped (Silero model absent at `~/.local/share/stenographer/models/live/silero_vad.onnx`; the brief permits the skip). Mutations M6 and M7 are detected. |
| V4 Common gate (AC1) | pass | `ruff check .`: All checks passed. `ruff format --check .`: 570 files already formatted. `pytest -m "not integration"`: 2514 passed, 1 skipped, 6 deselected. `stenographer --help`: exit 0. `tests/test_architecture.py`: 4 passed. |
| V5 Integration test exists (AC2) | pass | `tests/lib/platform/linux/test_system_audio_integration.py:15` has `@pytest.mark.integration` on `test_default_monitor_captures_three_seconds_of_playing_audio`. The `not integration` selection deselects it. Not run, per the brief. |

## Red runs

A detached scratch worktree at the parent commit `1cb136f` received the test
tree of `7a0dbc0` (`git checkout 7a0dbc0 -- tests`). Results are in the table.

## Mutation checks

Each mutation was applied to a scratch worktree at `7a0dbc0` and reverted
before the next one.

| ID | Mutation | Tests | Result |
| --- | --- | --- | --- |
| M1 | Default mode has no cap (`_max_frames = 0`) | test_recorder.py | 3 failed (detected) |
| M3 | Streaming mode appends each block to `_blocks` | test_recorder.py | 1 failed, `Left contains 3 more items` (detected) |
| M4 | No error after an early `pw-record` exit | test_system_audio*.py | 1 failed (detected) |
| M5 | Drop the final partial block | test_system_audio*.py | 1 failed (detected) |
| M6 | `flush()` does not flush the VAD | test_phrase_segmenter.py | 1 failed (detected) |
| M7 | No maximum-length cut | test_phrase_segmenter.py | 1 failed (detected) |

## Limits

- The real-model phrase test skipped because the Silero VAD model is absent.
- The integration test was not run (needs user consent and audio hardware).
