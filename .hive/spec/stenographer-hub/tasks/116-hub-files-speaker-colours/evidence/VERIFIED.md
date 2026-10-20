# VERIFIED — 116 hub-files-speaker-colours

Verifier: independent re-run on 2026-10-20 at commit `6621bf5`, from the task worktree.
I used a temporary `.venv` symlink to `/home/penguin/source/stenographer/.venv` and
`PYTHONPATH=src`. I removed the symlink after the runs.

| Item | Result | Observation |
| --- | --- | --- |
| V1 — failing-first pilot test | pass | Red: I restored `files_view.py` from `HEAD~1` and ran `test_files_preview_uses_distinct_shared_speaker_colors`. Result: `1 failed`, because both labels had `Color('#5fd7ff')`. Green: I restored the file. `tests/cli/hub/test_files.py` gave `19 passed`. |
| V1 — shared palette reuse | pass | `files_view.py` calls `speaker_color(line.speaker_id, speaker_ids, source=line.source)` from `cli/shared/speaker_colors.py`. `live_view.py` uses the same call. The task adds no second palette. The style is `bold <color>` with no background. |
| V2 — renders and visual check | pass | My own 150x45 pilot capture with synthetic lines (`verifier-after-files.png`): Speaker 1 is orange `#ffaf5f`, Speaker 2 is purple `#d787ff`, and a repeated Speaker 1 stays orange. I compared it with the board `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Files.png`. The layout and content match. The board shows filled chips; the no-fill rule overrides them. This agrees with the worker's `visual-check.md`. The worker's before/after `.txt` files contain only synthetic text (`sample alpha/beta/gamma`). |
| Coordinator rule — distinguishable without colour | pass | The plain render of my capture shows the speaker name on each line: `00:00:04  Speaker 1  sample alpha` / `00:00:06  Speaker 2  sample beta` / `00:00:08  Speaker 1  sample gamma`. The test also asserts both names in `preview.plain`. |
| V3 — gate | pass | `ruff check .`: All checks passed. `ruff format --check .`: 712 files already formatted. `pytest -m "not integration"`: 2679 passed, 2 skipped, 6 deselected. `stenographer --help`: rc 0. |

Note (outside this task's scope): the brief says that Sessions uses the shared colours.
`sessions_view.py` does not import `speaker_color`, so this verification found no
per-speaker colouring in Sessions to compare against. Requirement 1 is consistent with Live.
