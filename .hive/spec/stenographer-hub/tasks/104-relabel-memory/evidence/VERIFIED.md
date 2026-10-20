# VERIFIED — 104-relabel-memory

Second verifier run on 2026-10-20, against head `f7b797b` (repair: keep
float64 relabel scores). The base is `origin/dev` `6e80174`. The first run
(head `da8f4b6`) failed V2 on float32 rounding of merged scores.

Method: `git archive` extracted the base (`6e80174`) and the pre-repair head
(`da8f4b6`) into scratch folders. Each version ran with its own `PYTHONPATH`
and the `/home/penguin/source/stenographer/.venv` interpreter.

| Item | Result | Observation |
| --- | --- | --- |
| V1/V5 tests red/green | pass | Head `test_relabel.py` against base source: collection error (`ImportError`, `_best_active_pair` absent). Against pre-repair `da8f4b6` source: 1 failed (`test_default_relabel_does_not_merge_when_float64_score_is_below_threshold`), 7 passed. Head: 8 passed. |
| V2 identical output | pass | Base vs head: 8,000 cases, 0 differences (details below). |
| V3 real audio | pass | Clusters 4, Labels 4, Speaker 1-4 = 3222.3 / 5174.5 / 4572.4 / 1700.9 s, 360 phrases under 1.2 s. Matches task 58. |
| V4 probes | pass | Head at 9,000 phrases: 1.916 s, 0.730 GiB. Table below. |
| Gate | pass | `ruff check .`: all checks passed. `ruff format --check .`: 656 files already formatted. `pytest -m "not integration"`: 2645 passed, 2 skipped, 6 deselected. `stenographer --help`: exit 0. |

## V2 detail

Each case compared the SHA-256 of `pickle((ordered (speaker_id, label) pairs, progress calls))`.

- Targeted near-threshold search: 5,000 cases, 3-6 phrases, dimensions
  3/8/32, durations 1.5-6.0 s. Phrases 0 and 1 are the top pair and merge
  first. The threshold is `nextafter(m, +inf)`, where `m` is the float64
  merged score against phrase 2 and `float32(m) > m`. The base kept a split
  in 2,883 cases. Head: 0 differences. Sensitivity check: the same search
  against pre-repair `da8f4b6` gave 107 differences.
- Seeded sweep: seeds 0-599, 1-399 phrases, dimensions 8/32/192, 1-5 voices,
  noise 0-0.2, optional sustained minor voice near voice 0, half-step and
  integer quantized vectors (exact ties), duplicate vectors, short residue
  (0.3-1.1 s), renamed labels, thresholds 0.3-0.9. Each seed ran with
  `speaker_count` None, 1, 2, 3 and 5 (3,000 cases). 0 differences.
- Aggregate SHA-256 for base and head:
  `669d49d0f8b11b8a168a2260317fa5f364c372d30bcd6bfa5d6d51ba554c6af1` (same).

## V4 probe

Fresh process per row. Seed 95619, 192 dimensions, 3 voices with pairwise
centre cosine 0.75, noise sd 0.01, 2.2 s phrases spaced 2.3 s. Peak RSS is
`ru_maxrss`. It includes Python, imports and input data. All runs gave one
cluster. The head rows ran after the base probe ended, with no other probe
running.

| Version | Phrases | Time | Peak RSS |
| --- | ---: | ---: | ---: |
| Base `6e80174` | 2,000 | 8.857 s | 0.624 GiB |
| Base `6e80174` | 9,000 | 340.236 s | 11.838 GiB |
| Head `f7b797b` | 2,000 | 0.166 s | 0.093 GiB |
| Head `f7b797b` | 9,000 | 1.916 s | 0.730 GiB |

## Note on requirement 1

The repair stores the `anchor × anchor` matrix as float64. The brief asks
for "at most a dense float32 similarity matrix". At 9,000 anchors the
float64 matrix is about 0.65 GB. A float32 matrix would be about 0.32 GB.
The pre-repair head peak was 0.42-0.43 GiB. The measured targets are met:
peak RSS is under 1 GiB and time is under 30 s. No per-pair Python objects
or heaps remain. Requirement 2 requires the float64 scores: the base orders
merges by float64 keys. This verifier counts requirement 1 as met through
the measured target. The manager can decide whether the 2× matrix size is
acceptable.

No audio or transcript text was written. The recording was read by its
absolute path only.
