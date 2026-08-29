# Q02 — Silero VAD parameter grid

Status: planned (2026-08-29)

## 1 Hypothesis

Relaxing the repo's tighter-than-library VAD parameters (`vad_threshold`,
`vad_min_speech_duration_ms`, `vad_min_silence_duration_ms`,
`vad_speech_pad_ms`) reduces `leading_miss_rate` on the `cue` lane by ≥ 0.05
absolute **and** reduces the `empty` count on the `quiet` lane by ≥ 50 % of its
baseline value, without moving `wer_mean` by more than +0.002, without raising
`rtf_p95` by more than ×1.25, and without raising `trailing_junk_rate` on the
`tail` lane by more than `max(0.02, 2 × noise.trailing_junk_rate)`.

## 2 Symptom & mechanism

Two of the four owner-reported symptoms in `docs/experiments/README.md`:

1. **The first words of an utterance go missing** although the overlay showed
   input, and `activate_ms ≤ 0.4` proves capture was not late.
2. **Quiet utterances vanish entirely.** Two of the nine logged utterances
   passed the RMS gate (`peak_rms ≈ 0.024`, ≈2.6 s) and still reached the
   decoder with `vad_frames=0` — the VAD pre-filter discarded them wholesale.

The shipped parameters are `src/stenographer/transcribe/model.py:32-37`:

```python
_VAD_PARAMETERS = {
    "threshold": 0.5,
    "min_speech_duration_ms": 100,
    "min_silence_duration_ms": 500,
    "speech_pad_ms": 250,
}
```

They are handed to `WhisperModel.transcribe(vad_parameters=...)` at
`model.py:116-117`, which converts them to a `VadOptions` and calls
`get_speech_timestamps` at
`.venv/lib/python3.14/site-packages/faster_whisper/transcribe.py:884-893`;
`duration_after_vad` (→ `TranscriptionResult.vad_seconds` → the logged
`vad_frames`) is computed there from the concatenated chunks.

Library defaults are `0.5 / 0 / 2000 / 400`
(`faster_whisper/vad.py:37-42`). Three of the four repo values are **tighter**
than the library's, and each maps onto one of the two symptoms:

- **Onset loss.** The chunk is opened only at the first window whose Silero
  probability reaches `threshold` (`vad.py:108-111`). Everything before that
  window is discarded except for `speech_pad_ms` of pre-trigger audio, and
  only for the *first* chunk (`vad.py:163`). At 250 ms instead of the
  library's 400 ms, a soft onset that takes >250 ms to cross 0.5 loses its
  first syllable — and a cue plus a gap in front of the speech (`cue` lane)
  makes the trigger later still, or triggers on the cue itself and then closes
  before the speech starts.
- **Quiet-speech drop.** `threshold = 0.5` is an absolute probability on a
  model that is level-sensitive in practice; a low-gain mic can keep the whole
  utterance below it, so `speeches` stays empty, `collect_chunks` returns one
  empty array, `duration_after_vad = 0`, the decoder sees nothing and the
  transcript is empty. `min_speech_duration_ms = 100` compounds it: a chunk
  that does trigger briefly is dropped unless it exceeds 100 ms
  (`vad.py:145-149` for a closed chunk, `vad.py:154-159` for the final one) —
  the library default of `0` drops nothing.
- **`min_silence_duration_ms = 500`** (library 2000) splits at every half-second
  pause, so a mid-utterance breath ends a chunk; the tail of that chunk keeps
  only `speech_pad_ms` and the next chunk's onset is padded by at most the
  same (`vad.py:165-181`). Raising it keeps a natural pause *inside* one chunk
  instead of cutting either side of it.

Relaxing these acts directly on both mechanisms: a lower `threshold` triggers
on quieter speech (and lowers the library's derived `neg_threshold =
max(threshold - 0.15, 0.01)`, `vad.py:94-95`, so a chunk also stays open
longer); a larger `speech_pad_ms` restores more pre-trigger audio to the first
chunk; `min_speech_duration_ms = 0` stops brief triggers being thrown away;
a larger `min_silence_duration_ms` stops mid-utterance splitting.

Two second-order effects to keep in view. Relaxation *raises* `vad_seconds`,
which loosens `_validate_output`'s word ceiling (`max(12, ceil(8 ×
vad_seconds))`, `model.py:200`) — a relaxation, never a tightening, so it
cannot newly trip `PathologicalOutputError`. And retained inter-chunk gaps are
capped at ≈`2 × speech_pad_ms` (`vad.py:165-170`), which is why
`hallucination_silence_threshold = 2.0` (`model.py:27`) is mostly inert today:
raising `min_silence_duration_ms` to 2000 lets up to 2 s of silence sit inside
a single chunk and re-arms that mechanism. That interaction belongs to **Q07**;
Q02 only guards against it (§8).

## 3 Prerequisites

**Harness pieces.** `scripts/asr_corpus.py`, `scripts/asr_metrics.py`,
`scripts/asr_experiment.py` with `preflight`, `baseline`, `run` and `compare`,
their pure tests green, and the `DecodeOptions` seam of `HARNESS.md` §3.2
implemented and pinned.

**Injection fields.** `decode` lane only — `DecodeOptions.vad_threshold`,
`vad_min_speech_duration_ms`, `vad_min_silence_duration_ms`,
`vad_speech_pad_ms`. No `config` overrides at all. Because these are `decode`
fields, **`engine: "inprocess"` is mandatory for every variant in this plan**
(`HARNESS.md` §3: a non-empty `decode` with `engine: "subprocess"` is a
harness error). Every variant states `inprocess` explicitly rather than
relying on `auto`, so the screening baseline replay — whose `decode` is empty
and which `auto` would resolve to `subprocess` — runs on the same engine as
everything it is compared with.

**Corpus lanes.** `base`, `tail`, `cue` and a new `quiet` lane.

- `base` — 100 clips. Regression control.
- `tail` — 300 clips (1 s / 3 s / 5 s of appended −60 dBFS room tone). Produced
  and characterised by **Q09**; Q02 uses it as a guard lane only.
- `cue` — 300 clips (`record_start` at −12 dB plus a 0 / 100 / 300 ms gap
  prepended). **Produced and validated by Q10** — Q02 cannot start until Q10's
  lane exists in the manifest and its baseline `leading_miss_rate` is on
  record. This is a hard dependency, not a preference: the cue lane *is* the
  measurement instrument for symptom 1.
- `quiet` — **does not exist in `HARNESS.md` §2.4 and must be added.** Spec
  below.

### 3.1 Required addition — the `quiet` lane (FORK)

`HARNESS.md` §2.4 defines only `tail` and `cue`. Symptom 2 cannot be measured
without a lane that reproduces it, so `scripts/asr_corpus.py` gains a third
augmentation, generated from `base` clips only, pure numpy, deterministic:

For each base clip and each `target_peak_rms ∈ {0.030, 0.020}`:

1. `peak = stenographer.audio.speech_gate_stats(base_samples, 16000,
   0.0005).peak_rms` — the max over 50 ms frame RMS. The core function is
   reused deliberately: the lane's level is then defined by exactly the
   statistic the daemon logs as `peak_rms`, so "peak_rms ≈ 0.024" in the
   owner's log and "quiet=0.020" in the manifest are the same quantity.
2. `gain = target_peak_rms / peak`. If `gain > 1.0` the clip is **skipped**
   for that target (the lane never amplifies); the generator prints the skip
   count. On LibriSpeech `test-clean` no skips are expected.
3. `quiet = base_samples * gain`.
4. Add a noise floor: Gaussian noise at −60 dBFS RMS (σ = 0.001), seeded
   `random.Random(zlib.crc32(clip_id.encode()) ^ int(target_peak_rms *
   100000))` → `numpy.random.default_rng(seed)`, i.e. the same generator and
   the same −60 dBFS level the `tail` and `cue` lanes already use. **This step
   is not optional.** Pure attenuation scales the source noise floor down with
   the speech and leaves the SNR untouched, which is not what a low-gain mic
   does; the fixed floor puts the clip at ≈26–30 dB SNR, which is.
5. Write 16 kHz mono 16-bit PCM to
   `build/asr-corpus/wav/quiet/<id>+quiet<mmm>.wav`, where `<mmm>` is the
   target × 1000 zero-padded to three digits (`quiet030`, `quiet020`). At
   16-bit, σ = 0.001 is ≈33 LSB and a 0.020 peak is ≈650 LSB, so quantization
   adds nothing measurable.

Manifest fields: `lane: "quiet"`, `derived_from: <base id>`, `tags: [<stratum>,
"quiet=0.020"]`, and

```json
"augmentation": {"kind": "attenuated", "target_peak_rms": 0.020,
                 "gain": 0.0731, "rms_dbfs": -60.0}
```

(`gain` rounded to four decimals, per clip). `kind: "attenuated"` joins
`trailing_noise` and `leading_cue` in `HARNESS.md` §2.5's list — a
documentation change there, not a schema change. Lane size: 200 clips
(100 × 2 levels), ≈48 MB.

Sanity property the generator asserts: every produced clip still passes the
shipped RMS gate (`min_speech_rms = 0.0005`, `config.py:249`) —
`speech_gate_stats(quiet, 16000, 0.0005).passed is True`. That is what makes
the lane faithful to the log: the owner's lost utterances *passed* the gate
and were killed by VAD alone.

**Fork.** Adding a lane changes the manifest, and `compare` refuses a
`manifest_sha256` mismatch (`HARNESS.md` §6.4) while §7.3 case 2 makes a
manifest change a re-baseline trigger. Two ways out:

- **(a, taken)** Land the `quiet` generator in the foundation commit,
  *before* the baseline is established. `HARNESS.md` §2.4 now defines the lane
  and §7.1's baseline covers it along with the other six. Cost: +200 clips ×
  3 repeats × ≈5 s ≈ 50 min inside the one overnight baseline run. Nothing is
  thrown away.
- **(b)** Add the lane afterwards and re-baseline. Less damaging than it was —
  `HARNESS.md` §2.5's per-lane `lane_sha256` means only comparisons that score
  the `quiet` lane are affected (§6.4) — but still an extra run, and unnecessary
  now that (a) is taken.

Recommendation: **(a)**. If the baseline already exists when this plan starts,
(b) is forced and its cost belongs to Q02's budget.

### 3.2 Required addition — `noise` for `empty` (FORK)

`HARNESS.md` §7.1 records the three-repeat spread of `wer_mean`,
`trailing_junk_rate`, `leading_miss_rate`, `decode_ms_p50` and
`first_response_ms_p50`, and `validate_variant` enforces "margin ≥ 2 × noise
for the target metric". This plan's quiet-lane target is `empty`, which the
noise block does not carry, so that check cannot be evaluated.

**Fork.** Either (a) add `empty` to the `noise` block in `HARNESS.md` §7.1 —
one more spread over repeats already being run, no extra decode cost — or
(b) target `deletion_rate` on the quiet lane as a proxy. Recommendation:
**(a)**; `empty` is the symptom itself, and a proxy that moves for a different
reason would be worse than no proxy. Until (a) lands, `validate_variant` must
skip the noise check for a target metric absent from the block rather than
refusing the run.

The cue-lane target `leading_miss_rate` is already in the noise block and
needs nothing.

### 3.3 A guards-only verdict (settled)

`decide` (`HARNESS.md` §6.2) requires the target metric to *improve* by its
margin, and §7.1 requires that margin to be ≥ 2 × noise, hence > 0. A run
whose only purpose is to show that `tail`-lane junk did **not** get worse was
therefore once not expressible as a thresholds file.

**Settled: `HARNESS.md` §6.1 is the canonical mechanism.** `"target": null`
means "guards only" (rule 2 skipped, rules 1/3/4/5 still evaluated) and the
`guards` array expresses "must not get worse" as a `max_regression` entry. The
tail-lane guard belongs there. §6.4's plan-level arithmetic is kept as the
**fallback** — it is exactly the same inequality, computed by hand — for the
case where this plan runs before the foundation commit has landed `guards`; the
executing agent performs it unconditionally, and *additionally* runs
`q02f-guard` through `run --baseline` and requires exit 0.

**Baseline.** `docs/experiments/baseline.json` present, `schema == 1`,
covering lanes `base`, `tail`, `cue`, `quiet`, with a `noise` block carrying
`leading_miss_rate`, `trailing_junk_rate`, `wer_mean` and (per §3.2) `empty`,
and `per_lane` aggregates for all four lanes.

## 4 Variant matrix

Full factorial over the four axes would be 3 × 3 × 2 × 3 = 54 variants ×
900 clips — ≈9.9 h of decode for a question whose axes are largely separable.
The matrix is staged instead.

All variants: `"schema": 1`, `"plan": "Q02"`, `"tags_any": []`,
`"tags_all": []`, `"engine": "inprocess"`, `"repeats": 1` (temperature stays
at its default `(0.0,)`, so `HARNESS.md` §8.3's repeat rule does not apply),
`"config": {}`. Only `name`, `lanes` and `decode` differ.

### Stage A — one factor at a time (8 runs, screening)

Lanes for every stage-A variant: `["base", "tail", "cue", "quiet"]` (900
clips). Checked in under `docs/experiments/variants/Q02/`.

| # | File | `decode` (only the fields shown; the rest keep `DecodeOptions` defaults) |
|---|---|---|
| A0 | `q02a-base.json` | `{}` — the shipped literals, re-run in-process |
| A1 | `q02a-pad400.json` | `{"vad_speech_pad_ms": 400}` |
| A2 | `q02a-pad600.json` | `{"vad_speech_pad_ms": 600}` |
| A3 | `q02a-sil1000.json` | `{"vad_min_silence_duration_ms": 1000}` |
| A4 | `q02a-sil2000.json` | `{"vad_min_silence_duration_ms": 2000}` |
| A5 | `q02a-minspeech0.json` | `{"vad_min_speech_duration_ms": 0}` |
| A6 | `q02a-thr040.json` | `{"vad_threshold": 0.4}` |
| A7 | `q02a-thr030.json` | `{"vad_threshold": 0.3}` |

Full text of A1 (every other file differs only in `name` and `decode`):

```json
{
  "schema": 1,
  "name": "q02a-pad400",
  "plan": "Q02",
  "lanes": ["base", "tail", "cue", "quiet"],
  "tags_any": [],
  "tags_all": [],
  "engine": "inprocess",
  "repeats": 1,
  "config": {},
  "decode": {"vad_speech_pad_ms": 400}
}
```

The baseline values are the fourth cell of each axis and are measured once, as
A0, rather than repeated per axis: `speech_pad_ms 250`,
`min_silence_duration_ms 500`, `min_speech_duration_ms 100`, `threshold 0.5`.

### Stage B — interaction grid (≤ 11 runs)

Generated mechanically from stage A by §6.2's rule; same lanes, same shape,
one file per combination, named `q02b-<token>-<token>[…]` with the tokens
`pad400`, `pad600`, `sil1000`, `sil2000`, `minspeech0`, `thr040`, `thr030` in
axis order (pad, sil, minspeech, thr). Example:

```json
{
  "schema": 1,
  "name": "q02b-pad400-thr040",
  "plan": "Q02",
  "lanes": ["base", "tail", "cue", "quiet"],
  "tags_any": [],
  "tags_all": [],
  "engine": "inprocess",
  "repeats": 1,
  "config": {},
  "decode": {"vad_speech_pad_ms": 400, "vad_threshold": 0.4}
}
```

### Finals — three lane-scoped verdict runs

`HARNESS.md` §6.1 requires a thresholds file's `lanes` to equal its variant's,
and `decide` computes the target over that whole lane set. The two targets
live on different lanes, so the finalist's settings are checked in three
times, each scoped to the lanes its verdict is about. The decode settings in
all three are identical — whatever the finalist is — so this costs one extra
model load, not extra decoding.

| File | `lanes` | Clips | Role |
|---|---|---|---|
| `q02f-cue.json` | `["cue"]` | 300 | Formal verdict, target `leading_miss_rate` |
| `q02f-quiet.json` | `["quiet"]` | 200 | Formal verdict, target `empty` |
| `q02f-guard.json` | `["base", "tail"]` | 400 | Regression guard (§3.3 fork) |

Thresholds files: `docs/experiments/variants/Q02/thresholds-cue.json`,
`thresholds-quiet.json`, and — only if §3.3 fork (a) landed —
`thresholds-guard.json`. Contents in §6.

## 5 Procedure

Every command runs from the repo root with the repo venv. No step needs a
human. Where a command's exit code is not listed, `2` always means stop and
report a harness error.

If `scripts/asr_experiment.py run` names its variant positionally rather than
with `--variant`, pass it positionally; nothing else about the invocation
changes.

**Step 0 — preconditions.**

```sh
.venv/bin/python scripts/asr_experiment.py preflight
```

Exit `0` → continue. Exit `2` → stop (model not cached, no GPU, manifest
mismatch, dirty-tree baseline, <1 GiB free).

Then assert, from `build/asr-corpus/manifest.json` and
`docs/experiments/baseline.json`, without running anything:

1. the manifest contains lanes `base`, `tail`, `cue` and `quiet`, with
   100 / 300 / 300 / 200 clips;
2. `baseline.json`'s `corpus.manifest_sha256` equals the manifest's digest;
3. `baseline.json` has `per_lane` entries for all four lanes;
4. `baseline.json.noise` carries `leading_miss_rate`, `trailing_junk_rate`,
   `wer_mean` and `empty`.

Any failure → stop, exit 2, and report which of §3's forks is unresolved.

**Step 1 — quiet-lane symptom check.** Read
`baseline.json.aggregates.per_lane["quiet"].empty`, call it `E0`.

- `E0 ≥ 20` (≥ 10 % of 200 clips) → the lane reproduces symptom 2; continue
  with both arms.
- `E0 < 20` → regenerate the `quiet` lane with the extra target
  `target_peak_rms = 0.012` (tag `quiet=0.012`, 300 clips total), re-baseline
  **that lane only**, and re-read `E0`. Regenerating one lane moves only its own
  `corpus.lane_sha256` entry (`HARNESS.md` §2.5), and `compare` refuses on the
  compared lanes' digests alone (§6.4), so no other plan's in-flight comparison
  is invalidated and no full re-baseline is owed. If still `< 20`, record in §9 that
  the quiet arm's symptom was not reproduced at 16 kHz clean-source levels,
  drop the quiet arm (no `q02f-quiet` run, no quiet term in §6.2's score), and
  continue with the cue arm alone. Do not weaken the threshold to make it pass.

**Step 2 — stage A.** For each of A0…A7 in matrix order:

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q02/q02a-<name>.json
```

No `--baseline`, no `--thresholds`: these are screening runs and their exit
code carries no verdict. Exit `0` → record the run directory. Exit `2` →
stop.

After A0, cross-check the engines: with `WB0 =
A0.aggregates.per_lane["base"].wer_mean` and `WBb =
baseline.json.aggregates.per_lane["base"].wer_mean`, require
`|WB0 − WBb| ≤ 0.005`. A larger gap means the in-process engine is not
reproducing the subprocess baseline's text metrics; stop with exit 2 rather
than screening against a broken reference.

**Step 3 — stage B.** Apply §6.2's selection rule to A0…A7, write the
resulting `q02b-*.json` files, and run each exactly as in step 2. If the rule
yields no combinations (all four axis winners are the baseline value), skip to
step 6 with the plan denied.

**Step 4 — finalist.** Apply §6.3's rule to pick the finalist settings. Write
`q02f-cue.json`, `q02f-quiet.json` and (if §3.3 fork (a) landed)
`q02f-guard.json` with those `decode` values and the lanes in §4, and write
the two thresholds files with the margins computed by §6.1.

**Step 5 — formal verdicts.**

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant   docs/experiments/variants/Q02/q02f-cue.json \
  --baseline  docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q02/thresholds-cue.json

.venv/bin/python scripts/asr_experiment.py run \
  --variant   docs/experiments/variants/Q02/q02f-quiet.json \
  --baseline  docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q02/thresholds-quiet.json
```

Both are cross-engine comparisons (baseline: subprocess; run: in-process).
That is permitted: `HARNESS.md` §6.4 refuses a cross-engine comparison only
when `target.metric` starts with `load_ms`, `first_response_ms`, `decode_ms`
or `rtf`, and both targets here are text metrics. Guard 3 uses `rtf_p95`,
which is decode-only and comparable across engines by §3.1 — it does not make
these speed comparisons.

Exit `0` on both **and** the tail guard of §6.4 satisfied → **accept**. Exit
`1` on either, or the tail guard breached → **deny**. Exit `2` on either →
harness error, stop.

If §3.3 fork (a) landed, also run `q02f-guard.json` against
`thresholds-guard.json` and require exit `0`.

**Step 6 — record.** On accept, do §9's follow-through. On deny, append the
Outcome section §9 describes: the verdict lines verbatim, the run ids, and
`cp <run>/verdict.json docs/experiments/results/Q02-<run-id>.json` for each
formal run. Numbers only, in both cases.

## 6 Metrics & accept/deny

### 6.1 Targets, margins and the two thresholds files

**Cue lane.** Target `leading_miss_rate`, direction `lower`, margin
`max(0.05, 2 × baseline.noise.leading_miss_rate)`, `absolute`.

Justification of the 0.05 floor against `HARNESS.md`'s noise rule: decoding at
temperature 0 is deterministic on a fixed model and GPU (§8.3), so the
recorded repeat-noise is expected to be ≈0 and `2 × noise` would license an
implausibly small margin. The binding source of variability is the clip set,
not the decoder. With 300 cue clips and a baseline miss rate near `p = 0.2`,
the binomial standard error is `sqrt(0.2 × 0.8 / 300) = 0.023`; 0.05 is ≈2.2
standard errors, i.e. a change that would survive drawing a different 100-clip
subset. The `max()` keeps the harness rule binding whenever the measured noise
turns out to be larger than that.

**Quiet lane.** Target `empty`, direction `lower`, margin
`max(8, round(0.5 × E0), 2 × baseline.noise.empty)`, `absolute` (a count of
clips, not a rate — `empty` is a count in `HARNESS.md` §4.2).

Justification: `E0 ≥ 20` by step 1, so `0.5 × E0 ≥ 10` — the mechanism under
test (the decoder never sees the audio) is all-or-nothing per clip, and a
change that only shaves a fifth of the empties has not fixed it. The floor of
8 clips out of 200 is 4 percentage points ≈ 1.9 binomial standard errors at
`p = 0.1`, so it stays meaningful if `E0` lands just above the step-1 bar.

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.25,
  "forbid_empty_regressions": true,
  "target": {
    "metric": "leading_miss_rate",
    "direction": "lower",
    "margin": 0.05,
    "margin_kind": "absolute"
  },
  "lanes": ["cue"],
  "min_clips": 300
}
```

`thresholds-quiet.json` is the same file with `"metric": "empty"`,
`"margin": <computed>`, `"lanes": ["quiet"]`, `"min_clips": 200`. Both
`margin` values are written by the executing agent in step 4 from the formulas
above; the `0.05` shown is the floor, not a fixed value.

`thresholds-guard.json` (only under §3.3 fork (a)) is the same file with
`"target": null`, `"lanes": ["base", "tail"]`, `"min_clips": 400`.

Every run also inherits the guards of `HARNESS.md` §6.2 on its own lanes:
`wer_mean` +0.002, `rtf_p95` ×1.25, no empty regressions, no new errors.

### 6.2 Stage A → stage B (mechanical)

For a screening run `r`, from `result.json`'s `per_lane` block:

- `LM(r) = per_lane["cue"].leading_miss_rate`
- `EM(r) = per_lane["quiet"].empty`
- `WB(r) = per_lane["base"].wer_mean`
- `TJ(r) = per_lane["tail"].trailing_junk_rate`

`r` is **admissible** iff both

- `WB(r) ≤ WB(A0) + 0.002`, and
- `TJ(r) ≤ TJ(A0) + max(0.02, 2 × baseline.noise.trailing_junk_rate)`.

Composite score, lower is better (A0 scores exactly 2.0 by construction; if
the quiet arm was dropped in step 1, the second term is omitted and A0 scores
1.0):

```
S(r) = LM(r) / max(LM(A0), 1e-6) + EM(r) / max(EM(A0), 1)
```

Per axis, the **axis winner** is the admissible run on that axis — A0 counts as
the admissible run for the baseline value of every axis — with the lowest
`S`. Ties break first toward the baseline value, then toward the smaller
numeric parameter value.

Let `M` be the set of axes whose winner is not the baseline value. Stage B is
the full factorial over `M` where each axis takes either its baseline value or
its winning value, minus the all-baseline cell (that is A0) and minus the
single-axis cells (those are stage A). `|M| ≤ 4` bounds stage B at
`2⁴ − 1 − 4 = 11` runs; `|M| = 2` gives 1 run and `|M| = 3` gives 4.

If `M` is empty, no relaxation cleared its guards while improving either
symptom: the plan is **denied at stage A**. Record and stop.

### 6.3 Finalist selection (mechanical)

Let `A*` be the admissible stage-A run with the lowest `S` and `B*` the
admissible stage-B run with the lowest `S` (absent if stage B was empty or all
its runs were inadmissible). The finalist is `B*` if `S(B*) < S(A*)`, else
`A*`. If neither exists, the plan is denied. The finalist's `decode` object is
copied verbatim into the three `q02f-*.json` files.

### 6.4 The tail-lane guard (plan-level arithmetic — the fallback form)

`HARNESS.md` §6.1's `guards` array is the canonical mechanism and this guard is
one `max_regression` entry in it. The arithmetic below is the same inequality
written out, kept for the case where the foundation commit has not landed
`guards` yet. Computed unconditionally in step 5, from the finalist's stage-A or stage-B
screening run (which covered all four lanes) and `baseline.json`:

```
TJ(finalist) ≤ per_lane["tail"].trailing_junk_rate of the baseline
               + max(0.02, 2 × baseline.noise.trailing_junk_rate)
```

Breached → the plan is denied even if both formal runs exit 0. This guard
exists because it is the one thing the two formal runs structurally cannot
see: neither `q02f-cue` nor `q02f-quiet` includes the `tail` lane, and
`min_silence_duration_ms = 2000` is exactly the setting that would trade
first-word recall for trailing junk.

### 6.5 The verdict

**Accept** iff: `q02f-cue` exits 0, `q02f-quiet` exits 0 (or the quiet arm was
dropped in step 1 with that fact recorded), the §6.4 tail guard holds, and —
where §3.3 fork (a) landed — `q02f-guard` exits 0. Anything else is a deny.

## 7 Cost estimate

Per `HARNESS.md` §8.4: in-process ≈0.7 s per clip after one model load
(0.7–2.8 s). Lane sizes: `base` 100, `tail` 300, `cue` 300, `quiet` 200 = 900
clips per screening run.

| Phase | Runs | Clips each | Clip-decodes | Wall |
|---|---|---|---|---|
| Stage A | 8 | 900 | 7 200 | 8 × (900 × 0.7 s + 3 s) ≈ **84 min** |
| Stage B, typical (`\|M\| = 3`) | 4 | 900 | 3 600 | ≈ **42 min** |
| Stage B, worst (`\|M\| = 4`) | 11 | 900 | 9 900 | ≈ **115 min** |
| Finals | 3 | 300 / 200 / 400 | 900 | ≈ **11 min** |
| **Total, typical** | 15 | — | 11 700 | **≈ 2 h 17 min** |
| **Total, worst** | 22 | — | 18 000 | **≈ 3 h 30 min** |

Not counted above, because they belong to §3's prerequisites: generating the
`quiet` lane (pure numpy over 100 clips, < 2 min) and, under fork (a), the
+200 clips × 3 repeats × ≈5 s ≈ **50 min** added to the one-off baseline. Under
fork (b) instead, a re-baseline of the compared lanes is **≈5.5 h** at worst (the
full seven-lane run) and must be added to this plan's budget.

Disk: `quiet` lane ≈48 MB (200 clips of the same ≈12 min of audio, twice);
15–22 run directories at a few MB each ≈ 60 MB. Budget **150 MB** on top of
`HARNESS.md` §8.4's 1 GiB.

## 8 Risks, confounds, invariants

**`vad_min_speech_duration_ms = 0` admits non-speech.** With no minimum, a
cough, a keyboard click or the `record_start` cue itself can open and close a
chunk that is then handed to the decoder. On the `cue` lane this is not
hypothetical: the cue is a real transient at −12 dB immediately before the
speech. The failure mode is an inserted token at the head of the transcript,
which shows up as `substitution_rate` / `insertion_rate` in the run-level
`wer_mean` guard (+0.002) and, if it displaces the true first word, in
`leading_miss_rate` itself — the target metric would move the wrong way, so
the axis cannot win on a mechanism that breaks it.

**`vad_min_silence_duration_ms = 2000` re-arms Q07's mechanism.** Retained
gaps stop being capped at ≈2 × pad; up to 2 s of silence can sit inside one
chunk, which is both the audio `hallucination_silence_threshold = 2.0` was
meant to police and a known trigger for terminal loops. Caught by §6.4's tail
guard and by `trailing_junk_rate` in the stage-A admissibility test — an axis
value that raises tail junk is inadmissible before it can reach stage B.

**`vad_threshold = 0.3` may pass room tone.** The library derives
`neg_threshold = max(threshold − 0.15, 0.01) = 0.15` at that setting
(`vad.py:94-95`), so chunks both open earlier and close later. On the `tail`
lane this means appended room tone is more likely to be retained — the same
guard catches it. On `base` it means more audio per decode, which is the
direct driver of the `rtf_p95` ×1.25 guard: `rtf` divides `decode_ms` by the
*manifest* duration, so retaining more of the clip raises `rtf` mechanically,
not just statistically.

**Larger `vad_speech_pad_ms` is the mildest axis** — it only restores audio at
the first chunk's head (`vad.py:163`) and each chunk's tail (`vad.py:178-181`)
— but it also raises the ≈2 × pad gap-retention cap, so `pad600` and `sil2000`
together are the combination most likely to breach the tail guard. That is a
stage-B cell, and it is guarded, not excluded.

**The quiet lane is synthetic.** Attenuation plus a fixed −60 dBFS floor is a
model of a low-gain mic, not a recording of one. If it fails to reproduce
`vad_frames = 0` (step 1), the quiet arm reports that honestly and stops
rather than tuning the lane until the symptom appears. `X01` is the plan that
touches real microphone audio.

**Cross-engine baseline.** Every Q02 run is in-process; `baseline.json` is
subprocess. Legitimate for text metrics and `decode_ms` (`HARNESS.md` §3.1),
and step 2's A0 cross-check makes it measured rather than assumed.

**`HARNESS.md` §9 checklist, restated.**

- **No transcript text** anywhere but `clips.jsonl` under `build/`. No
  variant, thresholds, result, report, verdict or plan file in
  `docs/experiments/` carries a hypothesis, a reference or a normalized token
  string. This plan's Outcome section (§9) is numbers and run ids only.
- **No network in the ASR path.** Every run is in-process with
  `local_files_only=True` (`model.py:87`); Q02 downloads nothing. The corpus
  and the `quiet` lane are produced by `scripts/asr_corpus.py`, whose `fetch`
  is the only socket in the programme.
- **No platform imports.** The `quiet` generator uses `numpy`, `zlib`,
  `soundfile` and `stenographer.audio.speech_gate_stats` — all core.
- **Test policy** (hard rule 4). The `quiet` generator's arithmetic (gain from
  a synthetic array's frame RMS, the seeded noise floor, the manifest row) is
  pure and gets seen-to-fail tests in `tests/test_asr_corpus.py`. Nothing is
  mocked.
- **Fixed behaviour stays fixed.** `DecodeOptions()` defaults stay pinned; no
  new user-facing key; the config stays at exactly 23 keys in 4 sections
  (hard rule 9). Q02 can move a *literal*, never turn one into a setting.
- **Venv only**, SPDX header on the corpus generator's new code, ruff clean,
  line length 100.

## 9 Deliverables & follow-through

**On accept.**

1. `src/stenographer/transcribe/model.py:32-37` — replace the four values in
   `_VAD_PARAMETERS` with the finalist's. The dict's keys and shape do not
   change; only the numbers do.
2. `src/stenographer/transcribe/model.py`, `DecodeOptions`
   (`HARNESS.md` §3.2) — update `vad_threshold`,
   `vad_min_speech_duration_ms`, `vad_min_silence_duration_ms` and
   `vad_speech_pad_ms` to the same values, so the seam's defaults stay
   byte-for-byte the shipped literals.
3. `tests/transcribe/test_model.py` — update the literal dict in the
   `dataclasses.asdict(DecodeOptions())` pinning test. Editing both 2 and 3 in
   the same commit is the mechanism that makes a silent default drift
   impossible.
4. **A pure test is warranted, and it is a new one.** Nothing today asserts
   `_VAD_PARAMETERS` (grep: the name appears only at `model.py:32` and
   `model.py:117`), so the accepted numbers would be unguarded. Add to
   `tests/transcribe/test_model.py` a test asserting `_VAD_PARAMETERS ==
   {<the four accepted values>}` **and** that its four keys are exactly the
   `VadOptions` field names the wrapper intends to set. It is worth its line
   count for one reason only: these values were chosen by an experiment whose
   result is recorded in this file, and the test is what ties the literal back
   to it. Do not add a test that calls `get_speech_timestamps` — that is the
   library's behaviour, it needs real audio, and mocking it would prove
   nothing (hard rule 4).
5. `AGENTS.md` — hard rule 5 says "The anti-hallucination decode stack (VAD
   pre-filter, no-speech gate, silence trimming, short-audio token ceiling,
   output validation) is fixed behavior, not configuration." That sentence
   stays true and needs no edit. Add one sentence to the same rule instead:
   *"The VAD pre-filter's four parameters are the values Q02 accepted
   (`docs/experiments/Q02-vad-parameter-grid.md`); they are tighter/looser
   than the library defaults on purpose and change only through another
   accepted experiment."*
6. Re-baseline (`HARNESS.md` §7.3 case 1) after the change merges to `dev`,
   with the reason named in the commit message. Nothing under `src/` changes
   in that commit.
7. `AGENTS.md` acceptance gates — re-run on a real machine before dev → main:
   `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest` green, and real dictation
   end-to-end in `hold`, `toggle` and `hybrid`. The capture/logging gate
   applies directly here: *"a cold-start dictation retains its opening words"*
   is the acceptance-gate wording of this plan's primary target, so it must be
   exercised deliberately, not incidentally — and the log inspection must
   still show metrics with no transcript or audio content.
8. Set this file's Status to `accepted (<date>)` and append the Outcome
   section below with both verdict lines and both run ids.

**On deny.** Append to this file:

```markdown
## Outcome

Status: denied (<date>).

- q02f-cue  — run id `<run-id>`; verdict line verbatim.
- q02f-quiet — run id `<run-id>`; verdict line verbatim.
- Tail guard (§6.4): TJ(finalist) = <n> vs bound <n>.
- Stage A axis winners and their S scores; stage B winner and its S score.
```

and `cp <run>/verdict.json docs/experiments/results/Q02-<run-id>.json` for
each formal run. Set Status to `denied`. Numbers and run ids only — no text
fields, no clip hypotheses.

Either way, if step 1 dropped the quiet arm, that fact and `E0` at both
attenuation levels are recorded in the Outcome section, because it is a
finding about the corpus that the next plan needs.

## 10 Out of scope

- **`asr.vad_filter = false`** — turning the pre-filter off entirely. It is a
  user-facing config key, not a `DecodeOptions` field, and its trade
  (no onset loss at all, versus feeding raw silence to the decoder) is the
  hallucination question, not the recall question. **Q06** owns the
  empties-on-quiet-clips question from the other end (`_assemble`'s
  `no_speech_prob` gate).
- **`hallucination_silence_threshold`** — §2 explains why relaxing
  `min_silence_duration_ms` interacts with it. Q02 only guards the tail lane;
  **Q07** varies the threshold itself and must re-run after any accepted Q02
  change, on the re-baselined corpus.
- **`neg_threshold`** — the library derives it as `threshold − 0.15`
  (`vad.py:94-95`) and `DecodeOptions` exposes no field for it. Decoupling it
  from `threshold` would be a new seam field and a separate plan.
- **`max_speech_duration_s`** — unbounded today, and `audio.max_recording_seconds`
  already caps the daemon's input; no corpus clip exceeds 35 s.
- **Building or characterising the `cue` and `tail` lanes** — **Q10** and
  **Q09**. Q02 consumes them.
- **A `quiet` × `cue` cross lane** (attenuated audio *and* a leading cue),
  which is the closest synthetic analogue of the owner's actual failures. It
  is deliberately not built here: two orthogonal lanes give attributable
  results, a crossed lane gives one number that neither mechanism owns. If
  both arms accept, a follow-up plan should build it as a confirmation lane.
- **Real microphone audio** — **X01**, which is the one plan that needs a
  human.
- **Anything under `src/stenographer/audio.py`** — the RMS gate is not on
  trial. Both quiet utterances in the owner's log *passed* it; §3.1's lane
  asserts that its clips do too.
