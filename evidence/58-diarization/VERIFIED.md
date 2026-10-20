# VERIFIED — 58-diarization (repair 3 re-verification, F4/F5)

Fourth independent verifier run, on 2026-10-20 at `b6662b9`. This run checks
repair 3 for findings F4 and F5. `.venv` was a temporary symlink to
`/home/penguin/source/stenographer/.venv`. `PYTHONPATH=src` made the tests and
the CLI load this worktree. The red runs used two detached worktrees with this
task's test files copied in. One was at the `dev` merge base `033be49`, and one
was at the pre-repair head `ac5a804`. Previous verifier runs are in the git
history of this file.

| Item | Result | Observation |
| --- | --- | --- |
| V1 live and batch clustering (red/green) | pass | Base `033be49`: `test_relabel.py` fails at collection (`No module named 'stenographer.lib.live.relabel'`), and the 3 short-phrase tracker tests fail. Head: the targeted suite (`test_speaker_tracker.py`, `test_relabel.py`, `test_live_session.py`, `tests/cli/live/test_app.py`, `test_store.py`) gives 43 passed, 1 skipped. The skip is the kept 3-clip real-model test, whose public clips are absent from `tmp/live_audio`. |
| V2 stop pass, revisions, controls (red/green) | pass | Base `033be49`, without `test_relabel.py`: 7 failed, 31 passed, 1 skipped. The 7 failures are the 3 `test_live_session.py` stop/skip/failure tests, `test_app.py::test_second_q_skips_relabel_and_stop_progress_is_visible` (no `Relabeling speakers 2/5 · q to skip` in the status line), and the 3 short-phrase tracker tests. Head: all of these pass in the 43 above. |
| V3 real-audio check (both runs again) | pass | Baseline (`--baseline`): `Clusters: 457`, `Labels: 457`, `Phrases under 1.2 s: 360`. All 460 lines are identical to V3.md. Fixed: `Clusters: 4`, `Labels: 4`, Speaker 1–4 = 3222.3 / 5174.5 / 4572.4 / 1700.9 s, `Phrases under 1.2 s: 360`. Identical to V3.md. 4 labels matches the 4 speakers that the user confirmed. Fixed run time: 2 min 13 s, rc 0. |
| V4 gate | pass | `ruff check .`: all checks passed. `ruff format --check .`: 590 files already formatted. `pytest -m "not integration"`: 2567 passed, 2 skipped (absent public audio fixtures), 6 deselected. `stenographer --help`: rc 0. |
| V5 F4/F5 regressions (red/green) | pass | Pre-repair `ac5a804`: `test_batch_relabel_keeps_sustained_minor_voice_at_realistic_similarity` and `test_batch_relabel_short_residue_does_not_create_speakers` fail. The first gives 1 label instead of 2. The second gives 4 labels instead of 1. Result: 2 failed, 13 passed, 1 skipped. Head: both pass. |

## Edge-case probes (synthetic embeddings, threshold 0.5)

Voice A is `[1, 0, 0]`. Voice B is at cosine c to A.

| Probe | Result |
| --- | --- |
| A 100 s; B five 3 s turns every 4 s (15 s in 20 s), c = 0, 0.1, 0.2, 0.3, 0.4, 0.45, 0.49 | 2 labels for each c. **F4 repaired.** |
| Same, c = 0.55 (above the live threshold) | 1 label (merged, as designed) |
| A as 20 × 5 s phrases; same B, c = 0.2 / 0.3 / 0.4 / 0.49 | 2 labels for each c |
| A 100 s; 1, 4 or 20 orthogonal 0.8 s residue phrases, 50 s apart | 1 label (`Speaker 1`) for each count. **Residue adds no label.** |
| A 100 s; B 8 × 2 s turns every 4 s (16 s), c = 0.3 | 2 labels |
| A 100 s; B 8 × 2 s turns every 30 s or every 60 s (16 s), c = 0.3 | **1 label: B is merged into A** |
| A 100 s; B 15 × 2 s turns every 60 s (30 s), c = 0.3 | 2 labels, because B's 30 s is at least 20% of A's speech, so B is a core cluster |
| No anchors: 4 phrases of 0.3–1.1 s with orthogonal embeddings | 1 label. Every phrase takes the speaker id and label of the longest phrase. |
| No anchors: `Alice` 0.9 s, `Speaker 2` 0.7 s | Both become `Alice`, so a user rename on the longest phrase is kept |
| No anchors: progress callback | `(0, 2)`, then `(2, 2)` |

**Known limit (by design).** A minor voice gets its own label only in one of
two cases:

- It has 15 s of phrases that are each at least 2 s long, inside one 30-second
  window, and those phrases are at least two-thirds of its speech.
- Its speech is at least 20% of the largest cluster's speech.

A minor voice that speaks in sparse turns, for example a 2 s turn each minute,
and has less than 20% of the main voice's speech is merged into the most
similar voice. Its turns get that voice's label. A voice that speaks only in
phrases shorter than 2 s cannot get its own label either.

**Note (not a defect).** The no-anchor early return does not call
`should_cancel`. That return is a constant-time relabel and runs no clustering,
so a second `q` has nothing to interrupt there.

## Data handling

The real-audio runs printed only counts and talk times. They wrote no audio,
transcript text, or decoded text to evidence or logs. The probes used synthetic
vectors only. The temporary worktrees, the scratch outputs and the `.venv`
symlink were removed after the run.
