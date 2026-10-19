# 32-live-sources verification

| Item | Value |
| --- | --- |
| Task | 32-live-sources |
| Commit verified | cad5439 |
| Date | 2026-10-19 |
| Verdict | fail |

Environment: the worktree has no `.venv`. Each run used
`/home/penguin/source/stenographer/.venv/bin/` with `PYTHONPATH="$PWD/src"`.
`stenographer.__file__` resolved to this worktree's `src/`.

## Results

| Item | Result | Observation |
| --- | --- | --- |
| V1 Recorder streaming (R1, R4) | fail | Red and green reproduce. The "keeps no blocks" check is vacuous. See below. |
| V2 System audio capture (R2, R4) | pass | Red: `ImportError: cannot import name 'SystemAudioCaptureError' from 'stenographer.lib.platform.errors'`. Green: 6 passed. Mutations M4 and M5 fail the tests. |
| V3 Phrase segmenter (R3, R4) | pass | Red: `ModuleNotFoundError: No module named 'stenographer.lib.live.phrase'`. Green: 1 passed, 1 skipped (Silero model absent at `~/.local/share/stenographer/models/live/silero_vad.onnx`; the brief permits the skip). Mutations M6, M7, M8 fail the tests. |
| V4 Common gate (AC1) | pass | `ruff check`: All checks passed. `ruff format --check`: 570 files already formatted. `pytest -m "not integration"`: 2514 passed, 1 skipped, 6 deselected. `stenographer --help`: exit 0. `tests/test_architecture.py`: 4 passed. |
| V5 Integration test exists (AC2) | pass | `tests/lib/platform/linux/test_system_audio_integration.py:15` has `@pytest.mark.integration` on `test_default_monitor_captures_three_seconds_of_playing_audio`. Not run, per the brief. |

## Red runs

A detached worktree at the parent commit `1cb136f` received the test tree of
`cad5439` (`git checkout cad5439 -- tests`).

- `tests/lib/audio/test_recorder.py`: 2 failed, 61 passed (`TypeError` on the
  `streaming` keyword).
- `tests/lib/platform/test_system_audio.py`,
  `tests/lib/platform/linux/test_system_audio_capture.py`: collection error,
  `ImportError` on `SystemAudioCaptureError`.
- `tests/lib/live/test_phrase_segmenter.py`: collection error,
  `ModuleNotFoundError` on `stenographer.lib.live.phrase`.

Note: `V2.md` records the red import from `stenographer.lib.live.errors`. The
committed code defines the error in `stenographer.lib.platform.errors`.

## Mutation checks

Each mutation was applied to a scratch copy of `cad5439` and reverted.

| ID | Mutation | Tests | Result |
| --- | --- | --- | --- |
| M1 | Default mode has no cap (`_max_frames = 0`) | test_recorder.py | 3 failed (detected) |
| M2 | Streaming mode keeps the cap | test_recorder.py | 1 failed (detected) |
| M3 | Streaming mode appends each block to `_blocks` | test_recorder.py | 63 passed (NOT detected) |
| M4 | No error after an early `pw-record` exit | test_system_audio_capture.py | 1 failed (detected) |
| M5 | Drop the final partial block | test_system_audio_capture.py | 1 failed (detected) |
| M6 | `flush()` does not flush the VAD | test_phrase_segmenter.py | 1 failed (detected) |
| M7 | No maximum-length cut | test_phrase_segmenter.py | 1 failed (detected) |
| M8 | Phrase start ignores the segment start frame | test_phrase_segmenter.py | 1 failed (detected) |

## V1 failure

R4 requires that the test show "streaming mode keeps no blocks over a long fake
stream". `test_streaming_keeps_no_blocks_has_no_cap_and_emits_16khz_blocks`
(`tests/lib/audio/test_recorder.py:544`) asserts `recorder._blocks == []` only
after `recorder.stop()`. `stop()` always calls `_discard_samples()`, which
resets `_blocks`. So the assertion holds even when streaming mode retains every
block (M3). The production code does not retain blocks, but the test does not
prove it. A repair asserts the retention before `stop()` (for example, after
the fed blocks) and confirms that M3 then fails.
