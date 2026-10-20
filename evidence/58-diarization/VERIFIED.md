# VERIFIED — 58-diarization (F3 repair re-verification)

Third independent verifier run on 2026-10-20 at `a857439`. This run checks the
repair for finding F3 from the second run. `.venv` was a temporary symlink to
`/home/penguin/source/stenographer/.venv`, and `PYTHONPATH=src` made the tests
and the CLI load this worktree. The red runs used detached worktrees with this
task's tests copied in. One was at the `dev` merge base `033be49`, and one was
at the pre-repair head `a857439~1` (`158eb24`).

| Item | Result | Observation |
| --- | --- | --- |
| V1 live and batch clustering (red/green) | pass | Base: `test_relabel.py` fails at collection, and the 3 short-phrase tracker tests fail. Pre-repair: `test_batch_relabel_keeps_distinct_minor_voice` fails (1 failed, 3 passed). Head: targeted suite 42 passed, 1 skipped. The skip is the 3-clip real-model test, which is kept but whose public clips are absent. |
| V2 stop pass, revisions, controls (red/green) | pass | Base: 7 failed, 25 passed, 1 skipped (3 `test_live_session.py` stop tests, `test_app.py::test_second_q_skips_relabel_and_stop_progress_is_visible`, 3 tracker tests). Head: all pass. |
| V3 real-audio check (rerun) | **fail** | Baseline: `Clusters: 457`, `Labels: 457`, which is line-for-line identical to V3.md. Fixed: `Clusters: 5`, `Labels: 5` (Speaker 1–5: 3173.0 / 5147.7 / 4549.6 / 142.3 / 1657.6 s), which is line-for-line identical to V3.md. Phrases under 1.2 s: 360. The user listened to the 12 longest phrases of the new 142.3 s `Speaker 4` (172 phrases, about 0.8 s each, spread over all 5.6 h). All 12 were existing speakers or stray noise. That makes `Speaker 4` a false split. The prior head gave 4 labels, so this is a regression. |
| V4 gate | pass | `ruff check .` printed all checks passed. `ruff format --check .` reported 590 files formatted. `pytest -m "not integration"`: 2566 passed, 2 skipped, 6 deselected. `stenographer --help` returned rc 0. |
| F3 repair (distinct minor voice kept) | **fail** | See F4. The 0.05 bound protects only near-orthogonal voices. |

## Findings

**F4 (F3 not repaired). The 0.05 cosine bound does not keep a realistic
distinct minor voice separate.**
A small cluster (under 20% of the largest cluster's speech time) is still
folded into the nearest core cluster when its duration-weighted cosine is at
least `_MINIMUM_SMALL_CLUSTER_SIMILARITY = 0.05`
(`src/stenographer/lib/live/relabel.py:17`). The live rule and the
agglomerative step treat anything below 0.50 as a different speaker.

Synthetic probe at head (threshold 0.5; voice A 100 s, voice B 15 s, cosine c
between them):

| c | 0.00 | 0.04 | 0.06 | 0.10 | 0.20 | 0.30 | 0.40 | 0.49 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| labels | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 1 |

Real cosines from this embedding model on the consented recording: the centroids
of the final clusters score 0.40 to 0.66 against each other, which is the range
for different speakers. Of the 469 small agglomerative clusters, only 3 (22.1 s
in total) score below 0.05 against every core cluster. So a real minor speaker
with this model would score far above 0.05 and still be merged. The regression
test covers only cosine 0.

**F5 (V3 regression). The repaired pass gives 5 labels on a 4-speaker
recording, and one of them is noise.**
The clusters below 0.05 seed a new core cluster. Later short phrases and small
clusters then join it, and it ends up as a 142.3 s `Speaker 4` with centroid
cosines of 0.20 to 0.24 against the other four. User listening (above) confirms
that it is a false split, with no new voice in it. The repair therefore makes
the stop pass worse on the one real recording without protecting realistic
minor voices.

Possible repairs: base the fold bound on the live threshold or on the measured
different-speaker range instead of 0.05. Do not let low-similarity residue or
short phrases seed a labelled speaker (for example, require a minimum of long
speech before a non-core cluster survives). Add a synthetic test with a minor
voice at a realistic cosine (0.2 to 0.4). Then rerun V3 and show 4 labels.

## Data handling

The probe saved embeddings, durations, and phrase start times only, in the
scratch directory, and the file was deleted afterwards. No audio, transcript
text, or decoded text was written to evidence or logs. The listening check was
done by the user.
