# Q03 — beam size

Status: planned (2026-08-29)

## 1 Hypothesis

Raising `asr.beam_size` from the shipped `1` (greedy) to `3` or `5` reduces
`wer_mean` by ≥ 5 % relative on the `base` + `tail` lanes without raising
`trailing_junk_rate` above the baseline's, without introducing an empty or
errored clip that the baseline decoded, and at an `rtf_p95` no worse than
×2.0 of the baseline's (this plan's own ceiling — see §6.3 — rather than
`HARNESS.md`'s default ×1.25) and a `decode_ms_p95` no worse than 2500 ms
absolute.

## 2 Symptom & mechanism

**Symptom.** `docs/experiments/README.md` records the owner's report (3):
"the hallucination rate is high in general", and (2) "some utterances end in
hallucinated loops". Both are decoder-search failures rather than acoustic
ones: the model's *best* hypothesis is fine, but the search never looks at it.

**Code path.**

- `src/stenographer/transcribe/model.py:113` passes `beam_size=cfg.beam_size`
  into `WhisperModel.transcribe`. The shipped value is `1`
  (`src/stenographer/config.py:310`, template line
  `src/stenographer/config.py:255`), validated to `1..10` at
  `src/stenographer/config.py:198`. The library's own default is `5`
  (`.venv/lib/python3.14/site-packages/faster_whisper/transcribe.py:753`), so
  stenographer ships a deliberate, undocumented departure from it.
- `src/stenographer/transcribe/model.py:114` passes the scalar
  `temperature=0.0`. In `generate_with_fallback`, a temperature of `0`
  selects the branch at
  `.venv/lib/python3.14/site-packages/faster_whisper/transcribe.py:1441-1444`,
  which forwards `beam_size` and `patience` to
  `ctranslate2` and forwards **neither** `num_hypotheses` nor `best_of`; the
  `best_of` knob is reachable only from the `temperature > 0` branch at
  `transcribe.py:1433-1439`. This is the load-bearing interaction with Q01: at
  today's `temperature=0.0`, `best_of` is inert and `beam_size` is the *only*
  search-width knob in play.
- `length_penalty` (default `1`, `transcribe.py:756`) and `patience` (default
  `1`, `transcribe.py:755`) are never passed by `model.py:110-125`, so both sit
  at the library default; `patience` is inert at `beam_size=1` because
  CTranslate2 derives its search allowance from `patience × beam_size`.

**Why the change should act on the symptom.** With `beam_size=1` the decoder
commits to the argmax token at every step and cannot recover from a bad early
commitment; a hallucinated continuation that starts with one plausible token
is then followed to the end of the segment. Beam search keeps `k` partial
hypotheses scored by cumulative log-probability, so a degenerate continuation
whose per-token probability collapses is overtaken by a competing hypothesis
before the segment closes. `no_repeat_ngram_size=3` (`model.py:115`) already
forbids a *literal* trigram repeat inside one hypothesis; beam search is the
complementary mechanism, since it can discard the whole branch rather than
merely forbid its next token.

The counter-mechanism is real and is why this plan guards `trailing_junk_rate`
rather than assuming it improves: beam search on sequence models is known to
favour short, high-probability, degenerate continuations ("beam search
degeneration"), and the `tail` lane — where several seconds of room tone give
the decoder nothing to condition on — is exactly where that would show.

## 3 Prerequisites

- **Harness pieces.** `scripts/asr_corpus.py`, `scripts/asr_metrics.py`,
  `scripts/asr_experiment.py` (`HARNESS.md` §1) with the subcommands
  `preflight` and `run`, and their pure test modules green in the unit suite.
  `compare` is exercised through `run --baseline`.
- **Injection fields.** **None.** `beam_size` is an `asr` config key, so every
  variant in this plan is a pure **config-lane** variant
  (`HARNESS.md` §3: `"config": {"asr": {"beam_size": N}}`, `"decode": {}`).
  Q03 therefore does **not** depend on the `DecodeOptions` seam
  (`HARNESS.md` §3.2) existing, and can be run as soon as the runner and the
  baseline exist. This is also why `engine` resolves to `subprocess` — see §4.
- **Corpus lanes/tags.** `base` (produced by `asr_corpus.py`, `HARNESS.md`
  §2.3) and `tail` (produced by `asr_corpus.py`'s `tail` lane, characterised by
  **Q09**; `HARNESS.md` §2.4). No tag filters. The `cue` lane is deliberately
  excluded (§10).
- **Baseline.** `docs/experiments/baseline.json` present, written from a clean
  tree with the subprocess engine over all seven baseline lanes, carrying a `noise`
  block with entries for `wer_mean` and `trailing_junk_rate`
  (`HARNESS.md` §7.1), and describing the *shipped* defaults — i.e.
  `asr.beam_size = 1`.
- **Ordering.** Run Q03 **after Q04** (`compute_type`) has been settled and,
  if Q04 changed the default, after the re-baseline
  (`docs/experiments/README.md`, execution order steps 3 and 5). Run it
  **after Q01** if Q01 is accepted, because a temperature ladder re-decodes
  failed segments in the `temperature > 0` branch where `beam_size` is
  replaced by `beam_size=1 + num_hypotheses=best_of`
  (`transcribe.py:1433-1439`): an accepted Q01 changes what fraction of
  segments `beam_size` even governs, so Q03's number would no longer describe
  the shipped stack. Either ordering is fine as long as only one accepted
  change is merged at a time with a re-baseline between (`HARNESS.md` §7.3).

## 4 Variant matrix

All variants are config-lane (`decode` empty), so `engine: "auto"` resolves to
`subprocess` (`HARNESS.md` §3). That is also the engine the baseline was
recorded with, which keeps the `rtf_p95` guard an intra-engine comparison and
keeps `compare` clear of the §6.4 engine-mismatch refusal.

`repeats: 1` for every variant. Decoding is deterministic at `temperature=0.0`
(`HARNESS.md` §8.3) and no variant here introduces a temperature above zero,
so the text metrics are exactly reproducible. Repeats are *not* needed for
latency variance either: `rtf_p95` and `decode_ms_p95` are already order
statistics over 400 per-clip decodes within a single run, and the baseline's
`noise` block is the programme's measurement of run-to-run speed spread.

| # | Variant | Path | `config` | Lanes | Clips | Engine | Repeats | Run when |
|---|---|---|---|---|---|---|---|---|
| 0 | `q03-beam-1-control` | `docs/experiments/variants/Q03/q03-beam-1-control.json` | `{"asr": {"beam_size": 1}}` | `base` | 100 | subprocess | 1 | always, first |
| 1 | `q03-beam-3` | `docs/experiments/variants/Q03/q03-beam-3.json` | `{"asr": {"beam_size": 3}}` | `base`, `tail` | 400 | subprocess | 1 | always |
| 2 | `q03-beam-5` | `docs/experiments/variants/Q03/q03-beam-5.json` | `{"asr": {"beam_size": 5}}` | `base`, `tail` | 400 | subprocess | 1 | always |
| 3 | `q03-beam-8` | `docs/experiments/variants/Q03/q03-beam-8.json` | `{"asr": {"beam_size": 8}}` | `base`, `tail` | 400 | subprocess | 1 | **conditionally** — see below |

**Variant 0 is a control, not a candidate.** It re-runs the shipped default
against the current machine and corpus. Its target metric cannot improve
against a baseline of itself, so it is run **without** `--baseline` and judged
by the numeric drift check in §5 step 3. It exists because every Q03 verdict
rests on a baseline recorded at some earlier date, and `HARNESS.md` §7.3 item 4
makes an unnoticed CUDA/driver/library change a silent invalidator. 100 clips
on one lane is the cheapest honest drift check available (≈8 min).

**Variant 3 (`beam_size = 8`) is conditional.**
`docs/experiments/README.md`'s index lists this plan as "1 / 3 / 5 / 8"; the
condition reconciles that with the cost. Run variant 3 **iff** variant 2
(`beam 5`) was accepted **and** the curve is still descending, i.e.

```
(base_wer - wer_5) - (base_wer - wer_3) >= 0.5 * (base_wer - wer_3)
```

where `base_wer` is the baseline `wer_mean` recomputed over the same lanes.
In words: beam 5's *additional* gain over beam 3 is at least half of beam 3's
gain over greedy. If beam 5 was denied, or the gain has flattened, beam 8
cannot plausibly clear a bar beam 5 could not, and the run is skipped and
recorded as skipped. This rule is arithmetic on `result.json` numbers — no
human judgement.

**`patience` is deliberately excluded** from the matrix, contrary to the
optional suggestion:

1. It is not in `DecodeOptions` (`HARNESS.md` §3.2) and is not passed at
   `model.py:110-125`. Varying it would mean adding a field to a frozen
   dataclass under `src/`, updating its pinning test, and editing `AGENTS.md`
   — a change to the shared harness spec, made inside a plan that otherwise
   needs no code change at all.
2. Adding it would force `engine: "inprocess"` (a non-empty `decode` with
   `engine: "subprocess"` is a harness error, `HARNESS.md` §3), which would
   split this plan across two engines and put its latency guard on the wrong
   side of the baseline's engine.
3. It is inert at `beam_size=1`, so it can never be evaluated against the
   shipped default; it is a second-order refinement of the very knob under
   test, and its whole cost lands on the metric this plan is trying to
   protect.

If beam 5 or 8 is accepted and the WER curve is still descending at 8, a
follow-up plan (Q03b) covering `patience` and `length_penalty` together, on
the in-process engine against a re-baseline, is the right home for it (§10).

### Variant JSON, verbatim

`docs/experiments/variants/Q03/q03-beam-1-control.json`:

```json
{
  "schema": 1,
  "name": "q03-beam-1-control",
  "plan": "Q03",
  "lanes": ["base"],
  "tags_any": [],
  "tags_all": [],
  "engine": "auto",
  "repeats": 1,
  "config": {"asr": {"beam_size": 1}},
  "decode": {}
}
```

`docs/experiments/variants/Q03/q03-beam-3.json` (and, with `name` and
`beam_size` changed to `q03-beam-5`/`5` and `q03-beam-8`/`8`, the other two):

```json
{
  "schema": 1,
  "name": "q03-beam-3",
  "plan": "Q03",
  "lanes": ["base", "tail"],
  "tags_any": [],
  "tags_all": [],
  "engine": "auto",
  "repeats": 1,
  "config": {"asr": {"beam_size": 3}},
  "decode": {}
}
```

## 5 Procedure

Every command runs from the repository root in the repo venv; `<REPO>` below is
that repository root. Nothing here needs a human.

**Step 0 — write the variant and threshold files.** Create the four variant
JSON files of §4 and the `thresholds.json` of §6.4 under
`docs/experiments/variants/Q03/`. They are numbers and option names only.

**Step 1 — preflight.**

```sh
.venv/bin/python scripts/asr_experiment.py preflight
```

Exit `0` → continue. Exit `2` → stop; the message names the cause (venv, model
not cached, corpus digest mismatch, no CUDA device, insufficient disk;
`HARNESS.md` §8.2). Do not work around it: a missing model means running
`stenographer model download` (the only permitted model download,
`AGENTS.md` hard rule 5); a corpus mismatch means regenerating the corpus and
re-baselining (`HARNESS.md` §7.3 item 2).

**Step 2 — margin precondition.** The declared margin must be at least twice
the baseline's recorded noise for the target metric (`HARNESS.md` §7.1), and
`validate_variant` enforces it. Check it first so the failure is legible, and
*raise* the bar rather than run under an unenforceable one.

Everything this and the later snippets check that is an ordinary aggregate
belongs in `thresholds.json`'s `guards` array, which is the canonical mechanism
(`HARNESS.md` §6.1). The snippets are the **fallback**: they keep this plan
runnable if the foundation commit has not landed `guards` yet, and they compute
things — a margin precondition, a cross-variant curve — that no single guard row
can express.

```sh
.venv/bin/python - <<'PY'
import json, math, pathlib
b = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
p = pathlib.Path("docs/experiments/variants/Q03/thresholds.json")
t = json.loads(p.read_text())
base = b["aggregates"]["wer_mean"]
noise = b["noise"]["wer_mean"]
declared_abs = t["target"]["margin"] * abs(base)   # margin_kind == "relative"
floor_abs = 2.0 * noise
print(f"baseline wer_mean={base:.5f} noise={noise:.5f} "
      f"declared_abs={declared_abs:.5f} floor_abs={floor_abs:.5f}")
if declared_abs < floor_abs:
    new_rel = math.ceil((floor_abs / abs(base)) * 100) / 100
    t["target"]["margin"] = new_rel
    p.write_text(json.dumps(t, indent=2) + "\n")
    print(f"RAISED margin to {new_rel} relative (2x noise floor)")
else:
    print("margin OK")
PY
```

The rule only ever tightens the bar; it never loosens it. Record the printed
line in the Outcome section (§9). If `base` is `0.0` (an impossible corpus),
stop with a harness error rather than dividing by zero.

**Step 3 — control run and drift check.**

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q03/q03-beam-1-control.json
```

(If the implemented CLI takes the variant positionally rather than as
`--variant`, read `scripts/asr_experiment.py run --help` and use the form it
documents; the variant file is unchanged either way.)

Exit `0` → the run completed; note its `<run-id>`. Exit `2` → harness error,
stop. Then:

```sh
.venv/bin/python - <<'PY'
import json, pathlib, sys
runs = sorted(pathlib.Path("build/asr-experiments").glob("*-q03-beam-1-control"))
r = json.loads((runs[-1] / "result.json").read_text())
b = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
run_base = r["aggregates"]["per_lane"]["base"]
base_base = b["aggregates"]["per_lane"]["base"]
noise = b["noise"]["wer_mean"]
d_wer = abs(run_base["wer_mean"] - base_base["wer_mean"])
d_junk = abs(run_base["trailing_junk_rate"] - base_base["trailing_junk_rate"])
tol_wer = max(2.0 * noise, 0.002)
tol_junk = max(2.0 * b["noise"]["trailing_junk_rate"], 0.01)
print(f"drift wer_mean={d_wer:.5f} (tol {tol_wer:.5f}) "
      f"trailing_junk_rate={d_junk:.5f} (tol {tol_junk:.5f}) "
      f"errors={run_base.get('errors')}")
sys.exit(0 if (d_wer <= tol_wer and d_junk <= tol_junk) else 2)
PY
```

Exit `0` → the environment still reproduces the baseline; continue. Exit `2` →
**stop the plan**. The environment has drifted from the baseline
(`HARNESS.md` §7.3 item 4); re-baseline first, in its own commit, then restart
Q03 from step 1. Do not proceed with a comparison against a stale baseline.

**Step 4 — beam 3.**

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q03/q03-beam-3.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q03/thresholds.json
```

Exit `0` = the harness accepted (primary gate). Exit `1` = denied. Exit `2` =
harness error → stop and report; do not re-run hoping for a different number.
Record the `<run-id>` and the verdict line either way, then run the secondary
gate of step 6 against this run.

**Step 5 — beam 5.** Identical, with `q03-beam-5.json`. Run it regardless of
beam 3's verdict: the two are independent points on the same curve and the
matrix decision (§6.5) needs both.

**Step 6 — secondary gate (mandatory for every candidate variant).** The
harness's `decide` evaluates exactly one target metric plus its fixed guards
(`HARNESS.md` §6.2); this plan's "`trailing_junk_rate` not worse" and its
absolute latency ceiling are not expressible in `thresholds.json`, so they are
a separate numeric step. A variant is **accepted by this plan** only if the
harness exited `0` **and** this check exits `0`:

```sh
.venv/bin/python - <<'PY'
import json, pathlib, sys
NAME = "q03-beam-5"      # set to the variant under test
LANES = ("base", "tail")
runs = sorted(pathlib.Path("build/asr-experiments").glob(f"*-{NAME}"))
r = json.loads((runs[-1] / "result.json").read_text())
b = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
noise = b["noise"]["trailing_junk_rate"]
ok = True
for lane in LANES:
    run_l, base_l = r["aggregates"]["per_lane"][lane], b["aggregates"]["per_lane"][lane]
    if run_l["clips"] != base_l["clips"]:
        print(f"FAIL {lane}: clip counts differ {run_l['clips']} vs {base_l['clips']}")
        ok = False
        continue
    delta = run_l["trailing_junk_rate"] - base_l["trailing_junk_rate"]
    verdict = "ok" if delta <= noise else "FAIL"
    print(f"{verdict} {lane}: trailing_junk_rate {base_l['trailing_junk_rate']:.4f} "
          f"-> {run_l['trailing_junk_rate']:.4f} (delta {delta:+.4f}, tol +{noise:.4f})")
    ok = ok and delta <= noise
p95 = r["aggregates"]["decode_ms_p95"]
print(f"{'ok' if p95 <= 2500 else 'FAIL'} decode_ms_p95 {p95:.1f} ms (ceiling 2500)")
sys.exit(0 if (ok and p95 <= 2500) else 1)
PY
```

`trailing_junk_rate` is allowed to move up by at most the baseline's own
recorded noise for that metric — "not worse", read at the precision the
measurement supports.

**Step 7 — conditional beam 8.** Evaluate the §4 condition arithmetically:

```sh
.venv/bin/python - <<'PY'
import json, pathlib, sys
b = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
def wer(name):
    runs = sorted(pathlib.Path("build/asr-experiments").glob(f"*-{name}"))
    return json.loads((runs[-1] / "result.json").read_text())["aggregates"]["wer_mean"]
base = b["aggregates"]["wer_mean"]
g3, g5 = base - wer("q03-beam-3"), base - wer("q03-beam-5")
print(f"gain3={g3:+.5f} gain5={g5:+.5f} extra={g5 - g3:+.5f} need>={0.5 * g3:+.5f}")
sys.exit(0 if (g3 > 0 and (g5 - g3) >= 0.5 * g3) else 1)
PY
```

Exit `0` **and** beam 5 accepted by both gates → run `q03-beam-8.json` exactly
as in step 5, then its step-6 secondary gate. Otherwise skip it and record
"beam 8 skipped, curve flattened" with the printed numbers.

**Step 8 — decide and write the outcome.** Apply §6.5, then §9.

## 6 Metrics & accept/deny

### 6.1 Target metric

`wer_mean` (`HARNESS.md` §4.2), direction `lower`, **margin `0.05`,
`margin_kind` `relative`** — the run must beat the baseline's `wer_mean` by at
least 5 % of the baseline's own value.

Why relative and why 5 %: the expected effect of beam search over greedy on a
clean read-speech corpus is a few percent relative, and it scales with the
error rate rather than sitting at a fixed absolute size. A fixed absolute
margin would be either unmeetable (if the baseline `wer_mean` turns out near
0.03) or trivially meetable (if it turns out near 0.15). The `HARNESS.md` §7.1
noise rule then applies on top, in absolute terms, and step 2 of §5 raises the
margin whenever `0.05 × baseline_wer_mean` falls under twice the recorded
noise — so the declared bar is `max(5 % relative, 2 × noise)` by construction,
and can only tighten.

`wer_mean` rather than `wer_corpus` because `HARNESS.md` §4.2 fixes the accept
rule on `wer_mean` and because it weights short clips more, which is what
dictation is.

### 6.2 Secondary gate (this plan's own, §5 step 6)

- `trailing_junk_rate` per lane must not exceed the baseline's by more than
  the baseline's recorded noise for that metric, on **both** `base` and
  `tail`. This is the beam-search-degeneration guard, and the `tail` lane is
  where it bites; the lane comes from **Q09**.
- `decode_ms_p95 ≤ 2500 ms` absolute, so no accept can make a long utterance
  feel slow regardless of how favourable the ratio looks against a fast
  baseline.

### 6.3 The `rtf_p95` ceiling — this plan declares ×2.0, not ×1.25

`HARNESS.md` §6.1's example threshold is ×1.25. That is the wrong ceiling for
a beam-width experiment and this plan sets its own:

- Beam 5 does roughly 2–3× the decoder compute of greedy. CTranslate2 batches
  the beam within one generation call, so the measured wall-clock cost is
  sublinear in `beam_size`, but ×1.25 sits *below* even the optimistic end of
  the plausible range. A ×1.25 ceiling would deny beam 5 on cost before its
  quality was ever weighed — the guard would decide the experiment.
- The absolute numbers make the ratio affordable. Decode on the reference
  machine is ≈1.1 s per 25 s of audio (`HARNESS.md` §8.4), i.e. `rtf ≈ 0.044`,
  with the §4.2 illustrative `rtf_p95 ≈ 0.14`. At ×2.0 that is `rtf_p95 ≈
  0.28` — still nearly four times faster than real time, and on a 25 s
  utterance the added wait is ≈1.1 s at worst.
- ×2.0 is still a real guard: it denies a variant whose decode cost grows
  faster than its search width, which is the pathological case (VRAM pressure,
  fallback to a slower kernel) rather than the expected one.
- The absolute `decode_ms_p95 ≤ 2500 ms` gate of §6.2 backs the ratio up, so a
  favourable ratio measured against an unusually slow baseline still cannot
  license a slow accept.

This is a per-plan value in this plan's `thresholds.json`, not an edit to
`HARNESS.md` §6.1; the shared spec's example stands for plans whose change is
not expected to cost compute.

### 6.4 `thresholds.json`, verbatim

`docs/experiments/variants/Q03/thresholds.json`:

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.0,
  "rtf_p95_max_ratio": 2.0,
  "forbid_empty_regressions": true,
  "target": {
    "metric": "wer_mean",
    "direction": "lower",
    "margin": 0.05,
    "margin_kind": "relative"
  },
  "lanes": ["base", "tail"],
  "min_clips": 400
}
```

`wer_mean_max_delta` is `0.0` because the target metric *is* `wer_mean`: guard
1 of `HARNESS.md` §6.2 then degenerates to "no regression", which the target
already implies, and leaving it at a positive value would only be confusing.
`min_clips` is `400` = 100 `base` + 300 `tail` at `repeats: 1`. The control
variant uses no thresholds file (it is run without `--baseline`).

### 6.5 Deciding the matrix

**Best accepted by target metric, with a latency tie-break.** Among the
variants accepted by *both* gates (harness exit `0` **and** §5 step 6 exit
`0`), the winner is the one with the lowest `wer_mean`; if two accepted
variants' `wer_mean` differ by less than the baseline's recorded noise for
`wer_mean`, the smaller `beam_size` wins, because at that point the WER
difference is unmeasurable and the latency difference is not.

If no variant is accepted by both gates, the plan's outcome is **denied** and
the shipped `beam_size = 1` stands.

## 7 Cost estimate

Per-clip subprocess cost from `HARNESS.md` §8.4: ≈1 s interpreter and imports
+ 0.7–2.8 s cold model load + decode ≈ **4–5 s**. Decode is the small term:
the `base` lane averages ≈7.2 s of audio per clip (100 clips ≈ 12 min) and the
`tail` lane averages ≈10.2 s (base + 1/3/5 s of room tone), so at the
baseline's ≈1.1 s per 25 s the decode component is ≈0.32 s and ≈0.45 s
respectively. Doubling *that* adds well under 0.5 s per clip, so wall time is
load-dominated and nearly beam-independent — while `rtf`, which is computed
from `decode_ms` alone (`HARNESS.md` §5.6), still measures the beam cost
cleanly.

| Step | Clips | Repeats | s/clip | Wall |
|---|---|---|---|---|
| Control `q03-beam-1-control` (`base`) | 100 | 1 | 5.0 | 500 s ≈ **8 min** |
| `q03-beam-3` (`base`+`tail`) | 400 | 1 | 5.3 | 2120 s ≈ **36 min** |
| `q03-beam-5` (`base`+`tail`) | 400 | 1 | 5.5 | 2200 s ≈ **37 min** |
| **Mandatory subtotal** | 900 | — | — | **≈ 1 h 21 min** |
| `q03-beam-8` (conditional) | 400 | 1 | 6.0 | 2400 s ≈ **40 min** |
| **Worst case (beam 8 runs)** | 1300 | — | — | **≈ 2 h 1 min** |

Preflight adds one cold model load (`HARNESS.md` §8.2 step 5) per invocation,
≈3 s each. The four `python -` gate scripts are milliseconds.

Disk: the corpus is a prerequisite, not a cost of this plan (`base` ≈24 MB +
`tail` ≈100 MB, already present). Each run directory is a few MB —
`clips.jsonl` for 400 clips plus `result.json` — so ≈20 MB for four runs, far
inside the 1 GiB budget of `HARNESS.md` §8.4. No re-download.

## 8 Risks, confounds, invariants

### What else the change could move

- **Beam-search degeneration → more looping, not less.** The plausible
  downside, and the one the harness's single target metric would miss.
  Caught by the §6.2 secondary gate on both lanes, with the `tail` lane the
  sensitive one.
- **Word-density runaway → clip errors.** `_validate_output`
  (`src/stenographer/transcribe/model.py:200-204`) raises
  `PathologicalOutputError` above `max(12, 8 × vad_seconds)` words, and
  `_token_budget` (`model.py:173-175`) caps generated tokens. Beam search does
  not raise the cap, but a beam-selected hypothesis could be denser than the
  greedy one. Caught by guard 5 of `HARNESS.md` §6.2 — no clip may error in
  the run that succeeded in the baseline — and visible as `errors` in
  `result.json`.
- **VRAM.** The reference machine is an 8 GiB RTX 3080 Laptop
  (`HARNESS.md` §8.1); `medium.en` at the resolved `int8_float16` leaves
  headroom, and a beam of 5–8 multiplies only decoder activations. An OOM
  would surface as errored clips (guard 5) or a harness error (exit 2), never
  as a silent quality change.
- **Latency the guards do catch.** `rtf_p95 ≤ 2.0 ×` baseline plus
  `decode_ms_p95 ≤ 2500 ms` absolute (§6.2, §6.3).
- **Latency the guards do not catch.** Cold-start first-response time is
  unaffected by beam width (the ≈4 s wait is import + load, per `S01`), so
  this plan does not gate on `first_response_ms_*`.

### Confounds

- **CPU-only hosts.** Every number here comes from one CUDA GPU;
  `HARNESS.md` §6.4 makes `compare` refuse across `environment.device`, so
  this plan can never produce a CPU measurement. On CPU, `medium.en` decode is
  roughly an order of magnitude slower and the beam cost lands on an already
  marginal budget, so an accept here licenses a **GPU** recommendation only.
  This is the whole reason §9 forks the deliverable: the shipped default is
  what CPU users get, and moving it on GPU evidence alone is a product
  decision, not an experimental one. Note that a user can already set
  `beam_size` in their own `config.toml` today (`config.py:198`, range 1–10),
  so the recommendation is actionable with no code change at all.
- **`compute_type` not yet settled.** All Q03 variants inherit the baseline's
  `compute_type`, so the comparison is internally valid; but if **Q04**
  subsequently changes the default, the re-baseline
  (`HARNESS.md` §7.3 item 1) invalidates Q03's accepted number and Q03 must be
  re-run. Hence the §3 ordering: Q04 first.
- **`temperature` fallback (Q01).** At `temperature=0.0` the decoder always
  takes the `beam_size`/`patience` branch
  (`faster_whisper/transcribe.py:1441-1444`); a ladder would route failed
  segments to the `beam_size=1`/`best_of` branch
  (`transcribe.py:1433-1439`), where beam width does nothing. An accepted Q01
  changes what Q03 is measuring; re-run Q03 after it merges.
- **Corpus register.** LibriSpeech `test-clean` is read speech, not dictation.
  Absolute WERs are not comparable to published figures (`HARNESS.md` §5.1),
  and a beam gain on read speech may be smaller or larger on spontaneous
  dictation. The `user` lane (`HARNESS.md` §2.4) is the eventual answer; this
  plan does not wait for it.
- **`hotwords` / `initial_prompt`.** Both empty at the default
  (`config.py:256-257`) and unchanged by every variant, so neither
  interacts here. `asr.hotwords` on a distil model is a Q12 concern.

### Invariants (`HARNESS.md` §9, restated)

- **No transcript text** outside `build/asr-experiments/<run-id>/clips.jsonl`.
  Not in `result.json`, `report.md`, `verdict.json`, stdout, this file, any
  file under `docs/experiments/variants/Q03/`, or `docs/experiments/results/`.
  The four gate scripts in §5 print numbers only, by construction.
- **No network in the ASR path.** Every variant is config-lane, so
  `Model` keeps `local_files_only=True` (`model.py:87`) and the subprocess env
  sets `HF_HUB_OFFLINE=1` (`HARNESS.md` §3.1). This plan opens no socket at
  all: it neither fetches the corpus nor downloads a model.
- **No platform imports.** This plan adds no code; the harness's own isolation
  (the harness scripts and rigs named in `HARNESS.md` §9, all covered by
  `tests/platform/test_core_isolation.py`'s grep) is unchanged by it.
- **Test policy** (`AGENTS.md` hard rule 4). This plan adds no test and mocks
  nothing; it runs the real CLI over real audio with the real model.
- **Fixed behaviour stays fixed.** No `DecodeOptions` field is touched, no
  non-default `DecodeOptions` is constructed, and user config keeps exactly
  23 keys — `beam_size` is one of them already (`AGENTS.md` hard rule 9).
- **Venv only**; no new `.py` file, so no new SPDX header; ruff unaffected.

## 9 Deliverables & follow-through

### On accept

The winning variant's `beam_size` is `N` (§6.5). Two mutually exclusive
deliverables; **the orchestrator picks one** — see the recommendation below.

**(a) Change the shipped default.** One commit, `feat:` or `fix:`:

| File | Line | Change |
|---|---|---|
| `src/stenographer/config.py` | `310` (`beam_size=1,`) | `beam_size=N,` — the `Config.defaults()` dataclass value |
| `src/stenographer/config.py` | `255` (`beam_size = 1`) | `beam_size = N` — the annotated template, which *is* the user-facing documentation for this key |
| `tests/test_config.py` | `33` | `assert d.asr.beam_size == N` |
| `tests/cli/test_setup.py` | `269` | `"  beam_size = N",` |

Verified: no other file asserts the literal default. `README.md` documents no
per-key default (its config section, `README.md:92-120`, shows only hotkey
mode and feedback examples), so **no README edit is required** — but adding a
one-line `[stenographer.asr] beam_size = N` note there with the measured cost
is worthwhile either way. `src/stenographer/daemon.py:794` logs the effective
value in the banner and needs no change. `src/stenographer/cli/setup.py:452`
prompts within 1–10 and needs no change. The `1..10` validation range at
`src/stenographer/config.py:198` is unchanged.

`AGENTS.md`: add one sentence to hard rule 5, beside the existing
`asr.cpu_threads` and `asr.hotwords` sentences, recording that
`asr.beam_size` defaults to `N` because Q03 measured it on a CUDA GPU, naming
the measured `rtf_p95` ratio, and noting that CPU hosts pay the full ratio on
a far slower decode. `AGENTS.md` hard rule 9 is untouched: the key count and
the four sections are unchanged.

Then: **re-baseline** (`HARNESS.md` §7.3 item 1 — the shipped defaults moved),
in a commit that touches `docs/experiments/baseline.json` and nothing under
`src/`, with the reason in the message.

Then, before `dev` → `main`, the `AGENTS.md` acceptance gates that this change
touches, on the real machine:
`STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest` green; real dictation end-to-end
in `hold`, `toggle`, and `hybrid` modes (a decode-latency change is felt at
the end of every utterance); and the logging gate — `stenographer.log` opens
with one `banner:` block naming every effective key (it must now read
`beam_size=N`) and each dictation leaves exactly one `pipeline: utterance`
line, with
`tests/test_daemon_smoke.py::test_dictation_log_reports_metrics_without_the_transcript`
passing against that real log.

**(b) Recommend the user-config change only.** No `src/` change, no test
change, no `AGENTS.md` change, no re-baseline, no acceptance-gate run. The
deliverable is documentation: a short subsection in `README.md`'s *Configure*
section giving

```toml
[stenographer.asr]
beam_size = 5
```

with the measured GPU numbers (`wer_mean` improvement, `rtf_p95` ratio,
`decode_ms_p95`) and the explicit caveat that the figures are from one CUDA
GPU and that CPU hosts pay the same ratio on a much slower decode. Plus the
Outcome section below.

**Recommendation for the fork.** Take **(a)** only if the winning variant's
`rtf_p95` ratio is ≤ 1.5 *and* its `decode_ms_p95` ≤ 1500 ms — at that cost
the change is safe to hand even to an unmeasured CPU host. Otherwise take
**(b)**: the WER gain is real but the latency cost is one only a GPU user has
been shown to afford, and the shipped default is the one setting that reaches
every user without their consent. Both branches are decidable from
`result.json` alone.

**Either way**, append an "Outcome" section to this file: the verdict line for
every variant run, each `<run-id>`, the step-2 margin line, the step-3 drift
line, the step-6 secondary-gate lines, and the step-7 beam-8 decision.
Numbers only. Set Status to `accepted (<date>)`.

### On deny

Append the same "Outcome" section with every verdict line and run id, copy
each `verdict.json` to
`docs/experiments/results/Q03-<run-id>.json`, and set Status to
`denied (<date>)`. Numbers only. The shipped `beam_size = 1` stands and is now
an evidenced default rather than an inherited one — record that sentence in
the Outcome, since it is the durable result.

## 10 Out of scope

- **`patience`, `length_penalty`, `best_of`.** Excluded with reasons in §4.
  A follow-up **Q03b** on the in-process engine, after a `DecodeOptions`
  extension, is the right home — and only if the WER curve is still descending
  at beam 8. `best_of` is inert at `temperature=0.0`
  (`faster_whisper/transcribe.py:1433-1444`) and belongs to **Q01**.
- **The temperature fallback ladder** — **Q01**.
- **`repetition_penalty` and `no_repeat_ngram_size`** as the anti-loop knobs —
  **Q05**. Q03 measures whether beam width alone moves `trailing_junk_rate`;
  it does not tune the repetition machinery.
- **`compute_type`** — **Q04**, which must settle first (§3).
- **A different model** (`small.en`, `distil-medium.en`, `large-v3-turbo`) —
  **Q12**. `compare` refuses a cross-model comparison outside Q12
  (`HARNESS.md` §6.4).
- **Batched inference for long utterances** — **S02**.
- **Cold-start first-response latency** — **S01**. Beam width does not move
  import or load time, so this plan gates only on decode.
- **The `cue` lane and first-word loss** — **Q10** builds it, **Q02** tunes the
  VAD against it. Beam width acts on search, not on what the VAD delivered to
  the decoder, so paying 55 min per variant for a third lane would buy no
  hypothesis this plan can state.
- **`hallucination_silence_threshold`** — **Q07**.
- **A post-decode terminal-n-gram filter** — **Q11**.
- **Spontaneous-dictation audio.** The `user` lane
  (`HARNESS.md` §2.4) and **X01** are where the owner's own microphone enters
  the programme.
