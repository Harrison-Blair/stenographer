# Q01 — temperature fallback ladder

Status: planned (2026-08-29)

Baseline for every `file:line` citation: `dev` @ `a1b9807` (v0.11.6),
faster-whisper 1.2.1, CTranslate2 4.8.1, Python 3.14.7, in the repo venv.
Line numbers under `src/stenographer/transcribe/model.py` are the **pre-seam**
numbers; the `DecodeOptions` commit (`HARNESS.md` §3.2) shifts them, so §9
gives both forms of every edit.

## 1 Hypothesis

Replacing the scalar `temperature=0.0` with a temperature fallback ladder
(`(0.0, 0.2, 0.4)` or the library's full six-step ladder), which makes
`compression_ratio_threshold` live for the first time, reduces
`trailing_junk_rate` by ≥ 0.03 absolute on the pooled `base` + `tail` lanes
without moving `wer_mean` by more than +0.002 or `rtf_p95` by more than ×1.25.

## 2 Symptom & mechanism

**Symptom** — `README.md` symptom (2): "some utterances end in hallucinated
loops (`thank you`, `and more and more`)". `HARNESS.md` §5.5 scores exactly
this as `trailing_junk`: condition (a) two or more hypothesis words past the
last aligned word, condition (b) a terminal 1-, 2- or 3-gram repeated three
times that the reference does not itself repeat. The `tail` lane (trailing
room tone appended, `HARNESS.md` §2.4) is the lane built to reproduce it,
because the loops the owner reports occur when the decoder is asked to explain
silence at the end of a window.

**The code path.**

`src/stenographer/transcribe/model.py:114` passes `temperature=0.0` — a
scalar — into `WhisperModel.transcribe`. faster-whisper wraps it at
`.venv/lib/python3.14/site-packages/faster_whisper/transcribe.py:982-984`:

```python
temperatures=(
    temperature if isinstance(temperature, (list, tuple)) else [temperature]
),
```

so `options.temperatures` is the one-element list `[0.0]`. The fallback loop
is `for temperature in options.temperatures:` at `transcribe.py:1432`
(inside `generate_with_fallback`): it decodes, computes `avg_logprob` and
`compression_ratio`, sets `needs_fallback` when
`compression_ratio > options.compression_ratio_threshold`
(`transcribe.py:1480-1490`) or when
`avg_logprob < options.log_prob_threshold` (`transcribe.py:1493-1503`), and
`break`s when `not needs_fallback` (`transcribe.py:1515-1516`). With one
element the loop body runs exactly once and the `break`/`else` arms are
equivalent, so:

- **`compression_ratio_threshold` (library default 2.4) can never change the
  result today.** It is computed and logged at DEBUG and then discarded. A
  repetitive window — which is precisely what a terminal loop produces, and
  what compresses well, so its `len(text) / len(zlib.compress(text))` is
  high — is detected and then kept anyway.
- **`log_prob_threshold` (library default −1.0) is *not* inert.** Beyond the
  dead fallback trigger it still vetoes the no-speech window skip at
  `transcribe.py:1213-1224`: `should_skip = result.no_speech_prob >
  no_speech_threshold`, then `if log_prob_threshold is not None and
  avg_logprob > log_prob_threshold: should_skip = False`. That path is live
  under the current call and this plan does not touch it. Do not describe
  `log_prob_threshold` as inert anywhere in the outcome.

**Why the ladder should act on the symptom.** Restoring more than one entry in
`temperatures` turns both thresholds into what they were designed to be: a
window whose greedy/beam decode loops is re-decoded by sampling at a higher
temperature (`transcribe.py:1432-1440` switches to
`beam_size=1, num_hypotheses=options.best_of, sampling_temperature=temperature`),
and the first attempt whose compression ratio falls back under the threshold
is kept. If every attempt fails, `transcribe.py:1515-1529` selects the
best-`avg_logprob` result among those that were *below* the compression
threshold, falling back to all results — i.e. even the exhausted case prefers
a less repetitive candidate over the looping one.

**Two library settings that are confirmed inert here and must stay named as
such.** `prompt_reset_on_temperature` (0.5) is dead in this repo because
`condition_on_previous_text=False` (`model.py:121`) already takes the
prompt-reset branch unconditionally at `transcribe.py:1372-1382`. And
`no_repeat_ngram_size=3` (`model.py:115`) is passed into *every*
`model.generate` call inside the fallback loop (`transcribe.py:1451`), so the
ladder does not weaken it — a point that matters because "thank you" and
"and more" are 2-grams and are therefore not suppressed by it at any
temperature.

**Interaction with the repo's own output validation.** `_validate_output`
(`model.py:178-206`) raises `PathologicalOutputError` when word count exceeds
`max(12, ceil(8 × vad_seconds))`. A loop long enough to trip that ceiling is
today discarded wholesale (the daemon reports a failure). A working ladder
should *reduce* those; a sampling run that produces denser output could
instead *increase* them. That shows up as harness clip errors and is caught by
accept rule 5 (§6).

## 3 Prerequisites

Every item is blocking. The executing agent verifies each in §5 step 1 and
halts (exit 2, Status unchanged) if one is missing — it must not improvise a
substitute.

**Harness pieces** (`HARNESS.md` §1):

- `scripts/asr_corpus.py` — corpus fetched, converted, `tail` lane generated,
  `build/asr-corpus/manifest.json` present at schema 1.
- `scripts/asr_metrics.py` — `normalize`, `align`, `wer`,
  `leading_word_recall`, `trailing_junk`, `aggregate`, `decide`, with their
  seen-to-fail unit tests green.
- `scripts/asr_experiment.py` — subcommands `preflight`, `run`, `compare`;
  the in-process engine (`HARNESS.md` §3.1) including the §8.3 seeding
  (`ctranslate2.set_random_seed(20260829 + repeat)` before each clip;
  `ctranslate2.set_random_seed` is confirmed present in CTranslate2 4.8.1).
- **The runner must coerce a JSON array into a tuple.** A variant's
  `decode.temperature` is a JSON array; `DecodeOptions.temperature` is
  `tuple[float, ...]` and the dataclass is frozen and must stay hashable
  (`HARNESS.md` §3.2). `validate_variant` / the `DecodeOptions(**decode)`
  construction must convert `list → tuple` (and likewise for any future
  sequence field). If the runner passes the list through, this plan cannot
  run — that is a harness bug to fix first, not a plan variation.

**Injection fields** (`DecodeOptions`, `HARNESS.md` §3.2): `temperature`
(all four variants) and `compression_ratio_threshold` (variant 4 only). No
config keys are overridden; `config` is `{}` in every variant, so every run
uses the shipped `asr` defaults (`Systran/faster-whisper-medium.en`,
`compute_type = "int8"`, `beam_size = 1`, `silence_threshold = 0.6`,
`vad_filter` on — `src/stenographer/config.py:253-259`).

**Corpus lanes/tags**: `base` and `tail`, no tag filter (all three tail
durations 1 s / 3 s / 5 s participate). 100 + 300 = 400 clip ids.

**Baseline**: `docs/experiments/baseline.json` present, `schema == 1`,
`environment.device == "cuda"`, `environment.model ==
"Systran/faster-whisper-medium.en"`, and a `noise` block carrying
`trailing_junk_rate` (`HARNESS.md` §7.1).

**Plan dependency — Q09.** `Q09-trailing-silence-augmentation.md` owns the
`tail` lane: it builds it and characterises junk rate as a function of
appended room tone. Q01 is a *consumer* of that lane and is only meaningful
once Q09 has shown the lane reproduces the symptom. Concretely, §5 step 2
refuses to run unless the baseline's `per_lane["tail"].trailing_junk_rate` is
both (a) at least 0.04 and (b) at least twice
`per_lane["base"].trailing_junk_rate`. If Q09 has not yet established that,
Q01 is blocked, not denied.

## 4 Variant matrix

All four variants use the **in-process** engine: `decode` is non-empty, and
`HARNESS.md` §3 makes a non-empty `decode` with `engine: "subprocess"` a
harness error by design (the shipped CLI has no way to receive decode
overrides). `engine` is written explicitly rather than left at `auto` so the
file records the intent. Lanes and filters are identical across all four, so
the clip sets are identical and `decide`'s intersection rule (`HARNESS.md`
§6.2) never trims anything.

| # | Name | `decode` | Engine | Repeats | Path |
|---|---|---|---|---|---|
| 1 | `q01-control-t0` | `{"temperature": [0.0]}` | inprocess | 1 | `docs/experiments/variants/Q01/q01-control-t0.json` |
| 2 | `q01-ladder-3` | `{"temperature": [0.0, 0.2, 0.4]}` | inprocess | 3 | `docs/experiments/variants/Q01/q01-ladder-3.json` |
| 3 | `q01-ladder-6` | `{"temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]}` | inprocess | 3 | `docs/experiments/variants/Q01/q01-ladder-6.json` |
| 4 | `q01-ladder-6-cr20` | `{"temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], "compression_ratio_threshold": 2.0}` | inprocess | 3 | `docs/experiments/variants/Q01/q01-ladder-6-cr20.json` |

**Variant 1 is the control and is not a candidate.** It re-runs today's
shipped decode stack through the in-process engine. Its job is fidelity: at
`temperature=(0.0,)` decoding is deterministic (`HARNESS.md` §8.3), so its
text metrics must reproduce the subprocess baseline's, and its `rtf_p95` is
the only *same-engine* latency reference the ladders have (the baseline's
`rtf_p95` comes from the subprocess engine). `repeats: 1` because no
temperature above zero is in play (`HARNESS.md` §3). It will be *denied* by
`decide` — it improves nothing — and that denial is the expected result, not a
failure; §5 handles its exit code specially.

**Variants 2 and 3 are the hypothesis.** The three-step ladder is the
conservative form: it caps sampling at 0.4, where Whisper output is still
close to greedy, and it bounds the worst-case retry cost per window at three
passes. The six-step ladder is the library default and the form most users of
faster-whisper actually run; it is included because a two-step escalation may
simply not be enough to shake a confident loop loose.

**Variant 4 tightens `compression_ratio_threshold` to 2.0** on top of the full
ladder. **Justification for inclusion:** the threshold is the *trigger* for
the very mechanism this plan restores, and it is meaningless without a ladder
— which is why it can only be tested here and not as its own plan. 2.4 is
Whisper's original value, tuned for 30-second windows of continuous
narration; a dictation utterance is typically 3–15 s of speech inside a 30 s
window, so a two-word loop appended to a short utterance may not lift the
whole window's ratio past 2.4 even though it is exactly the failure the
threshold exists to catch. Testing 2.0 costs one more variant and answers
whether the ladder's *sensitivity*, not its *depth*, is the limiting factor.
It is deliberately paired only with the six-step ladder (not with the
three-step) to keep the matrix at four runs: a tighter trigger with a shallow
ladder is the combination most likely to exhaust the ladder and land in the
`transcribe.py:1515-1529` best-of-failures arm, which is the least
interesting outcome.

**Not included, and why:** `best_of` (library default 5) is not a
`DecodeOptions` field (`HARNESS.md` §3.2), so this plan cannot vary it; every
sampled retry therefore draws 5 hypotheses. See §8 and §10.

## 5 Procedure

Every command runs from the repo root with the repo venv. No step requires a
human. Exit codes are handled inline; unless a step says otherwise, exit 2
means stop and report.

**Step 0 — confirm the runner's flag spelling** (the harness CLI is
specified, not yet written; use whichever form its help shows, positional or
`--variant`, in every later step):

```sh
.venv/bin/python scripts/asr_experiment.py run --help
```

**Step 1 — prerequisites and preflight.**

```sh
.venv/bin/python -c "import json,pathlib; m=json.loads(pathlib.Path('build/asr-corpus/manifest.json').read_text()); assert m['schema']==1; lanes={c['lane'] for c in m['clips']}; assert {'base','tail'} <= lanes, lanes; print('clips', sum(1 for c in m['clips'] if c['lane'] in ('base','tail')))"
.venv/bin/python -c "import json,pathlib; b=json.loads(pathlib.Path('docs/experiments/baseline.json').read_text()); assert b['schema']==1; assert b['environment']['device']=='cuda'; assert b['environment']['model']=='Systran/faster-whisper-medium.en'; assert 'trailing_junk_rate' in b['noise']; print(json.dumps(b['noise'],indent=1))"
.venv/bin/python scripts/asr_experiment.py preflight
```

The clip count printed by the first command must be 400. `preflight` exit 2
stops the plan (missing model → `stenographer model download`; no CUDA →
this plan does not run on CPU, see §8).

**Step 2 — Q09 gate and margin resolution** (deterministic; the agent applies
the rule, it does not judge):

```sh
.venv/bin/python - <<'PY'
import json, pathlib
b = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
per = b["aggregates"]["per_lane"]
tail, base = per["tail"]["trailing_junk_rate"], per["base"]["trailing_junk_rate"]
noise = b["noise"]["trailing_junk_rate"]
pooled = b["aggregates"]["trailing_junk_rate"]
print(f"tail={tail:.4f} base={base:.4f} pooled={pooled:.4f} noise={noise:.4f}")
assert tail >= 0.04 and tail >= 2 * base, "Q09 gate failed: the tail lane does not reproduce the symptom"
margin = 0.03
if 2 * noise > margin:                       # HARNESS.md 7.1
    margin = round(-(-2 * noise // 0.005) * 0.005, 3)
assert margin <= 0.06, f"metric too noisy to test (needs margin {margin})"
assert pooled >= 2 * margin, f"pooled baseline {pooled:.4f} too low for an absolute margin of {margin}"
print("margin", margin)
PY
```

- Q09 gate assertion fails → **halt, Status stays `planned`**, report that Q01
  is blocked on Q09. Not a denial.
- `margin > 0.06` → **halt**, Status `abandoned`, reason "target metric noisier
  than any defensible margin".
- The pooled assertion fails (baseline pooled `trailing_junk_rate` below
  `2 × margin`, i.e. an absolute improvement of `margin` is arithmetically
  near-unreachable) → **edit `thresholds.json` once**, setting
  `"margin_kind": "relative"` and `"margin": 0.5` (halve the rate), record the
  edit verbatim in the Outcome section, and continue. This is the plan's one
  permitted amendment.
- Otherwise write the printed `margin` into `thresholds.json` in step 3 (0.03
  unless the noise rule raised it).

**Step 3 — write the variant and threshold files** (they are checked in; this
step creates them if absent, byte-identical to §6 and §4):

```sh
mkdir -p docs/experiments/variants/Q01
cat > docs/experiments/variants/Q01/thresholds.json <<'JSON'
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.25,
  "forbid_empty_regressions": true,
  "target": {
    "metric": "trailing_junk_rate",
    "direction": "lower",
    "margin": 0.03,
    "margin_kind": "absolute"
  },
  "lanes": ["base", "tail"],
  "min_clips": 400
}
JSON
cat > docs/experiments/variants/Q01/q01-control-t0.json <<'JSON'
{
  "schema": 1,
  "name": "q01-control-t0",
  "plan": "Q01",
  "lanes": ["base", "tail"],
  "tags_any": [],
  "tags_all": [],
  "engine": "inprocess",
  "repeats": 1,
  "config": {},
  "decode": {"temperature": [0.0]}
}
JSON
cat > docs/experiments/variants/Q01/q01-ladder-3.json <<'JSON'
{
  "schema": 1,
  "name": "q01-ladder-3",
  "plan": "Q01",
  "lanes": ["base", "tail"],
  "tags_any": [],
  "tags_all": [],
  "engine": "inprocess",
  "repeats": 3,
  "config": {},
  "decode": {"temperature": [0.0, 0.2, 0.4]}
}
JSON
cat > docs/experiments/variants/Q01/q01-ladder-6.json <<'JSON'
{
  "schema": 1,
  "name": "q01-ladder-6",
  "plan": "Q01",
  "lanes": ["base", "tail"],
  "tags_any": [],
  "tags_all": [],
  "engine": "inprocess",
  "repeats": 3,
  "config": {},
  "decode": {"temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]}
}
JSON
cat > docs/experiments/variants/Q01/q01-ladder-6-cr20.json <<'JSON'
{
  "schema": 1,
  "name": "q01-ladder-6-cr20",
  "plan": "Q01",
  "lanes": ["base", "tail"],
  "tags_any": [],
  "tags_all": [],
  "engine": "inprocess",
  "repeats": 3,
  "config": {},
  "decode": {
    "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    "compression_ratio_threshold": 2.0
  }
}
JSON
```

If step 2 raised the margin or switched it to relative, apply that edit to
`thresholds.json` now.

**Step 4 — the control run.**

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q01/q01-control-t0.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q01/thresholds.json
```

Exit 2 → stop. Exit 0 or 1 → **expected either way** (the control cannot
improve the target, so 1 is the normal outcome; a 0 would mean the baseline
and the control disagree by more than the margin, which is itself a fidelity
failure). Then check fidelity explicitly against the baseline's own noise:

```sh
.venv/bin/python - <<'PY'
import json, pathlib
runs = sorted(pathlib.Path("build/asr-experiments").glob("*-q01-control-t0/result.json"))
r = json.loads(runs[-1].read_text()); b = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
print("control run", runs[-1].parent.name)
for k in ("wer_mean", "trailing_junk_rate", "leading_miss_rate"):
    d = abs(r["aggregates"][k] - b["aggregates"][k])
    tol = max(3 * b["noise"][k], 0.002)
    print(f"{k}: run {r['aggregates'][k]:.4f} baseline {b['aggregates'][k]:.4f} delta {d:.4f} tol {tol:.4f}")
    assert d <= tol, f"in-process engine does not reproduce the baseline on {k}"
print("control rtf_p95", r["aggregates"]["rtf_p95"])
PY
```

An assertion failure here means the two engines do not agree at temperature 0
and **no Q01 verdict is trustworthy** — halt, Status stays `planned`, report a
harness fidelity defect. Otherwise record the printed `control rtf_p95` as
`RTF_CTRL`; §6's extra guard uses it.

**Step 5 — the three ladder runs, in matrix order.** Run each; do not stop on
a deny.

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q01/q01-ladder-3.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q01/thresholds.json; echo "exit $?"
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q01/q01-ladder-6.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q01/thresholds.json; echo "exit $?"
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q01/q01-ladder-6-cr20.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q01/thresholds.json; echo "exit $?"
```

Per variant: `0` = accepted candidate, `1` = denied (record the verdict line
and move on), `2` = harness error (record it, move on to the next variant;
only a `2` on *every* variant stops the plan).

**Step 6 — apply the selection rule (§6), then the same-engine latency
guard**, over the accepted variants only:

```sh
.venv/bin/python - <<'PY'
import json, pathlib, sys
root = pathlib.Path("build/asr-experiments")
# The control's rtf_p95 is read from step 4's own run directory, never typed in:
# no step of this plan may wait on a person (docs/experiments/README.md).
ctrl = sorted(root.glob("*-q01-control-t0/result.json"))
if not ctrl:
    print("FAIL no q01-control-t0 run; step 4 did not complete"); sys.exit(2)
RTF_CTRL = float(json.loads(ctrl[-1].read_text())["aggregates"]["rtf_p95"])
print("control rtf_p95", round(RTF_CTRL, 4), "from", ctrl[-1].parent.name)
for name in ("q01-ladder-3", "q01-ladder-6", "q01-ladder-6-cr20"):
    runs = sorted(root.glob(f"*-{name}"))
    if not runs: print(name, "no run"); continue
    v = json.loads((runs[-1] / "verdict.json").read_text())
    a = json.loads((runs[-1] / "result.json").read_text())["aggregates"]
    ok = v["accepted"] and a["rtf_p95"] <= 1.25 * RTF_CTRL
    print(name, runs[-1].name, "accepted", v["accepted"],
          "rtf_p95", round(a["rtf_p95"], 4), "vs ctrl", round(1.25 * RTF_CTRL, 4),
          "-> candidate", ok)
PY
```

A variant that `decide` accepted but whose `rtf_p95` exceeds `1.25 × RTF_CTRL`
is **demoted to denied** by this plan (§6) — the baseline's `rtf_p95` is a
subprocess number and the control's is the honest same-engine reference.

**Step 7 — record the outcome.** On a winner: §9's accept branch. With no
winner: §9's deny branch — append an "Outcome" section holding every verdict
line and run id, copy each `verdict.json` to
`docs/experiments/results/Q01-<run-id>.json`, set Status to `denied`. Numbers
only in both branches; never copy anything out of `clips.jsonl`.

## 6 Metrics & accept/deny

**Target metric**: `trailing_junk_rate` (`HARNESS.md` §4.2 — the fraction of
scored clips whose `trailing_junk` flag is true, §5.5). **Direction**: lower.
**Margin**: 0.03. **Margin kind**: absolute. **Lanes**: `base` and `tail`,
pooled — `decide` computes the target over the union of the thresholds' lanes,
so this is one pooled rate over 400 clip ids, and §6.3's per-lane rows in
`report.md` are read for diagnosis, not for the verdict.

**Why pooled rather than `tail` alone.** The `wer_mean` and empty-regression
guards are only as good as the clips they see, and the clean `base` lane is
exactly where a sampling ladder is most likely to *cost* accuracy — a
`tail`-only verdict would let a variant trade base-lane WER for tail-lane
junk without ever being measured on the trade. The cost of pooling is
dilution: `base` contributes 100 of the 400 clips (25%), and its baseline junk
rate is expected to be near zero (Q09's premise), so an improvement of `d` on
`tail` shows up as `0.75 × d` pooled. A 0.03 pooled margin therefore demands
roughly a 0.04 improvement on the lane that carries the symptom, which is the
right thing to demand. This also matches the worked example in `HARNESS.md`
§6.1, which uses `"lanes": ["base", "tail"]` with this same metric.

**Why 0.03 satisfies the noise rule.** `HARNESS.md` §7.1 requires the margin
to be at least twice the baseline's recorded noise for the metric, and
`validate_variant` enforces it. The baseline is run at `temperature=(0.0,)`
with the subprocess engine, where decoding is deterministic for a fixed model,
compute type and GPU (§8.3), so the recorded `trailing_junk_rate` noise should
be at or near 0.000 — 0.03 clears `2 × noise` with room to spare. 0.03 pooled
over 400 clips is 12 clips changing verdict, which is well outside what a
deterministic re-run can produce, and small enough that a real effect is
detectable. §5 step 2 raises the margin mechanically if the measured noise
turns out larger, and abandons the plan above 0.06.

**`min_clips: 400`** — the number of distinct clip ids in the two lanes. With
`repeats: 3` the runner scores 1200 records over those 400 ids; 400 is the
correct floor under either counting convention, which is why it is written
rather than 1200.

**`thresholds.json`, verbatim** (`docs/experiments/variants/Q01/thresholds.json`):

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.25,
  "forbid_empty_regressions": true,
  "target": {
    "metric": "trailing_junk_rate",
    "direction": "lower",
    "margin": 0.03,
    "margin_kind": "absolute"
  },
  "lanes": ["base", "tail"],
  "min_clips": 400
}
```

**The five accept rules** (`HARNESS.md` §6.2, restated so the outcome can cite
them): (1) `run.wer_mean ≤ baseline.wer_mean + 0.002`; (2)
`trailing_junk_rate` improves by ≥ 0.03 absolute; (3) `run.rtf_p95 ≤ 1.25 ×
baseline.rtf_p95`; (4) no clip non-empty in the baseline is empty in the run;
(5) no clip errored in the run that succeeded in the baseline. Because every
ladder variant carries a temperature above zero, `decide` additionally uses
the **mean over the three repeats** and denies when the target metric's
**spread across repeats exceeds the margin** (`HARNESS.md` §8.3) — a variant
whose junk rate wobbles by more than 0.03 between seeds has not demonstrated
anything, however good its mean.

**One extra plan-level guard** (§5 step 6): an accepted variant whose
`rtf_p95` exceeds `1.25 × RTF_CTRL`, the control's same-engine `rtf_p95`, is
demoted to denied. Rule 3 compares an in-process run against a subprocess
baseline; `HARNESS.md` §3.1 licenses that for `decode_ms`, but the control
gives a strictly better comparator and it costs nothing to apply both.

**Multi-variant decision rule**: **first accepted in matrix order wins**
(`q01-ladder-3` before `q01-ladder-6` before `q01-ladder-6-cr20`; the control
is never a candidate), **unless a later accepted variant improves the target
by ≥ 0.02 more than the first accepted one**, in which case that later variant
wins. Rationale: a shorter ladder is strictly cheaper in worst-case latency
and involves strictly less sampling nondeterminism in shipped behaviour, so it
is preferred at equal effect; 0.02 is the margin a longer or more aggressive
ladder must clear to justify those costs. Ties beyond that are impossible
under a strict inequality; if two variants land within 0.02 of each other,
matrix order decides.

## 7 Cost estimate

**One pass** over the variant's clip set is 400 clips (100 `base` + 300
`tail`) on the in-process engine: `HARNESS.md` §8.4 puts `base + tail` (400)
at **≈5 min**, i.e. ≈0.75 s/clip, plus one cold `Model.__init__` per variant
(≈2–3 s, amortised to nothing).

**Fallback retries cost time only on windows that fail a threshold.** A clip
is ≤ 35 s of speech plus ≤ 5 s of tail, so 1–2 Whisper windows. A retry
re-runs `model.generate` for that one window at `beam_size=1,
num_hypotheses=best_of=5` (`transcribe.py:1432-1440`) — roughly 5× the cost of
the shipped `beam_size=1` greedy pass, because `best_of` defaults to 5 and
this plan cannot change it (§4). If a fraction `f` of windows retry an average
of `r` times, decode time scales by `1 + 5·f·r`. Clips that pass at
temperature 0 — expected to be the large majority — cost exactly what the
control costs.

| Variant | Passes | Nominal (f = 0.15, r = 1 → ×1.75) | Worst case (f = 0.5, r = 2 → ×6) |
|---|---|---|---|
| `q01-control-t0` | 1 × 5 min | 5 min (no retries possible) | 5 min |
| `q01-ladder-3` | 3 × 5 min = 15 min | ≈26 min | 90 min (capped: ladder depth 3 → r ≤ 2) |
| `q01-ladder-6` | 3 × 5 min = 15 min | ≈26 min | 90 min+ (r ≤ 5) |
| `q01-ladder-6-cr20` | 3 × 5 min = 15 min | ≈30 min (tighter trigger → higher f) | 90 min+ |

**Total: ≈1 h 30 min nominal; reserve a 5 h window** for the pathological
case where most windows exhaust the ladder. Nothing about the plan needs
supervision during that time; if the wall clock is a constraint, run the
control and `q01-ladder-3` first — the decision rule prefers them anyway.

**Disk**: the corpus already exists (`base` ≈24 MB, `tail` ≈100 MB;
`HARNESS.md` §8.4) and is not regenerated. Four run directories, each holding
a `clips.jsonl` of 400 (control) to 1200 (ladders) records at ≈600 B →
0.25–0.75 MB each, plus `result.json` / `report.md` / `verdict.json` /
`variant.json` → **under 30 MB total**, well inside preflight's 1 GiB check.
The in-process engine installs no logging, so no `stenographer.log` is written
by any of these runs.

## 8 Risks, confounds, invariants

**Risk — sampling introduces *different* hallucinations.** At T = 0.6–1.0
Whisper produces fluent, confident, wrong text rather than a loop. The
`wer_mean` guard (+0.002) catches it in aggregate; `trailing_junk` condition
(a) (two or more unaligned tail words) catches the specific case where the
substitute junk is still at the end. What neither catches well is a *mid*-
utterance substitution on a clip that had no junk to begin with — read the
`substitution_rate` row of `report.md` before accepting, and treat a rise in
`substitution_rate` alongside a flat `wer_mean` as a reason to prefer the
shorter ladder even if both are accepted.

**Confound — `log_prob_threshold` becomes a second live trigger.** Restoring
the ladder makes `avg_logprob < −1.0` a fallback trigger
(`transcribe.py:1493-1503`) at the same time as `compression_ratio > 2.4`.
This plan cannot attribute an improvement to one or the other, and does not
try to. `q01-ladder-6-cr20` is the only compression-specific lever tested: if
it beats `q01-ladder-6` materially, the compression path is doing the work; if
they are indistinguishable, the attribution stays open. Splitting them (e.g. a
variant with `compression_ratio_threshold: null`) is deliberately out of scope
(§10).

**Confound — `no_repeat_ngram_size=3` interaction.** The n-gram block is
applied inside every fallback attempt (`transcribe.py:1451`), so the ladder
neither weakens nor strengthens it. But it is already suppressing exact 3-gram
repeats, which means the loops that survive to be scored are 1- and 2-gram
loops ("thank you", "and more") — precisely the ones `trailing_junk` condition
(b) is written to catch at `n ∈ (1, 2, 3)`. Any joint tuning of
`no_repeat_ngram_size` or `repetition_penalty` belongs to Q05; if Q05 is
merged first, Q01 must be re-run against the re-baselined defaults
(`HARNESS.md` §7.3 clause 1), because the two changes act on the same symptom
and their effects are not additive.

**Confound — `best_of = 5` rides along.** Accepting a ladder ships sampling
with 5 hypotheses per retry, a behaviour change this plan measures but cannot
isolate. It is named explicitly in §9's `AGENTS.md` edit so it is not an
undocumented consequence.

**Risk — `PathologicalOutputError` regressions.** `_validate_output`
(`model.py:178-206`) caps word count at `max(12, ceil(8 × vad_seconds))`. A
denser sampled output raises `PathologicalOutputError` out of
`Model.transcribe`; the in-process engine records it as a clip `error`
(exception class name only, `HARNESS.md` §4.1) and accept rule 5 denies the
variant. That is the correct outcome. Conversely, a *drop* in these errors is
a real win that the target metric does not see — count them per variant from
`clips.jsonl`'s `error` field and report the count in the Outcome, as numbers.

**Deny conditions specific to this plan**, beyond the five standard rules:
(i) target-metric spread across the three repeats exceeds the margin
(`HARNESS.md` §8.3); (ii) `rtf_p95 > 1.25 × RTF_CTRL` (§6's extra guard);
(iii) the control fails its fidelity check in §5 step 4 — which denies nothing
but invalidates every Q01 verdict and halts the plan.

**Not runnable on CPU.** `preflight` exits 2 without CUDA unless `--allow-cpu`
is passed, and a CPU run is never comparable to the CUDA baseline
(`HARNESS.md` §6.4). Do not pass `--allow-cpu` for this plan.

**`HARNESS.md` §9 invariant checklist, restated:**

- **No transcript text** anywhere but `build/asr-experiments/<run-id>/clips.jsonl`.
  Not in `result.json`, `report.md`, `verdict.json`, stdout, this file's
  Outcome section, `docs/experiments/results/`, or any file under
  `docs/experiments/variants/Q01/`. The variant files here carry numbers and
  option names only — no `initial_prompt`, no `hotwords`.
- **No network in the ASR path.** `Model` keeps `local_files_only=True`
  (`model.py:87`); no variant touches it; the in-process engine downloads
  nothing; `asr_corpus.py fetch` is not run by this plan.
- **No platform imports.** The harness touches core modules only; this plan
  adds no new import.
- **Test policy** (`AGENTS.md` hard rule 4): no mock of `WhisperModel`,
  `subprocess`, or `soundfile` is written for this plan. See §9 for what test,
  if any, the accept branch adds.
- **Fixed behaviour stays fixed.** `DecodeOptions()` defaults remain pinned by
  a test; nothing under `src/` constructs a non-default instance; user config
  still has exactly 23 keys in 4 sections. On accept, the *default itself*
  moves and the pin moves with it — the stack stays fixed, at a different
  fixed point.
- **Venv only**, SPDX header on every new `.py` (this plan adds none), ruff
  clean at line length 100.

## 9 Deliverables & follow-through

**On accept** — let `T` be the winning variant's `temperature` tuple and `C`
its `compression_ratio_threshold` (2.4 unless `q01-ladder-6-cr20` won).

1. **The literal change.** Pre-seam, the line is
   `src/stenographer/transcribe/model.py:114`:

   ```python
               temperature=0.0,
   ```

   The `DecodeOptions` seam (`HARNESS.md` §3.2) is a prerequisite of this
   plan, so by the time Q01 runs that call site already reads
   `temperature=self._options.temperature,` and the shipped value lives in the
   dataclass default. **The change is therefore to the default**, in the
   `DecodeOptions` block of the same file:

   ```python
       temperature: tuple[float, ...] = (0.0,)
   ```
   →
   ```python
       temperature: tuple[float, ...] = (0.0, 0.2, 0.4)
   ```

   and, only if `q01-ladder-6-cr20` won, in the same block:

   ```python
       compression_ratio_threshold: float | None = 2.4
   ```
   →
   ```python
       compression_ratio_threshold: float | None = 2.0
   ```

   Also delete the seam's stale comment on that field — `# library default;
   inert while len(temperature) == 1` — which stops being true the moment the
   ladder ships. Replace it with `# live once the ladder has more than one
   step`. Do **not** touch `log_prob_threshold`: it was never inert (§2).

2. **The pinning test.** `tests/transcribe/test_model.py` gains (per
   `HARNESS.md` §3.2) a test asserting `dataclasses.asdict(DecodeOptions())`
   equals a literal dict. Update that literal in the same commit — the two
   edits together are the record that a default moved deliberately.

3. **The `AGENTS.md` sentence.** Hard rule 5 currently reads:

   > The anti-hallucination decode stack (VAD pre-filter, no-speech gate,
   > silence trimming, short-audio token ceiling, output validation) is fixed
   > behavior, not configuration.

   Replace it with (adjusting the tuple and threshold to the winner):

   > The anti-hallucination decode stack (VAD pre-filter, no-speech gate,
   > silence trimming, short-audio token ceiling, output validation, and the
   > temperature fallback ladder `(0.0, 0.2, 0.4)` — whose retries are what
   > make `compression_ratio_threshold` live, and which sample `best_of = 5`
   > hypotheses per retry) is fixed behavior, not configuration.

   The point of the wording: the stack is *still* fixed, it is fixed at a
   different point. No config key is added; the count stays at 23 keys in 4
   sections (hard rule 9).

4. **Existing tests. None assert the decode kwargs.** Verified:
   `grep -rn temperature src/ tests/` matches exactly one line,
   `model.py:114`, and `tests/transcribe/test_model.py` covers only
   `resolve_cpu_threads`, `_token_budget`, `_validate_output` and `_assemble`
   — nothing reaches the `WhisperModel.transcribe` call. So this change breaks
   no test and, absent the pin, would be invisible to the suite.

5. **What pure test to add: only the pin.** Under `AGENTS.md` hard rule 4 and
   `HARNESS.md` §9, a test that mocks `WhisperModel` to assert
   `temperature=(0.0, 0.2, 0.4)` was passed is exactly the forbidden shape — a
   green mock proving a call *would* have happened. The `DecodeOptions()`
   pinning test is the correct and sufficient pure test, because the value is
   now data on a frozen dataclass rather than a call-site literal, and the
   integration smoke suite plus the acceptance gates are the real gate. Add
   nothing else. If a future reader wants a behavioural test, the honest one is
   an `integration`-marked decode of a fixture that loops at T = 0 — out of
   scope here and not worth a 1.5 GB model dependency in the unit suite.

6. **Re-baseline.** `HARNESS.md` §7.3 clause 1: the shipped defaults moved, so
   `docs/experiments/baseline.json` no longer describes them. Re-run
   `baseline` (≈1180 clips × 3 repeats, subprocess, ≈5.5 h) after the change lands
   on `dev`, in a commit that touches only `docs/experiments/baseline.json` and
   says which clause triggered it. Every other tail-lane plan (Q05, Q07, Q11)
   must be run or re-run against the new baseline.

7. **`AGENTS.md` acceptance gates to re-run on the real machine before
   dev → main** — this change is in the ASR path, so:
   - `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest` green;
   - real dictation end-to-end in `hold`, `toggle` and `hybrid` modes;
   - the capture/logging gate: a cold-start dictation retains its opening
     words, and an inspection of `stenographer.log` plus the journal shows
     metrics but no transcript or audio content;
   - additionally, because retries cost latency on exactly the windows that
     fail a threshold, confirm by inspection of `pipeline: utterance` lines
     that first-utterance `decode_ms` on a normal dictation has not visibly
     regressed. This is the user-facing risk the corpus `rtf_p95` guard only
     approximates.

8. **Status** → `accepted`, plus an Outcome section holding the winning
   verdict line, the run id, every variant's numbers, and the
   `PathologicalOutputError` counts per §8. Numbers only.

**On deny** (no variant accepted, or every accepted one demoted by the
latency guard): append an "Outcome" section to this file with each verdict
line and run id verbatim, copy each `verdict.json` to
`docs/experiments/results/Q01-<run-id>.json`, set Status to `denied`, and
state which of the five accept rules (plus the two plan-level deny conditions)
each variant failed. Change nothing under `src/`. A deny is a real result: it
says the scalar `temperature=0.0` is the right shipped value and that
`compression_ratio_threshold`'s inertness is harmless, which retires an open
question and points the symptom at Q05, Q07 or Q11.

**On blocked** (Q09 gate or control fidelity): Status stays `planned`, no
`results/` file is written, and the report names the blocking prerequisite.

## 10 Out of scope

- **`repetition_penalty` and `no_repeat_ngram_size`** — Q05. They act on the
  same symptom through a different mechanism and must be measured separately
  before either is combined with a ladder.
- **`hallucination_silence_threshold`** (2.0 today, `model.py:27`) — Q07,
  which runs on the same `tail` lane.
- **A pure post-decode terminal-n-gram filter** — Q11. It would remove the
  junk after the fact rather than stop the decoder producing it; Q01 tests the
  decoder-side fix so Q11 can be judged against it.
- **`_assemble`'s no-speech gate and the library's log-prob-vetoed skip**
  (`transcribe.py:1213-1224`) — Q06.
- **`beam_size`** — Q03. Note that `beam_size` is *ignored* at every T > 0
  rung (`transcribe.py:1432-1440` replaces it with `beam_size=1,
  num_hypotheses=best_of`), so if both Q01 and Q03 accept, the interaction
  must be re-measured rather than assumed.
- **`best_of`** — untested by anyone. It is not a `DecodeOptions` field
  (`HARNESS.md` §3.2) and cannot be varied by this harness today. If the
  ladder is accepted, adding `best_of: int = 5` to `DecodeOptions` and giving
  it a plan is a reasonable follow-up; until then the library default ships
  with the ladder and §9's `AGENTS.md` sentence says so.
- **Isolating `compression_ratio_threshold` from `log_prob_threshold`** as
  fallback triggers — see §8. Would need a variant with one of them set to
  `null`, which changes behaviour the shipped stack has always had, and is not
  worth a run until the ladder itself has proven useful.
- **The `cue` lane and leading-word loss** — Q10 and Q02. Q01 runs on `base` +
  `tail` only; a ladder has no plausible mechanism for first-word recovery.
- **Any user-facing configuration knob for temperature.** `AGENTS.md` hard
  rule 9 fixes the config at 23 keys and hard rule 5 keeps the decode stack out
  of configuration. Whatever this plan accepts becomes a new fixed default, not
  a setting.
