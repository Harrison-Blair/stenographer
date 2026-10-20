# VERIFIED — 59-files-engine

Second verifier run on 2026-10-20 at `e14f702` (repair of the failed M2 item), from
the worktree root. The venv was a temporary `.venv` symlink to
`/home/penguin/source/stenographer/.venv` with `PYTHONPATH=$PWD/src`. The module path
resolved to this worktree. Red runs and the default-path comparison used a detached
worktree of the base `06bd0d3`. `relabel.py` on `dev` (`a1758da`) is unchanged since
that base. The fixed-path comparison used a detached worktree of the pre-repair
commit `5d778d4`. No microphone, real ffmpeg, model download, or integration test
was used. Synthetic embeddings only; no audio or transcript text.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red | pass | At base with the new tests copied in: `test_ffmpeg_decoder.py`, `tests/lib/files/test_engine.py`, and `tests/lib/files/test_media.py` fail in collection. `test_batch_relabel_honors_a_fixed_speaker_count` fails (1 failed, 5 passed). |
| V1 green | pass | The V1 green command gives 24 passed. |
| V2 / V4 gate | pass | `ruff check .`: all checks passed. `ruff format --check .`: 627 files already formatted. `pytest -m "not integration"`: 2621 passed, 2 skipped (absent public audio samples), 6 deselected. `stenographer --help`: exit 0. |
| M1 default path identical to dev | pass | 40 seeded random cases (1–299 phrases, 1–5 voices, center similarity 0–0.8, mixed durations, renamed labels), `speaker_count` not given, outputs and progress calls pickled. Base and HEAD give the same sha256 `0746278b…40e1f8`. |
| M2 fixed-count memory/time | pass | Fresh process per run, 192-dim embeddings, 3 voices, 2.2 s phrases, `speaker_count=3`, peak RSS from `ru_maxrss`. See the table below. The prior run measured 11.72 GiB / 155.1 s at N=9000. |
| V3 probe | pass | The V3 fixed-count rows reproduce: 0.077 s / 0.068 GiB at N=2000 and 0.776 s / 0.402 GiB at N=9000 (V3: 0.061 s / 0.069 GiB and 0.717 s / 0.406 GiB). The 9,000-phrase default-count row was not rerun. The manager stated that the default-path memory comes from task 58 and is out of scope. |
| V4 fixed-count output unchanged | pass | 40 seeded random cases × `speaker_count` 1–6 (240 runs). The pre-repair `5d778d4` and HEAD give the same sha256 `f5c20e4c…6986ba`. `test_relabel.py`: 6 passed. |
| Fixed-count quality | pass | K = 2–6 orthogonal voice centers, noise σ 0.03, random voice order, durations 0.3–6 s, N ∈ {3K, 60, 400}, 10 seeds each, `speaker_count=K`. 145 of 145 runs give exactly the true partition. |

## M2 probe

| N phrases | Voice-center similarity | speaker_count | Time | Peak RSS | Clusters |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2000 | 0.75 | 3 | 0.077 s | 0.068 GiB | 3 |
| 4000 | 0.0 | 3 | 0.170 s | 0.147 GiB | 3 |
| 9000 | 0.75 | 3 | 0.776 s | 0.402 GiB | 3 |
| 9000 | 0.0 | 3 | 0.784 s | 0.402 GiB | 3 |

The prior failed verdict (t59-verifier-1) recorded 11.72 GiB / 155.1 s at N=9000 for
the fixed count. The repair replaces the all-pairs Python heap with a dense N×N
float32 matrix and a nearest-neighbor chain. Memory is now bounded by that matrix
(about 0.3 GiB at N=9000).
