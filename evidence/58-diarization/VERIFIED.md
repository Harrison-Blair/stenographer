# VERIFIED — 58-diarization (repair re-verification)

Second independent verifier run on 2026-10-20 at `f4388d7`, after the repair
for the first run's finding F1. `.venv` was a temporary symlink to
`/home/penguin/source/stenographer/.venv`. The tests and CLI loaded this
worktree's `src/` through `PYTHONPATH=src`. The red runs used detached
worktrees with this task's `tests/` copied in. One was at the `dev` merge base
`033be49`. The other was at the pre-repair head `0324a5e`.

| Item | Result | Observation |
| --- | --- | --- |
| V1 live and batch clustering (red/green) | pass | Base: `test_relabel.py` fails at collection, and the 3 short-phrase tests in `test_speaker_tracker.py` fail. Pre-repair `0324a5e`: 2 `test_relabel.py` tests fail (labels `Speaker 4`/`Speaker 172` were kept, and `Renamed voice` was on both voices). Head: 38 passed, 1 skipped. The 3-clip real-model test is kept. It skips because its public clips are absent. |
| V2 stop pass, revisions, controls (red/green) | pass | Base: 8 failed, 27 passed (3 `test_live_session.py` stop tests, `test_app.py::test_second_q_skips_relabel_and_stop_progress_is_visible`, the handler test, and the 3 tracker tests). Head: all pass. |
| V3 real-audio check (rerun) | pass | Reran both commands on the consented recording, about 4 min each. Baseline: `Clusters: 457`, `Labels: 457`. Fixed: `Clusters: 4`, `Labels: 4` (Speaker 1–4: 3217.9 / 5184.4 / 4585.5 / 1682.3 s). Phrases under 1.2 s: 360. Both outputs are line-for-line identical to V3.md. Only counts and timings were printed. |
| V4 gate | pass | `ruff check .` all passed. `ruff format --check .` reported 590 files formatted. `pytest -m "not integration"`: 2565 passed, 2 skipped, 6 deselected. `stenographer --help` prints usage (rc 0). |
| Prior F1 (unique labels, rename mapping) | pass | Probe: voices A (10 s) and B (5 s) were both live "Speaker 1", plus 2 s of B as "Speaker 2". Result: `Speaker 1` on A and `Speaker 2` on B. With A renamed to "Alice", the result was `Alice` on A and `Speaker 1` on B. Clusters now count equal to labels in V3. |
| Prior F2 (renumber unnamed labels) | pass | Unnamed clusters are numbered 1..N in order of first appearance. Renamed labels are kept. |
| Requirement 2: batch pass keeps distinct voices | **fail** | See F3. |

## Findings

**F3 (fails requirement 2). The stop pass merges a distinct speaker who talks
less than 20% as much as the top speaker.**
`_MINIMUM_CLUSTER_SPEECH_FRACTION = 0.20` (`src/stenographer/lib/live/relabel.py:16`)
is applied after agglomerative clustering. It marks every cluster with less
than 20% of the largest cluster's speech time as non-core. It then joins that
cluster to the nearest core cluster, whatever their similarity. The threshold
does not apply to this step. The code comment says the value was chosen to keep
4 voices in the same consented recording that V3 uses to judge the result.
That makes V3 tuned to this one file rather than an independent check.

Synthetic probe at head, using the default threshold 0.5:
- Voice A had 100 s with embedding `[1,0,0]`. Voice B had 15 s with an
  orthogonal embedding `[0,0,1]` (cosine 0). Both phrases are well above
  1.2 s. Result: one cluster, with both lines labelled `Speaker 1`.
- The same probe with B at 25 s: two clusters, as expected.

Effect: in an unbalanced conversation, the stop pass removes a real speaker.
Examples are an interview, a lecture with questions, or a meeting with one
main presenter. The live labels had already separated that speaker. The user
cannot fix this with a rename. The brief asks for a batch method "with a
threshold". The live rule for long phrases must stay as it is. No test covers
this case. Possible repairs: use a small absolute time floor (only fold
clusters with very little speech time), or fold a small cluster only when its
similarity to the target is above a lower bound. Add a synthetic test for a
distinct minor voice. Then rerun V3 to show that it still gives about 4
labels.

**Note (not a failure).** The rename detection treats a label as renamed when
it differs from `Speaker <n>` for its own `speaker_id`. Suppose a user renames
`speaker-3` to `Speaker 1`. That label counts as renamed and it is kept. This
is acceptable.
