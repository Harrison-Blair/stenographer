# VERIFIED — 104-relabel-memory

Verifier run on 2026-10-20 against head `da8f4b6`, base `origin/dev` `6e80174`.
The base source was extracted with `git archive origin/dev src` into a
scratch folder. Each version ran with its own `PYTHONPATH` and the
`/home/penguin/source/stenographer/.venv` interpreter.

| Item | Result | Observation |
| --- | --- | --- |
| V1 tests red/green | pass | Base: `test_relabel.py` errors during collection (`_best_active_pair` absent). Head: 7 passed. |
| V2 identical output | **fail** | Seeded sweep matches; a constructed input at the default threshold 0.5 gives different labels. See below. |
| V3 real audio | pass | Clusters 4, Labels 4, Speaker 1-4 = 3222.3 / 5174.5 / 4572.4 / 1700.9 s, 360 phrases under 1.2 s. Matches task 58. |
| V4 probes | pass | Table below. Head is well under 1 GiB and 30 s at 9,000. |
| Gate | pass | ruff check passed; ruff format: 654 files already formatted; pytest `-m "not integration"`: 2644 passed, 2 skipped, 6 deselected; `stenographer --help` ran. |

## V2 detail

Seeded sweep: 600 seeds, 1-500 phrases each, dimensions 8/32/192, 1-5
voices, a sustained minor voice at cosine 0.2-0.49 to a major voice,
scattered short residue (0.3-1.1 s), renamed labels, noise 0-0.2,
quantized and integer vectors (many exact ties and duplicates), thresholds
0.3-0.9. Each seed ran with `speaker_count` None, 1, 2, 3, 5. For each of
the 3,000 cases the SHA-256 of `pickle((result, progress_calls))` was the
same for base and head (0 differences).

Divergence: the base compares merged-cluster scores in float64 (heap keys
and the `score >= threshold` push check). The head stores the merged score
in the float32 matrix first, then compares the rounded value. When a merged
score lies in `[t - ulp/2, t)`, it rounds up to `t` in float32. The head then
merges and the base does not. Reproduction at the default threshold 0.5,
three phrases of 3.0, 3.0 and 6.0 s:

```text
vectors [[0.4999999403953552, 0.8660253882408142, 0.0],
         [0.5, 0.8659821152687073, 0.008660109713673592],
         [1.0, 0.0, 0.0]]
merged score float64 0.4999999850988388 -> float32 0.5
base [('speaker-1','L0'), ('speaker-1','L0'), ('speaker-2','L2')]
head [('speaker-1','L2'), ('speaker-1','L2'), ('speaker-1','L2')]
```

A wider search (3,000 small two-group instances, threshold set just above
each float64 merged score that float32 rounds up) gave 1,669 of 4,736
differing outputs. Pairs whose float64 scores differ but round to the same
float32 value can also be ordered by id instead of by score. This is a
precision change, not an exact tie, and V2 does not state it. Possible fix:
keep the merged scores (and `best_scores`) in float64 for comparison, or
otherwise match the base float64 keys.

## V4 probe (fresh processes, seed 95619, 192-dim, 3 voices, 2.2 s phrases)

| Version | Phrases | Time | Peak RSS |
| --- | ---: | ---: | ---: |
| Base | 2,000 | 8.627 s | 0.618 GiB |
| Base | 9,000 | 314.861 s | 11.835 GiB |
| Head | 2,000 | 0.159 s | 0.074 GiB |
| Head | 9,000 | 1.661 s | 0.424 GiB |

All runs produced one cluster. No audio or transcript text was written.
