# Q06 — the `_assemble` no-speech re-gate on/off

Status: planned (2026-08-29)

## 1 Hypothesis

Removing the daemon's own per-segment `no_speech_prob` filter in `_assemble`
(`assemble_no_speech_gate: false`) does not increase the `empty` clip count on
any lane, does not raise `trailing_junk_rate` on the `tail` lane by more than
twice the baseline's recorded noise for that metric, does not turn a
silence-only clip into text, and does not move `wer_mean` by more than `+0.002`
or `rtf_p95` by more than `×1.25` — while removing the only code path that can
discard an entire confident utterance the library deliberately kept.

This is a **no-harm** experiment, not an improvement experiment: the filter is
a guard, and the case for deleting it is that it is provably stricter than the
library gate that already ran upstream. §6 pre-registers the decision rule for
both the "the corpus exercises the gate" and the "the corpus never exercises
the gate" outcomes, so the executing agent never has to judge.

## 2 Symptom & mechanism

**Symptom** (`docs/experiments/README.md`, owner report 1 and 3): utterances
where "nothing comes out at all" although the overlay showed input, plus a
general sense that quiet speech is dropped. The secondary concern is that
loosening a filter raises hallucination/junk (owner reports 2 and 3).

**The code path.** `src/stenographer/transcribe/model.py:215`:

```python
kept = [seg for seg in segments if seg.no_speech_prob < silence_threshold]
```

`silence_threshold` is `asr.silence_threshold` (default `0.6`,
`src/stenographer/config.py:259`), and the *same* value is already handed to
faster-whisper as `no_speech_threshold` at `model.py:118`. So the gate runs
twice, on two different rules:

| | library, `faster_whisper/transcribe.py:1215-1234` | repo, `model.py:215` |
|---|---|---|
| drops when | `no_speech_prob > 0.6` **and** `avg_logprob <= -1.0` | `no_speech_prob >= 0.6` |
| boundary at exactly `0.6` | kept | dropped |
| log-prob veto | yes (`log_prob_threshold`, library default `-1.0`, not overridden) | none — `avg_logprob` is discarded at `model.py:126-138` |

The repo gate is therefore **strictly stricter** on both axes. Combined with
the library's own behaviour this has a sharp consequence:

- A pass the library skips yields *no* segments at all — `transcribe.py:1234`
  advances `seek` and `continue`s before the `yield` at `:1349-1370`. So every
  segment that reaches `_assemble` came from a pass the library **kept**.
- A kept pass either had `no_speech_prob <= 0.6` (which `_assemble` also
  keeps, except at exactly `0.6`) or had `no_speech_prob > 0.6` rescued by
  `avg_logprob > -1.0` — a pass the decoder was *confident* about.
- `_assemble` drops precisely that second class. **The only thing the repo
  gate can ever discard is a pass the library deliberately rescued because the
  decoder was confident.**

And it discards it wholesale: `no_speech_prob` is a per-decode-pass value
copied onto every segment of that pass (`transcribe.py:1364`,
`no_speech_prob=result.no_speech_prob`). Within one 30 s window every segment
carries the identical value, so the filter is all-or-nothing per pass; a
dictation utterance shorter than 30 s is one pass, so it is all-or-nothing for
the whole utterance. It cannot strip a single trailing junk segment — the job
its name implies. It either passes everything or produces `text == ""`, which
the daemon treats as success-shaped (no paste, no error cue, `AGENTS.md` hard
rule 5) — exactly "nothing comes out at all".

**Why the change should act on the symptom.** Quiet or silence-heavy input is
where `no_speech_prob` climbs above `0.6` while the decode stays confident;
that is the population the repo gate deletes and the library keeps.

**Confound to keep separate.** The logged `vad_frames=0` at `peak_rms 0.024`
(README) is the VAD pre-filter discarding quiet speech *before* decoding — a
different mechanism, owned by `Q02`. A clip zeroed by the VAD is empty in both
arms of this experiment and contributes nothing to its target metric.

## 3 Prerequisites

- **Harness pieces** (`HARNESS.md` §1): `scripts/asr_corpus.py`,
  `scripts/asr_metrics.py`, `scripts/asr_experiment.py` with `preflight`,
  `baseline` and `run`, and their pure tests, all green.
- **Injection field**: `DecodeOptions.assemble_no_speech_gate: bool = True`
  (`HARNESS.md` §3.2), threaded so `_assemble` takes `gate: bool` and, when
  `False`, keeps every segment while still running `_validate_output`. No
  config key is added or changed; `asr.silence_threshold` keeps its meaning as
  the library's `no_speech_threshold` and the config stays at 23 keys
  (`AGENTS.md` hard rule 9).
- **Corpus lanes**: `base`, `tail`, `cue` and `silence` — all four are built by
  the foundation commit and covered by the baseline (`HARNESS.md` §2.4, §7.1).
  Fork **F1** in §8 records why the `silence` lane had to land there rather than
  later; option F1a was taken.
- **Baseline**: `docs/experiments/baseline.json` present, `schema == 1`,
  containing `aggregates.per_lane` for `base`, `tail` and `cue` and a `noise`
  block with `trailing_junk_rate`. `git_dirty == false`.
- **Instrumentation** (§3.1 below) merged into `scripts/asr_experiment.py`
  before the first run of this plan.

### 3.1 Gate-firing instrumentation (numeric only)

The plan must report **how often the shipped gate actually fires**. Nothing in
`src/` needs to change to get it: at temperature 0 the decode is deterministic
(`HARNESS.md` §8.3), so the segment list the gate-off arm returns *is* the
pre-gate list of the gate-on arm. Counting there measures the shipped
behaviour exactly.

The executing agent extends the in-process engine to compute, from the
`TranscriptionResult` it already holds and `cfg.asr.silence_threshold`, four
additional **numeric** per-clip keys in `clips.jsonl` (`HARNESS.md` §4.1):

| key | value |
|---|---|
| `assemble_segments_total` | `len(result.segments)` |
| `assemble_gated_segments` | count of `result.segments` with `no_speech_prob >= cfg.asr.silence_threshold` |
| `segment_no_speech_max` | max `no_speech_prob` over `result.segments`, `null` when empty |
| `segment_no_speech_min` | min `no_speech_prob` over `result.segments`, `null` when empty |

and two aggregates (`HARNESS.md` §4.2, also per lane):

| key | value |
|---|---|
| `assemble_gate_fire_rate` | fraction of scored clips with `assemble_gated_segments >= 1` |
| `assemble_gated_segment_total` | Σ `assemble_gated_segments` |

`assemble_gated_segments` and `assemble_segments_total` are copied into
`clip_scores` (`HARNESS.md` §4.3); all six values are numbers, so
`tests/test_asr_baseline_file.py`'s no-text rule is untouched. In the
**gate-on** arm these read `0` and `len(kept)` by construction — that zero is
the wiring check, not a result. The subprocess engine does not emit them
(`null`), and `decide` never uses them: they are descriptive, so no
`thresholds.json` schema pressure. Add the four/two keys to `HARNESS.md` §4.1
and §4.2 as in-process-only optional fields in the same commit.

## 4 Variant matrix

Both variants are in-process (`engine: "auto"` resolves to `inprocess`
because `decode` is non-empty, `HARNESS.md` §3), `repeats: 1` (temperature
stays at `(0.0,)`, so §8.3's repeat rule does not apply).

| # | Name | Path | `decode` | Lanes | Engine | Repeats | Role |
|---|---|---|---|---|---|---|---|
| V1 | `q06-gate-on` | `docs/experiments/variants/Q06/q06-gate-on.json` | `{"assemble_no_speech_gate": true}` | base, tail, cue | inprocess | 1 | Identity control: cross-engine parity check against the subprocess baseline, and the instrumentation wiring check. |
| V2 | `q06-gate-off` | `docs/experiments/variants/Q06/q06-gate-off.json` | `{"assemble_no_speech_gate": false}` | base, tail, cue | inprocess | 1 | Treatment; the plan's verdict run. |
| V3 | `q06-gate-off-silence` | `docs/experiments/variants/Q06/q06-gate-off-silence.json` | `{"assemble_no_speech_gate": false}` | silence | inprocess | 1 | Fork **F1** only; see §8. |
| V4 | `q06-gate-on-silence` | `docs/experiments/variants/Q06/q06-gate-on-silence.json` | `{"assemble_no_speech_gate": true}` | silence | inprocess | 1 | Fork **F1** only; the silence control. |

```json
{
  "schema": 1,
  "name": "q06-gate-off",
  "plan": "Q06",
  "lanes": ["base", "tail", "cue"],
  "tags_any": [],
  "tags_all": [],
  "engine": "auto",
  "repeats": 1,
  "config": {},
  "decode": {"assemble_no_speech_gate": false}
}
```

V1 is the same file with `"name": "q06-gate-on"` and `true`; V3/V4 are the
same two files with `"lanes": ["silence"]` and names suffixed `-silence`.

### 4.1 The excluded third variant — "library-equivalent" gate

A third variant that keeps the re-gate but gives it the library's rule
(`no_speech_prob > threshold` **and** `avg_logprob <= log_prob_threshold`,
which needs `avg_logprob` carried onto `SegmentInfo` at `model.py:126-138`
and a tri-state `assemble_no_speech_gate`) is **excluded, on proof rather
than cost**:

- The library applies exactly that rule at `transcribe.py:1215-1234`, with
  the same `no_speech_threshold` (`model.py:118`) and the library-default
  `log_prob_threshold = -1.0` (`DecodeOptions.log_prob_threshold`, not
  overridden by `src/`).
- Every pass surviving to `_assemble` therefore satisfies
  `no_speech_prob <= 0.6` **or** `avg_logprob > -1.0`.
- A downstream gate dropping on `no_speech_prob > 0.6` **and**
  `avg_logprob <= -1.0` is the exact complement of that condition: it can
  never fire. It is a no-op, and running it would burn ~10 minutes of GPU to
  reproduce `q06-gate-off` under a different name.

The single residual difference is the boundary: a pass with `no_speech_prob`
exactly equal to the threshold and `avg_logprob <= -1.0` — a float-equality
case. It is covered by V2 anyway, since V2 keeps that pass too. If a future
plan changes `log_prob_threshold` or `no_speech_threshold` so the two gates no
longer share values (e.g. `Q01`'s temperature ladder combined with a different
`log_prob_threshold`), this proof lapses and the variant must be reconsidered
— record that in §10 of the plan that makes the change.

## 5 Procedure

Every command runs from the repo root with the repo venv (`AGENTS.md` hard
rule 1). No step needs a human.

```sh
# 0. Harness self-check and instrumentation tests (pure, no GPU).
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration" tests/test_asr_metrics.py \
  tests/test_asr_experiment.py tests/test_asr_corpus.py tests/test_asr_baseline_file.py

# 1. Preflight: venv, model cache, manifest digests, GPU, compute type, git.
.venv/bin/python scripts/asr_experiment.py preflight

# 2. V1 — identity control (~10 min).
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q06/q06-gate-on.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q06/thresholds.json

# 3. V2 — treatment (~10 min).
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q06/q06-gate-off.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q06/thresholds.json
```

**Exit-code handling.**

- Step 0/1 non-zero → stop; fix the harness. This plan does not start on a
  broken harness or a dirty tree.
- **Step 2 (V1) must exit `0`.** V1 changes nothing, so a deny means the
  in-process engine does not reproduce the subprocess baseline and every V2
  number would be unattributable. Treat a V1 deny as a **harness error**: stop,
  record the verdict line in §9's Outcome, and do not run V2. (The one legal
  divergence is `rtf_p95`/`load_ms`; guard 3 uses `rtf_p95`, which is
  decode-only and cross-engine comparable per `HARNESS.md` §3.1. If V1 denies
  on `rtf_p95` alone, re-run V1 with `engine: "subprocess"` and
  `decode: {}` removed is *not* possible — instead record it and treat guard 3
  as advisory for V2 as well, noting it in the Outcome.)
- Step 3 exit `2` → harness error; stop and record.
- Step 3 exit `0` or `1` → continue to step 4; the exit code alone is **not**
  the plan's verdict here (§6 explains why and pre-registers the rest).

**Margin ladder** (only if step 2 or 3 exits `2` complaining about the
target margin — see §6.1): edit `thresholds.json`'s `target.margin` to `0`,
re-run; if that is also rejected, set it to `0.0001`, re-run, and treat a
deny whose only failing guard is the target metric as the *no-harm* branch of
§6.2. Nothing else in the thresholds file changes; record which rung was used.

```sh
# 4. Pre-registered numeric checks P1-P4 (no GPU; reads two result.json files).
.venv/bin/python - \
  docs/experiments/baseline.json \
  build/asr-experiments/<v2-run-id>/result.json \
  build/asr-experiments/<v1-run-id>/result.json <<'PY'
import json, sys

base = json.load(open(sys.argv[1]))
off  = json.load(open(sys.argv[2]))
on   = json.load(open(sys.argv[3]))
LANES = ["base", "tail", "cue"]
fail = []

def agg(doc, lane=None):
    a = doc["aggregates"]
    return a["per_lane"][lane] if lane else a

def scores(doc):
    return {(r["clip_id"], r["repeat"]): r for r in doc["clip_scores"]}

# P1 - no-harm on empties, over the thresholds' lanes.
b_empty = sum(agg(base, ln)["empty"] for ln in LANES)
r_empty = sum(agg(off, ln)["empty"] for ln in LANES)
print(f"P1 empty baseline={b_empty} run={r_empty}")
if r_empty > b_empty:
    fail.append("P1: empty count increased")

# P2 - trailing junk on the tail lane, tolerance 2x the baseline's noise.
noise = base["noise"]["trailing_junk_rate"]
b_junk = agg(base, "tail")["trailing_junk_rate"]
r_junk = agg(off, "tail")["trailing_junk_rate"]
print(f"P2 trailing_junk_rate[tail] baseline={b_junk:.4f} run={r_junk:.4f} "
      f"tolerance={2 * noise:.4f}")
if r_junk > b_junk + 2 * noise:
    fail.append("P2: trailing_junk_rate on tail exceeded 2x noise")

# P4 - benefit and exposure (descriptive, never blocking).
bs, rs = scores(base), scores(off)
common = sorted(set(bs) & set(rs))
recovered = [k for k in common if bs[k]["empty"] and not rs[k]["empty"]]
lost      = [k for k in common if not bs[k]["empty"] and rs[k]["empty"]]
print(f"P4 clips={len(common)} recovered={len(recovered)} lost={len(lost)}")
for ln in LANES:
    print(f"P4 fire_rate[{ln}] on={agg(on, ln)['assemble_gate_fire_rate']:.4f} "
          f"off={agg(off, ln)['assemble_gate_fire_rate']:.4f} "
          f"gated_segments[{ln}]={agg(off, ln)['assemble_gated_segment_total']}")
print("P4 fire_rate[all] off="
      f"{agg(off)['assemble_gate_fire_rate']:.4f}")
if lost:
    fail.append(f"P4: {len(lost)} clips lost their text")

for f in fail:
    print("FAIL", f)
print("PLAN-CHECKS", "FAIL" if fail else "PASS")
sys.exit(1 if fail else 0)
PY
```

Fork **F1** adds, before step 4:

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q06/q06-gate-on-silence.json --no-compare
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q06/q06-gate-off-silence.json --no-compare
.venv/bin/python - \
  build/asr-experiments/<on-silence-run-id>/result.json \
  build/asr-experiments/<off-silence-run-id>/result.json <<'PY'
import json, sys
on, off = (json.load(open(p)) for p in sys.argv[1:3])
n_on  = sum(0 if r["empty"] else 1 for r in on["clip_scores"])
n_off = sum(0 if r["empty"] else 1 for r in off["clip_scores"])
print(f"P3 silence non-empty on={n_on} off={n_off} clips={len(on['clip_scores'])}")
print("P3", "FAIL" if n_off > n_on else "PASS")
sys.exit(1 if n_off > n_on else 0)
PY
```

The silence lane has an empty reference, so `wer` degenerates to the
hypothesis word count (`HARNESS.md` §5.3) and `wer_mean` is meaningless there.
The silence lane is therefore **never** in a `thresholds.json` `lanes` list
and is never compared to `baseline.json` (`--no-compare`); it is judged only
by P3.

## 6 Metrics & accept/deny

### 6.1 `thresholds.json`

`docs/experiments/variants/Q06/thresholds.json`, used by V1 and V2 verbatim:

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.25,
  "forbid_empty_regressions": true,
  "target": null,
  "guards": [
    {"metric": "empty", "direction": "lower",
     "max_regression": 0, "margin_kind": "absolute"}
  ],
  "lanes": ["base", "tail", "cue"],
  "min_clips": 700
}
```

This is a **no-harm** plan, so it has no target: `"target": null` is legal
(`HARNESS.md` §6.1) and rule 2 is skipped. "`empty` must not increase" is then
exactly a `max_regression` of `0` on an integer count — no negative margin, no
strict-versus-non-strict reading to worry about, and the verdict line says
`target null` rather than naming a target the plan never had.

§7.1's "guard bound ≥ recorded noise" rule is satisfied trivially: the baseline's
`noise` block records no spread for `empty`, and at temperature 0 the decode is
deterministic (§8.3), so the count has no run-to-run spread to absorb.

**Fallback only**, for the case where this plan runs before the foundation
commit has landed the `guards` array: the ladder in §5 — a `target` of
`{"metric": "empty", "direction": "lower", "margin": -0.5, "margin_kind":
"absolute"}`, which encodes the same "must not increase" under either reading of
§6.2 rule 2, together with a `validate_variant` that tolerates a negative margin.
It is never the preferred spelling and must not be used when `guards` exists.

`trailing_junk_rate` is deliberately **not** the target: §7.1 requires a
target margin of at least twice its recorded noise, which a no-harm (≤ 0)
margin can never satisfy — and with `"target": null` there is no target to put
it in. It is enforced as P2 against exactly that `2 × noise` tolerance instead.

### 6.2 The decision rule (pre-registered)

The harness verdict on V2 supplies guards 1 (`wer_mean`), 3 (`rtf_p95`), 4
(no non-empty → empty clip) and 5 (no new errored clip). P1–P3 supply the
target and the two directional guards the contract cannot express.

**Accept iff all of**: V1 exited `0`; V2's guards 1, 3, 4 and 5 all passed;
`PLAN-CHECKS PASS` (P1, P2, P4-lost); and, under fork F1, `P3 PASS`.

Two accept branches, distinguished only in what §9's Outcome records:

- **Branch A — the corpus exercised the gate**
  (`assemble_gate_fire_rate > 0` on any lane, i.e. `P4 recovered >= 1` or
  `assemble_gated_segment_total >= 1`). Empirical: the run shows the gate
  firing and shows removing it costs nothing. Record the recovered clip count
  and the per-lane fire rates.
- **Branch B — the corpus never exercised the gate**
  (`assemble_gate_fire_rate == 0.0` on every lane). Expected, because
  LibriSpeech `test-clean` is clean read speech and the gate only fires on
  passes the library rescued. The run then proves *no harm* and nothing else,
  and the case for the change rests on §2's mechanism proof, which is
  pre-registered **here, in advance**: the repo gate is strictly stricter than
  the library gate on both axes, is all-or-nothing per pass, cannot strip a
  trailing segment, and can only ever discard a pass the library kept because
  the decoder was confident. That judgement is made now, not by the executing
  agent. Branch B still **accepts**, with Status
  `accepted (no-harm; gate never fired on this corpus)`, and §9's real-machine
  gate carries the burden of confirming the symptom is addressed.

**Deny** if any of P1, P2, P3, P4-lost fails, or if V2 fails guard 1, 3, 4 or
5. In particular a P2 or P3 failure is the "more junk got through" outcome the
gate exists to prevent, and it settles the question in the gate's favour.

**Harness error (exit 2, no verdict)** if V1 denies, if preflight fails, if
either run exits 2 after the margin ladder is exhausted, or if the manifest,
device or model differs from the baseline's (`HARNESS.md` §6.4).

Matrix decision: there is nothing to choose between — V1 is a control and V2
is the single treatment.

## 7 Cost estimate

In-process, `HARNESS.md` §8.4 (≈0.7 s/clip after one load; ≈2 s load).

| Run | Clips × repeats | Time |
|---|---|---|
| V1 `q06-gate-on` | 700 × 1 | ≈9 min + load |
| V2 `q06-gate-off` | 700 × 1 | ≈9 min + load |
| F1 V4 `q06-gate-on-silence` | 20 × 1 | < 1 min |
| F1 V3 `q06-gate-off-silence` | 20 × 1 | < 1 min |
| preflight (one cold load) | — | ≈1 min |
| P1–P4 checks | — | seconds |

**Total ≈ 25 min wall** on the reference machine (RTX 3080 Laptop), ≈22 min
without fork F1. Disk: four run directories, a few MB each; the optional
silence lane adds ≈3 MB of WAV under `build/asr-corpus/wav/silence/`. No new
downloads — the corpus and model must already be present (`HARNESS.md` §8.2).

If fork F1 is taken *after* the baseline exists and the silence clips are
appended to the corpus manifest, `HARNESS.md` §7.3 rule 2 forces a
re-baseline: **+3 h**. §8's F1 recommendation exists to avoid exactly that.

## 8 Risks, confounds, invariants

**R1 — a junk-only pass reaches the transcript on near-silence.** The central
risk: without the repo gate, a pass with `no_speech_prob >= 0.6` is emitted.
The library gate is the remaining defence and it only rescued that pass
because `avg_logprob > -1.0`. Checked by P3 (silence lane: pure room tone,
empty reference — any text is pure fabrication) and by P2 (`tail` lane: 1/3/5 s
of appended room tone after real speech, the augmentation most likely to
produce a low-energy second pass). If the library gate is not enough, P2 or P3
fails and the plan denies.

**R2 — `PathologicalOutputError` on the extra segments.** `_validate_output`
runs over the kept list (`model.py:218-224`), so gate-off feeds it more words
against the same `vad_seconds` budget (`word_limit = max(12, ceil(8 ×
vad_seconds))`, `model.py:200`). A clip that passed with the gate could now
raise, which in the daemon discards the whole decode. Caught: the runner
records the exception class name as `error` with metrics `null` and
`empty: true` (`HARNESS.md` §4.1), which trips guard 5 (new error) and
P4-lost. This is a genuine deny path, not a nuisance — if it fires, the
follow-up is a plan about the density limit, not a fix inside Q06.

**R3 — the corpus does not exercise the gate at all** (Branch B). Mitigated by
pre-registering the decision in §6.2 and by making the real-machine acceptance
gate in §9 the empirical check. The instrumentation in §3.1 turns this from an
unknown into a reported number.

**R4 — confound with `Q02` (VAD).** `vad_frames=0` clips are dropped before
decoding and are empty in both arms; they cannot move the target. Do not read
a Q06 result as evidence about quiet-speech VAD behaviour. Likewise `Q07`
(`hallucination_silence_threshold`) and `Q05`/`Q11` (repetition, tail filter)
act on the same `tail`-lane junk metric — merge one accepted change at a time
and re-baseline between (`HARNESS.md` §7.3, `README.md` step 4).

**R5 — cross-engine comparison.** V2 is in-process; `baseline.json` is
subprocess. Legal for text metrics and `decode_ms`/`rtf` (`HARNESS.md` §3.1),
and the target is not a speed metric so §6.4's engine refusal does not apply.
V1 exists to make the assumption falsifiable rather than assumed.

**R6 — `silence_threshold` becomes single-purpose.** After the change the key
only feeds the library's `no_speech_threshold`. Its default value is not
retuned here (§10) and the key count stays at 23.

### Fork F1 — the silence-only control lane (decision required)

`HARNESS.md` §2.4 defines `base`, `tail`, `cue`, `user` and `pseudo-gold`;
there is **no silence lane and no quiet lane**, and no `Q02` file exists yet
to define one. R1 is the plan's main risk and P3 is its only direct check, so
the lane matters. Three options:

- **F1a — recommended: add a `silence` lane to `HARNESS.md` §2.4 and
  `scripts/asr_corpus.py` before the programme's baseline is established.**
  20 clips of Gaussian room tone at −60 dBFS, durations `{3.0, 5.0, 8.0}` s,
  seeded `zlib.crc32(f"silence-{i}")`, `reference: ""`, `derived_from: null`,
  `augmentation: {"kind": "pure_noise", "seconds": s, "rms_dbfs": -60.0}`,
  `lane: "silence"`, tag `silence`. Cost is minutes if it lands in the
  foundation commit, because it changes the manifest digest and thus the
  baseline (§7.3 rule 2). **This is an orchestrator-level decision that
  affects the foundation, not something Q06 can defer.** Several other plans
  (`Q01`, `Q05`, `Q07`, `Q11`) would want the same lane.
- **F1b — fallback if the baseline already exists.** Generate the same 20
  clips into a *side* manifest under `build/asr-silence/manifest.json`, leaving
  the corpus manifest and its digest untouched, and give
  `scripts/asr_experiment.py run` a `--manifest <path>` and a `--no-compare`
  flag so the pair can be run and judged by P3 alone. Small additive runner
  change; no re-baseline. Use this if the baseline is already checked in.
- **F1c — skip the silence lane.** Rely on P2 (`tail`, 5 s of room tone after
  speech) plus guards 4/5. Weakest: `tail` clips always contain real speech, so
  a pass that is *entirely* silence never occurs and R1 goes unchecked in its
  purest form. Choose this only if neither F1a nor F1b is available, and record
  the gap in the Outcome.

**Settled: F1a.** `HARNESS.md` §2.4 now defines the `silence` lane and the
foundation commit builds it before the baseline, exactly as F1a describes. F1b
and F1c are recorded because the plan is written so that all three work — under
F1c, drop V3/V4 and the P3 snippet and mark P3 `SKIPPED` in the Outcome — but
neither should be needed.

### `HARNESS.md` §9 invariant checklist (restated)

- **No transcript text** outside `build/**/clips.jsonl`. The four new per-clip
  keys and two aggregates in §3.1 are numbers or `null`; `clip_scores`,
  `result.json`, `report.md`, `verdict.json`, stdout, the P1–P4 snippets, this
  file and everything under `docs/experiments/variants/Q06/` carry no text
  field. The snippets in §5 print counts and rates only.
- **No network in the ASR path.** `local_files_only=True` (`model.py:87`)
  unchanged; the in-process engine downloads nothing; this plan runs no
  `asr_corpus.py fetch`.
- **No platform imports.** The harness touches core modules only; the change
  is inside `transcribe/model.py`, which is core.
- **Test policy** (`AGENTS.md` hard rule 4): the instrumentation's pure part
  (counting segments at or above a threshold) gets a seen-to-fail test in
  `tests/test_asr_experiment.py`; nothing mocks the model, `soundfile` or
  `subprocess`. On accept, the two tests this plan deletes are deleted
  *because* they are the green-mock failure mode rule 4 names.
- **Fixed behaviour stays fixed** until accept: `DecodeOptions()` defaults are
  unchanged by this plan's runs, nothing under `src/` constructs a non-default
  instance, user config keeps exactly 23 keys.
- **Venv only**, SPDX header on any new `.py`, ruff clean, line length 100.

## 9 Deliverables & follow-through

**On accept** — one commit on `dev`, conventional message (`fix:`, since it
removes a filter that discards correct output):

1. **`src/stenographer/transcribe/model.py:215`** — delete the filter. `kept`
   becomes every segment; `_assemble` loses its `silence_threshold` parameter
   (`model.py:210`) and the call at `model.py:142` loses that argument.
   `model.py:118` keeps `no_speech_threshold=cfg.silence_threshold` — the
   library gate is what remains. Update `_assemble`'s docstring
   (`model.py:214`), which currently promises "Gate probable-silence
   segments"; it now validates and assembles only.
2. **`DecodeOptions.assemble_no_speech_gate`** — delete the field and the
   `gate: bool` parameter with it. The field exists to answer this one
   question; once answered it is dead configuration, and `HARNESS.md` §3.2's
   rule is that the defaults are byte-for-byte today's literals — there is no
   literal left to mirror. Update the `dataclasses.asdict(DecodeOptions())`
   pinning test (`HARNESS.md` §3.2) and the `DecodeOptions` block in
   `HARNESS.md` §3.2 in the same commit. *(If the harness is judged to need a
   permanent regression switch, the alternative is flipping the default to
   `False` and keeping the field; prefer deletion — the pinning test then
   documents the removal.)*
3. **`tests/transcribe/test_model.py`** —
   delete `test_assemble_drops_silence_segments_and_concatenates`
   (`:134-148`) and `test_assemble_boundary_segment_at_threshold_is_dropped`
   (`:152-157`). Both assert the deleted behaviour, and both construct three
   differing `no_speech_prob` values (0.1 / 0.8 / 0.2) inside a 1.5 s span —
   a single decode pass, where `transcribe.py:1364` copies one value onto
   every segment. They are green tests of an impossible input
   (`AGENTS.md` hard rule 4). Replace with one seen-to-fail test that
   `_assemble` concatenates every segment in order and preserves each
   segment's words, built from ordinary segments — no test may re-encode the
   per-segment `no_speech_prob` shape. Keep
   `test_assemble_validates_survivor_word_density` (`:158-163`), renaming
   "survivor" out of its name, and keep the `_segment` helper.
4. **`src/stenographer/config.py:259`** — the template comment
   `silence_threshold = 0.6        # post-decode no-speech-probability gate`
   now describes a gate that no longer exists. Change it to name the decode-time
   gate, e.g. `# decoder no-speech gate (log-prob vetoed)`, within the column
   the template uses. `tests/cli/test_setup_config.py` and `tests/test_config.py`
   reference the key, not the comment; check the byte-comparison test in
   `tests/cli/` still passes.
5. **`AGENTS.md` hard rule 5** — the sentence "The anti-hallucination decode
   stack (VAD pre-filter, no-speech gate, silence trimming, short-audio token
   ceiling, output validation) is fixed behavior, not configuration." names a
   layer that is being removed. Replace "no-speech gate" with wording that
   scopes it to the library's: *"the decoder's own log-prob-vetoed no-speech
   gate (fed by `asr.silence_threshold`; the daemon adds no second, unvetoed
   re-gate — it discarded whole confident utterances, Q06)"*. `AGENTS.md`'s
   own rule is that a settled decision changes in the same commit as the code.
   Also add the removal to the cut-features paragraph's authorized list if the
   orchestrator judges it a lifecycle-visible change.
6. **`docs/experiments/README.md`** — the `Q06` index row's goal sentence
   becomes the outcome; and this file's Status becomes `accepted (<date>)` or
   `accepted (no-harm; gate never fired on this corpus) (<date>)` per §6.2,
   with an Outcome section carrying the verdict line, both run ids, P1–P4
   numbers, and which fork/margin rung was used. Numbers only.
7. **Re-baseline** — `HARNESS.md` §7.3 rule 1: the shipped defaults moved, so
   `docs/experiments/baseline.json` is re-run (all seven baseline lanes,
   subprocess, 3 repeats, ≈5.5 h) in a separate commit that touches nothing
   under `src/`.
8. **`AGENTS.md` acceptance gates, before dev → main** (real machine, owner's
   hardware): `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest` green; real
   dictation end-to-end in `hold`, `toggle` and `hybrid`; a **quiet-speech
   dictation check** — several deliberately quiet utterances, each producing
   text rather than silence, which is the symptom this plan targets and the
   only empirical evidence under Branch B; and the logging gate (one
   `pipeline: utterance` line per dictation whose `segments`/`words` fields
   match, with no transcript or audio content in `stenographer.log`), since
   the `segments`/`words` counts at `daemon.py:655-656` now include formerly
   gated segments.

**On deny** — append an "Outcome" section to this file with the verdict line,
the run ids, the failing check (P1/P2/P3/P4 or the harness guard), and the
per-lane numbers; copy `verdict.json` to
`docs/experiments/results/Q06-<run-id>.json`; set Status to
`denied (<date>)`. Change nothing under `src/`. A deny is informative: it says
the library gate alone is not sufficient on this corpus, and the natural
follow-up is a plan that *narrows* the re-gate (a trailing-segment-only filter,
which is `Q11`'s territory) rather than one that removes it.

## 10 Out of scope

- **The VAD pre-filter** and the `vad_frames=0` quiet-speech drop — `Q02`.
  A different mechanism at a different stage; noted in §2 only to prevent
  attributing its effect to this gate.
- **Tuning `asr.silence_threshold`'s value** (`0.6`). This plan tests the
  *presence* of the daemon-side re-gate, not the number both gates share. No
  plan in the `README.md` index currently owns that value; if the owner wants
  it swept, it is a new `config`-lane plan (`config: {"asr":
  {"silence_threshold": …}}`, subprocess engine, no `DecodeOptions` needed) —
  flagged here as a gap in the programme.
- **`log_prob_threshold`, `compression_ratio_threshold` and the temperature
  ladder** — `Q01`. They are inert at `temperature=(0.0,)` except for the
  log-prob veto this plan's proof relies on; if `Q01` is accepted first,
  re-check §4.1's no-op proof before reusing it.
- **`hallucination_silence_threshold`** — `Q07`. **Terminal repetition
  removal** — `Q05` and `Q11`; a post-decode filter that strips a trailing
  junk segment is the thing `_assemble`'s gate could never do, and `Q11` is
  where it belongs. If this plan is accepted, the gate it deletes is step 1 of
  Q11's `_assemble` call-site ordering, so Q11's order becomes
  `_validate_output` → `filter_tail` → join and its filter is otherwise
  untouched (it reads word probabilities, which this gate never saw). Q11 §10
  carries the mirror of this sentence; whichever plan merges second updates the
  ordering in the same commit.
- **The `_validate_output` word-density limit** (`model.py:200`). Q06 only
  observes whether removing the gate trips it (risk R2); changing the limit is
  a separate plan.
- **The batched inference path** (`faster_whisper/transcribe.py:247`, which
  applies the no-speech rule differently) — `S02`.
- **Speed.** `rtf_p95` is a guard here, not a subject; the in-process engine
  makes `load_ms` meaningless (`HARNESS.md` §3.1) and the S-series owns
  latency.
