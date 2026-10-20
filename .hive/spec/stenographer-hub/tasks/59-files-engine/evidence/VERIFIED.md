# VERIFIED — 59-files-engine

Verifier rerun on 2026-10-20 at `5d778d4`, from the worktree root, with a temporary
`.venv` symlink to `/home/penguin/source/stenographer/.venv` and `PYTHONPATH=$PWD/src`
(the module path was checked to resolve to this worktree). Red runs used a detached
worktree of the base `06bd0d3` with only the new test files copied in. No microphone,
real ffmpeg, model download, or integration test was used.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red | pass | At base: `test_ffmpeg_decoder.py`, `tests/lib/files/test_media.py`, and `test_engine.py` fail in collection (modules missing); `test_batch_relabel_honors_a_fixed_speaker_count` fails. The red run that V1 records for `test_invalid_output_format_is_rejected_before_queueing` happened mid-development, so it cannot be replayed at base (that file fails in collection there). |
| V1 green | pass | The V1 green command gives 24 passed. |
| V2 gate | pass | ruff check: all checks passed. ruff format --check: 624 files already formatted. pytest `-m "not integration"`: 2621 passed, 2 skipped, 6 deselected. `stenographer --help`: exit 0. |
| M1 default relabel path unchanged | pass | `relabel.py` is unchanged on `dev` since the base. The diff to the default path only adds the `speaker_count` guard and the branch. The base's own `test_relabel.py` passes against HEAD (5 passed). A differential run over 40 seeded random cases (1–299 phrases, 1–5 voices, renamed labels, mixed durations) compared pickled outputs and progress calls of base and HEAD with `speaker_count=None`: the outputs are byte-identical (sha256 `96a2824c…`). The 58 V3 rule constants and code are untouched. |
| M2 fixed-count relabel memory/time | **fail** | Synthetic 192-dim embeddings, 3 voices, 2.2 s phrases, single process, peak RSS from `ru_maxrss`. |

## M2 probe (manager request)

| N phrases | speaker_count | time | peak RSS |
| --- | --- | --- | --- |
| 500 | 3 | 0.2 s | 0.08 GiB |
| 1000 | 3 | 1.0 s | 0.19 GiB |
| 2000 | 3 | 4.8 s | 0.61 GiB |
| 2000 | None (default) | 3.1 s | 0.26 GiB |
| 4000 | 3 | 23.9 s | 2.35 GiB |
| 9000 | None (default) | 108.1 s | 4.49 GiB |
| 9000 | 3 | 155.1 s | 11.72 GiB |

Judgement: `_relabel_fixed` pushes all N(N-1)/2 pairs into a Python heap, with no
threshold filter, on top of the (2N-1)^2 float32 matrix (about 1.2 GiB at N=9000).
Its memory grows faster than the default path's, which pushes only pairs at or above
the threshold. A 5.6 h file with a fixed speaker count needs about 12 GiB in the Files
engine process, about 2.6x the default path. That is not usable on a common 8–16 GB
machine, which also holds the ASR model in its child process. Files up to about 2000
phrases (about 1.3 h) stay under 1 GiB. The default path's 4.5 GiB at N=9000 is a
pre-existing cost of task 58 and is outside the scope of this task.
