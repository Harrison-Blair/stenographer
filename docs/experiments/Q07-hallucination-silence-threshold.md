# Q07 — `hallucination_silence_threshold` × the VAD gap cap

Status: planned (2026-08-29)

## 1 Hypothesis

Lowering `hallucination_silence_threshold` from `2.0` to `1.0` reduces
`trailing_junk_rate` by ≥ 0.03 absolute on the `tail` lane without moving
`wer_mean` by more than +0.002 or `rtf_p95` by more than ×1.25.

**Pre-registered prediction (the plan expects its own primary hypothesis to
fail at the shipped VAD settings).** With `vad_min_silence_duration_ms = 500`
and `vad_speech_pad_ms = 250`, the silence the decoder can still see is too
short for either threshold to act, so `hst ∈ {None, 1.0, 2.0}` should produce
*byte-identical* hypotheses on every clip. The matrix is built so that a null
result is a measurement of the mechanism rather than an absence of one: the
`vad_min_silence_duration_ms = 2000` row and the `vad_filter = false`
diagnostic pair restore retained silence in known quantities, and the
differ-count across each `{None, 2.0}` pair says exactly how much work the
branch does at each level of retained silence. §6 states the accept rule for
both the "lower it" outcome and the "it only ever deletes real speech, so
disable it" outcome; §9 states what a fully null result is written up as.

## 2 Symptom & mechanism

**Symptom** (`docs/experiments/README.md`, symptom 2): some utterances end in
hallucinated loops — "thank you", "and more and more". Metric:
`trailing_junk_rate` (HARNESS.md §5.5).

**What the daemon asks for.** `src/stenographer/transcribe/model.py:27` fixes
`_HALLUCINATION_SILENCE_SECONDS = 2.0`, passed at `model.py:119`;
`word_timestamps=True` at `model.py:124` (the option is inert without it);
`vad_filter=cfg.vad_filter` at `model.py:116` with `_VAD_PARAMETERS` at
`model.py:32-37` — `min_silence_duration_ms = 500` (`model.py:35`) and
`speech_pad_ms = 250` (`model.py:36`).
`condition_on_previous_text=False` (`model.py:121`) means no clip can
contaminate the next, so one `Model` may serve a whole variant.

**What the library does with it.** In
`.venv/lib/python3.14/site-packages/faster_whisper/transcribe.py`:

- `word_anomaly_score` (1242-1252) and `is_segment_anomaly` (1254-1260) score a
  segment's first eight non-punctuation words: probability < 0.15, duration
  < 0.133 s, or duration > 2.0 s. A fluent, high-probability "Thank you."
  scores ~0 and is **not** anomalous — the threshold never gets a chance to
  look at it. This is the first reason the option under-delivers, and it is
  independent of silence.
- Branch A, leading rewind (1294-1307): if the window's first words-bearing
  segment is anomalous and `first_segment["start"] - time_offset > threshold`,
  `seek` is rewound past the gap and the window is re-decoded. Acts on
  *leading* silence.
- Branch B, surrounded-by-silence truncation (1309-1339): for an anomalous
  segment, `silence_before` (1320-1324) is
  `start - hal_last_end > threshold` **or** `start < threshold` **or**
  `start - time_offset < 2.0`; `silence_after` (1325-1329) is
  `hal_next_start - end > threshold` **or** the next segment is anomalous
  **or** `window_end_time - end < 2.0`. Both true ⇒ `current_segments[si:] = []`
  (1337) and a forward re-seek (1331-1336).

**Two corrections to the naive reading, both load-bearing here.**

1. `window_end_time` is `time_offset + 30 s` unconditionally (1169-1172), *not*
   clipped to the content. For any clip whose post-VAD content is under ~28 s —
   every clip in this corpus at the shipped settings — the
   `window_end_time - end < 2.0` escape in `silence_after` is dead. So a
   trailing hallucination is only ever removed when **more than `threshold`
   seconds of retained silence follow it**, with `hal_next_start` falling back
   to `time_offset + segment_duration` ≈ content end. Removing trailing junk
   therefore requires *keeping* trailing silence, which is precisely what the
   VAD takes away.
2. Lowering the threshold is not monotonically more aggressive. It widens the
   two gap tests but narrows `start < threshold` (1322) and the end-jump
   `content_duration - end < threshold` (1335). Losing that end-jump means the
   re-seek at 1332 can re-decode the region the junk came from, so `hst = 1.0`
   could plausibly *raise* trailing junk for junk landing near content end.
   That is a real, falsifiable outcome of this experiment, not a nuisance.

**How much silence survives the VAD** (`faster_whisper/vad.py`): a chunk closes
only after `min_silence_samples` of silence (79, 135-152) and closes at
`temp_end`, the silence's *start*; the padding loop (161-182) then either
absorbs an inter-chunk gap entirely when it is shorter than
`2 × speech_pad_samples` (164-170) or shaves `speech_pad_ms` off each side
(171-177); the final chunk is padded by `speech_pad_ms` only (178-181), except
when the audio ends while still triggered (154-159), in which case the whole
remaining tail is retained. With `speech_pad_ms = 250` that gives:

| VAD `min_silence` | retained internal silence | raw internal pause needed for `gap > threshold` |
|---|---|---|
| 500 ms (shipped) | 0 for raw ≤ 0.5 s; raw − 0.5 s above | > 2.5 s at `hst 2.0`; > 1.5 s at `hst 1.0` |
| 2000 ms | raw for raw ≤ 2.0 s; raw − 0.5 s above | > 2.5 s at `hst 2.0`; > 1.0 s at `hst 1.0` |

and at the trailing edge, with an appended tail of 1/3/5 s:

| VAD `min_silence` | retained trailing silence (`tail` lane) |
|---|---|
| 500 ms | 250 ms for every tail length — the `tail` lane collapses onto `base` |
| 2000 ms | 1.0 s for `tail=1s` (vad.py:154-159 fires); 250 ms for `tail=3s`/`5s` |
| `vad_filter = false` | the full 1.0 / 3.0 / 5.0 s |

Read against correction 1: only the `vad_filter = false` row leaves enough
trailing silence for Branch B to fire on a trailing hallucination at all. With
a 5 s tail and speech ending at `T`, junk is removable when it starts after
`T + threshold` and ends before `content_end - threshold` — a 3 s window at
`hst 1.0` against a 1 s window at `hst 2.0`. That difference is the mechanism
this plan measures, and the reason the diagnostic pair exists.

**Why the change should act on the symptom** — and the honest counter: it
should act only where retained silence exceeds the threshold. The matrix
brackets that condition instead of assuming it.

## 3 Prerequisites

- **Harness pieces.** HARNESS.md §1 in full: `scripts/asr_corpus.py`,
  `scripts/asr_metrics.py`, `scripts/asr_experiment.py` with the `preflight`,
  `baseline` and `run` subcommands, their pure tests green, and the
  `DecodeOptions` seam of HARNESS.md §3.2 landed in
  `src/stenographer/transcribe/model.py` with its pinning test.
- **Injection fields.** `DecodeOptions.hallucination_silence_seconds`
  (`float | None`), `DecodeOptions.vad_min_silence_duration_ms` (`int`),
  `DecodeOptions.word_timestamps` (stays `true` in every variant — HARNESS.md
  §3.2 has `validate_variant` reject `word_timestamps=false` beside a non-null
  threshold). Config key: `asr.vad_filter` (`src/stenographer/config.py:64`,
  default `true` at `config.py:258`), used by the two diagnostics only.
- **Corpus lanes/tags.** `tail` (300 clips: 100 base clips × 1 s / 3 s / 5 s of
  −60 dBFS room tone), produced by HARNESS.md §2.4 and characterised by Q09.
  The `tail` clips carry the `base` clips' references verbatim, so WER,
  deletions and `leading_word_recall` measured on `tail` also guard the real
  speech. Tags used in the analysis: `tail=1s`, `tail=3s`, `tail=5s`.
- **Baseline.** `docs/experiments/baseline.json` present, written from a clean
  tree, with a `noise` block carrying `trailing_junk_rate` and `wer_mean`, and
  with `per_lane.tail` populated.
- **Order.** Runs after the foundation, after Q09 (the lane) and after Q04
  (`compute_type` settled). Independent of Q01/Q05/Q11; see §8 for the Q02
  overlap.

## 4 Variant matrix

Eight variants. Every one carries a non-empty `decode`, so `engine: "auto"`
resolves to the in-process engine (HARNESS.md §3) — the only engine that can
vary `DecodeOptions`. `repeats: 1`: every variant keeps `temperature` at
`(0.0,)`, so HARNESS.md §8.3's three-repeat rule does not apply. All eight run
`lanes: ["tail"]`, `tags_any: []`, `tags_all: []`.

Note that **A1 spells out today's defaults explicitly**. It must: an empty
`decode` would resolve `engine: "auto"` to the subprocess engine and stop being
a matched control.

| # | Variant name | `decode` | `config` | Role |
|---|---|---|---|---|
| A1 | `q07-hst-2-ms500` | `hallucination_silence_seconds: 2.0`, `vad_min_silence_duration_ms: 500` | — | Shipped control; cross-engine sanity check against the baseline |
| A2 | `q07-hst-1-ms500` | `1.0`, `500` | — | **Candidate** — the primary hypothesis |
| A3 | `q07-hst-none-ms500` | `null`, `500` | — | Branch fully off; measures what the branch does at shipped VAD |
| B1 | `q07-hst-2-ms2000` | `2.0`, `2000` | — | Control for the B row; isolates the VAD change |
| B2 | `q07-hst-1-ms2000` | `1.0`, `2000` | — | Joint cell; attributable only against B1 |
| B3 | `q07-hst-none-ms2000` | `null`, `2000` | — | Branch off with more retained silence |
| D1 | `q07-novad-hst-2` | `2.0`, `500` | `asr.vad_filter = false` | **Diagnostic, not a candidate** |
| D2 | `q07-novad-hst-none` | `null`, `500` | `asr.vad_filter = false` | **Diagnostic, not a candidate** |

**Why these eight.** The `{None, 1.0, 2.0} × {500, 2000}` factorial is the
smallest design that separates three confounded questions: does the branch fire
at all (the `{None, 2.0}` differ-count within a row), does lowering the
threshold change anything the branch already reaches (`1.0` against `2.0`
within a row), and is any observed win the threshold's or the VAD's (row B
against row A, and B2 against B1). Dropping the `2.0` cells would leave every
delta confounded with the VAD change; dropping row B would leave a null result
uninterpretable, because §2 predicts row A cannot fire. The `vad_filter = false`
pair is the positive control: it is the only configuration in which §2's
mechanism *must* show up, so if `{None, 2.0}` are identical there too, the
finding is about `is_segment_anomaly`, not about silence — a materially
different conclusion, and one worth two runs.

**Only `hallucination_silence_seconds` is a Q07 merge candidate.**
`vad_min_silence_duration_ms` is Q02's key and `asr.vad_filter` is user config
whose default `true` is fixed by `AGENTS.md` hard rule 5 (the VAD pre-filter is
named as part of the anti-hallucination stack). Rows B and D exist to make the
threshold's effect *measurable*, never to ship. See §6's attribution rule and
§9.

Variant JSON files, checked in by the executing agent before step 1, under
`docs/experiments/variants/Q07/`. A1 in full; the rest differ only in `name`
and the two named fields (and, for D1/D2, the `config` block):

```json
{
  "schema": 1,
  "name": "q07-hst-2-ms500",
  "plan": "Q07",
  "lanes": ["tail"],
  "tags_any": [],
  "tags_all": [],
  "engine": "auto",
  "repeats": 1,
  "config": {},
  "decode": {
    "hallucination_silence_seconds": 2.0,
    "vad_min_silence_duration_ms": 500,
    "word_timestamps": true
  }
}
```

D1/D2 additionally carry `"config": {"asr": {"vad_filter": false}}`. Files:
`q07-hst-2-ms500.json`, `q07-hst-1-ms500.json`, `q07-hst-none-ms500.json`,
`q07-hst-2-ms2000.json`, `q07-hst-1-ms2000.json`, `q07-hst-none-ms2000.json`,
`q07-novad-hst-2.json`, `q07-novad-hst-none.json`. A conditional ninth,
`q07-hst-05-ms2000.json` (`0.5`, `2000`), is written but run only under §5
step 7's condition.

## 5 Procedure

Every command runs from the repository root with the repo venv. No step needs a
human. Exit codes: `0` accept, `1` deny, `2` harness error (HARNESS.md §6.3).
**Any `2` aborts the plan** — record the failing command and stop; a harness
error is never a deny.

**Step 0 — reconcile the CLI and gate decidability.**

```sh
.venv/bin/python scripts/asr_experiment.py run --help
```

`HARNESS.md` §1 fixes the CLI surface, `--variant <path>` included, so that is
what this plan writes throughout.

The snippets below are the **fallback** form of this plan's guards: anything one
of them checks that is an ordinary aggregate belongs in `thresholds.json`'s
`guards` array, which is the canonical mechanism (`HARNESS.md` §6.1). They stay
because this plan must remain runnable if the foundation commit has not landed
`guards`, and because some of them compute figures no single guard row carries.

```sh
.venv/bin/python - <<'PY'
import json, math, pathlib
b = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
B = b["aggregates"]["per_lane"]["tail"]["trailing_junk_rate"]
N = b["noise"]["trailing_junk_rate"]
Nw = b["noise"]["wer_mean"]
M = max(0.03, math.ceil(2 * N * 100) / 100)
print(f"tail_trailing_junk_rate={B:.4f} noise_tjr={N:.4f} noise_wer={Nw:.4f} required_margin={M:.2f}")
print("DECIDABLE" if B >= M else "NOT_DECIDABLE")
PY
```

- `required_margin` above `0.03` ⇒ edit `target.margin` in
  `docs/experiments/variants/Q07/thresholds.json` to that value before step 1
  and record the edit in the Outcome section. HARNESS.md §7.1 requires a margin
  of at least twice the target metric's recorded noise, and `validate_variant`
  enforces it.
- `NOT_DECIDABLE` ⇒ the `tail` lane does not carry enough trailing junk for a
  `required_margin` improvement to exist. **Stop here**, run nothing, set
  Status to denied, and write the Outcome as *not decidable* with `B`, `N` and
  `M`. This is a legitimate finding about Q09's lane, and it saves ~40 minutes.
- Set `wer` target margin in `thresholds-wer.json` to
  `max(0.004, ceil(2 * noise_wer * 1000) / 1000)` by the same rule.

**Step 1 — preflight.**

```sh
.venv/bin/python scripts/asr_experiment.py preflight
```

Exit 0 required. It verifies the venv, the cached model, the manifest digests
for the `tail` lane, the CUDA device, the resolved compute type, git state and
free disk (HARNESS.md §8.2).

**Step 2 — the control, and the cross-engine sanity gate.**

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q07/q07-hst-2-ms500.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q07/thresholds.json
```

A1 reproduces the shipped decode in-process, so exit `1` (deny, target delta
≈ 0) is the expected and correct outcome — it is a control, not a candidate.
Then gate on agreement with the subprocess baseline:

```sh
.venv/bin/python - q07-hst-2-ms500 <<'PY'
import json, pathlib, sys
run = sorted(pathlib.Path("build/asr-experiments").glob(f"*-{sys.argv[1]}"))[-1]
r = json.loads((run / "result.json").read_text())["aggregates"]["per_lane"]["tail"]
b = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
base, noise = b["aggregates"]["per_lane"]["tail"], b["noise"]
for k in ("trailing_junk_rate", "wer_mean"):
    d = abs(r[k] - base[k])
    print(f"{k} run={r[k]:.4f} baseline={base[k]:.4f} delta={d:.4f} allowed={2*noise[k]:.4f} "
          f"{'OK' if d <= 2 * noise[k] else 'MISMATCH'}")
PY
```

Any `MISMATCH` ⇒ the in-process engine does not reproduce the shipped decode
and every later comparison in this plan is void. **Abort**, report it as a
harness defect against HARNESS.md §3.1, and change nothing under `src/`.

**Step 3 — the remaining seven runs**, in matrix order, each exit code
recorded and none of them a reason to stop (only `2` stops the plan):

```sh
for v in q07-hst-1-ms500 q07-hst-2-ms2000 q07-hst-1-ms2000 q07-novad-hst-2; do
  .venv/bin/python scripts/asr_experiment.py run \
    --variant "docs/experiments/variants/Q07/$v.json" \
    --baseline docs/experiments/baseline.json \
    --thresholds docs/experiments/variants/Q07/thresholds.json
  echo "$v exit=$?"
done
for v in q07-hst-none-ms500 q07-hst-none-ms2000 q07-novad-hst-none; do
  .venv/bin/python scripts/asr_experiment.py run \
    --variant "docs/experiments/variants/Q07/$v.json" \
    --baseline docs/experiments/baseline.json \
    --thresholds docs/experiments/variants/Q07/thresholds-wer.json
  echo "$v exit=$?"
done
```

The `hst = null` variants are scored against the WER target: disabling a branch
can only *add* text, so `trailing_junk_rate(None) ≥ trailing_junk_rate(2.0)` by
construction and the junk target is unreachable for them. Their accept path is
"the branch only ever deleted real speech" (§6).

**Step 4 — the differ-count (the deadness evidence).** Counts only; the
snippet reads `clips.jsonl` under `build/` and prints no text.

```sh
.venv/bin/python - <<'PY'
import json, pathlib
root = pathlib.Path("build/asr-experiments")
def load(name):
    d = sorted(root.glob(f"*-{name}"))[-1]
    return {r["clip_id"]: r for r in map(json.loads, (d / "clips.jsonl").open())}
pairs = [("q07-hst-2-ms500", "q07-hst-none-ms500"), ("q07-hst-2-ms500", "q07-hst-1-ms500"),
         ("q07-hst-2-ms2000", "q07-hst-none-ms2000"), ("q07-hst-2-ms2000", "q07-hst-1-ms2000"),
         ("q07-novad-hst-2", "q07-novad-hst-none")]
for a, b in pairs:
    A, B = load(a), load(b)
    ids = sorted(set(A) & set(B))
    diff = [i for i in ids if A[i]["hypothesis_norm"] != B[i]["hypothesis_norm"]]
    by_tag = {}
    for i in diff:
        for t in A[i]["tags"]:
            if t.startswith("tail="):
                by_tag[t] = by_tag.get(t, 0) + 1
    print(f"pair={a}|{b} clips={len(ids)} differ={len(diff)} " +
          " ".join(f"{t}={by_tag.get(t, 0)}" for t in ("tail=1s", "tail=3s", "tail=5s")))
PY
```

**Step 5 — attribution.** For every variant that exited `0`, check it against
its own row control before crediting it to Q07:

```sh
.venv/bin/python - <<'PY'
import json, pathlib
root = pathlib.Path("build/asr-experiments")
def tjr(name):
    d = sorted(root.glob(f"*-{name}"))[-1]
    return json.loads((d / "result.json").read_text())["aggregates"]["per_lane"]["tail"]["trailing_junk_rate"]
margin = json.loads(pathlib.Path("docs/experiments/variants/Q07/thresholds.json").read_text())["target"]["margin"]
for cand, ctrl in [("q07-hst-1-ms500", "q07-hst-2-ms500"), ("q07-hst-1-ms2000", "q07-hst-2-ms2000")]:
    d = tjr(ctrl) - tjr(cand)
    print(f"{cand} vs {ctrl}: paired_delta={d:.4f} margin={margin:.4f} "
          f"{'ATTRIBUTED_TO_HST' if d >= margin else 'NOT_ATTRIBUTED'}")
PY
```

**Step 6 — the decision** per §6, then the write-up per §9.

**Step 7 — the conditional ninth run.** If and only if `q07-hst-1-ms2000`
reported `differ ≥ 10` in step 4 *and* its paired delta in step 5 was at least
half the margin but under it, run `q07-hst-05-ms2000.json` against
`thresholds.json` and re-apply steps 4-6 to it (paired against
`q07-hst-2-ms2000`). Otherwise skip it: without movement at `1.0`, `0.5` has
no mechanism to exploit, and §2's correction 2 says it narrows two clauses
further.

**Step 8 — confirmation before any merge** (only when §6 selects a winner).
Run the winning variant on the lanes it was not measured on, with a copy of its
JSON whose `lanes` is `["base", "cue"]` and file name suffix `-confirm`, and no
`--baseline` (a report-only run):

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q07/<winner>-confirm.json
```

Then require, from that `result.json` against `baseline.json`'s matching
per-lane aggregates: `wer_mean` no worse than `+0.002` on either lane,
`leading_word_recall_mean` no lower than `baseline − 0.005` on either lane, and
no clip empty that was non-empty in the baseline. A failure here blocks the
merge and is recorded in the Outcome; the variant is reported as accepted on
`tail` but rejected on confirmation.

## 6 Metrics & accept/deny

**Primary target** — `trailing_junk_rate`, direction `lower`, margin `0.03`
absolute (raised by step 0 to `ceil(2 × noise, 0.01)` when the recorded noise
demands it), over `lanes: ["tail"]`, `min_clips: 300`.

`docs/experiments/variants/Q07/thresholds.json`:

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
  "lanes": ["tail"],
  "min_clips": 300
}
```

**Secondary target** — the "disable it" path, for the `hst = null` variants
only. `docs/experiments/variants/Q07/thresholds-wer.json` is the same file with

```json
  "target": {"metric": "wer_mean", "direction": "lower", "margin": 0.004, "margin_kind": "absolute"}
```

(`0.004` raised by step 0 to `ceil(2 × noise_wer, 0.001)` when larger). Because
`decide` evaluates one target, the junk side of that path is checked
numerically from step 4/5's outputs: a `null` variant only counts as accepted
when its `trailing_junk_rate` on `tail` also rises by no more than
`noise.trailing_junk_rate` over `q07-hst-2-ms500`.

**Why the `tail` lane alone carries the verdict.** Its clips are the `base`
clips plus room tone and carry the same references, so deletions of real speech
— the branch's real risk — surface in the same run's `wer_mean`,
`deletion_rate` and `leading_word_recall_mean`. `base` and `cue` are covered by
step 8's confirmation run rather than by diluting a 300-clip target metric with
100 clips that carry no tail.

**Selection when more than one variant accepts.** Best accepted by target
metric, not first in matrix order: among variants that both exit `0` **and**
pass step 5's attribution, take the lowest `per_lane.tail.trailing_junk_rate`;
tie-break by lower `wer_mean`, then by fewer changed literals, then by matrix
order. A variant whose paired delta is `NOT_ATTRIBUTED` is never selected — its
win belongs to the VAD change and is handed to Q02 (§9).

**A row-B-only winner does not merge from here.** If the only attributed win
needs `vad_min_silence_duration_ms = 2000`, Q07's outcome is a joint
recommendation to Q02, and Q07 is re-run against the re-baselined defaults
after Q02 lands. Q07 may edit exactly one literal on its own authority:
`_HALLUCINATION_SILENCE_SECONDS`.

**Diagnostics D1/D2 have no verdict.** Their exit codes are recorded and
ignored; `vad_filter = false` is not a shippable default (§8). Expect them to
deny, quite possibly on clip errors (see §8's word-density confound).

**What a deny looks like, and why it is still the deliverable.** The evidence
that the branch is effectively dead at the shipped settings is step 4's first
pair: `q07-hst-2-ms500` against `q07-hst-none-ms500` with `differ = 0` of 300
means the option changed no decode at all — turning it off entirely is
indistinguishable from leaving it at `2.0`. Read together with the other four
pairs, the differ-counts form the finding:

| Observation | Conclusion reported |
|---|---|
| Row A pairs differ = 0, D pair differs > 0 | The branch works; the shipped VAD starves it of the silence it needs. `2.0` is dead code at the shipped settings. |
| Row A differ = 0, row B differs > 0, D differs > 0 | As above, and quantified: retained silence is the controlling variable, `min_silence` is the lever, and the threshold is only useful jointly (hand to Q02). |
| Every pair differs = 0, D included | The blocker is `is_segment_anomaly` (transcribe.py:1254-1260), not silence: this corpus's hallucinations are fluent and high-probability. Q05/Q11 own the symptom; recommend removing the option as dead configuration. |
| Row A differs > 0 but under the margin | The branch fires and is measurable at shipped settings; the margin, not the mechanism, was the obstacle. Report the effect size for a future re-run against a lane with more junk. |

## 7 Cost estimate

From HARNESS.md §8.4: in-process ≈ 0.7 s per clip after one model load; the
`tail` lane is 300 clips; `repeats: 1`.

| Item | Arithmetic | Time |
|---|---|---|
| 8 variants × 300 clips × 0.7 s | 2400 × 0.7 s = 1680 s | 28 min |
| 8 in-process model loads | 8 × ≈2.5 s | ≈0.3 min |
| D1/D2 decode un-stripped audio (+1/3/5 s per clip, some `long` clips crossing into a second 30 s window) — allow ×1.5 | 2 × 300 × 0.7 s × 0.5 | ≈3.5 min |
| B1-B3 retain more internal silence — allow ×1.1 | 3 × 300 × 0.7 s × 0.1 | ≈1 min |
| preflight (one cold load + digest check over 300 WAVs) | — | ≈1 min |
| **Total, eight variants** | | **≈34 min; budget 45 min** |
| Conditional ninth run (step 7) | 300 × 0.7 s | +3.5 min |
| Confirmation run (step 8, `base` + `cue` = 400 clips) | 400 × 0.7 s | +5 min |

Disk: the corpus already exists; each run directory is a few MB (a 300-line
`clips.jsonl` with three text fields plus `result.json`/`report.md`/
`verdict.json`), so ≤ 50 MB for eight runs. HARNESS.md §8.2's 1 GiB free-space
preflight covers it.

## 8 Risks, confounds, invariants

**The change can delete real speech.** Both branches remove decoded content:
Branch A rewinds `seek` past a gap (transcribe.py:1302) and Branch B truncates
`current_segments[si:]` (1337). A short, quiet or clipped real first word can
score anomalous under `word_anomaly_score` (1242-1252) — exactly the corpus's
`leading_word_recall` failure mode — and a lower threshold widens both gap
tests, so `hst = 1.0` can silently drop genuine speech. Guards:
`wer_mean_max_delta = 0.002` and `forbid_empty_regressions` in every thresholds
file, `leading_word_recall_mean` reported per aggregate and enforced in step
8's confirmation run against `base` and `cue`. The `tail` clips carry the same
speech as `base`, so the guard is not deferred to step 8 alone.

**Lowering the threshold is not monotone.** §2, correction 2: `1.0` narrows
`start < threshold` (1322) and the end-jump `content_duration - end < threshold`
(1335), so `trailing_junk_rate` may *rise*. A candidate that increases the
target metric denies on direction; that is the correct result and is reported,
not retried at another value.

**`vad_filter = false` is a diagnostic, never a candidate default.**
`AGENTS.md` hard rule 5 (AGENTS.md:229-231) names the VAD pre-filter as part of
the fixed anti-hallucination stack, and `asr.vad_filter` defaults to `true`
(`src/stenographer/config.py:258`). The VAD does real work: it is what keeps
the decoder off long silences in the first place, and Q02 — not Q07 — owns any
change to it. D1/D2 exist purely to prove the mechanism in isolation.

**Word-density confound in D1/D2.** `_validate_output`'s limit is
`max(12, ceil(8 × vad_seconds))` (`model.py:200`) and `vad_seconds` comes from
`duration_after_vad` (`model.py:139`); with the VAD off it becomes the full
clip, so the diagnostics get a *larger* runaway budget and a different
`PathologicalOutputError` rate. An in-process `PathologicalOutputError` is
recorded as a clip error, and HARNESS.md §6.2 rule 5 denies any run with a new
clip error — one more reason the diagnostics' verdicts are ignored. Their
differ-counts and aggregates remain valid.

**`min_silence_duration_ms` overlaps Q02.** Row B moves a key Q02 grids. The
paired attribution in step 5 is what separates the threshold's contribution
from the VAD's; without it, a row-B accept would be uninterpretable. A row-B
win is handed to Q02 rather than merged here (§6, §9).

**Cross-engine comparison.** All eight variants run in-process against a
subprocess baseline. HARNESS.md §3.1 makes text metrics and `decode_ms`
comparable across engines, and §6.4 only refuses mixed engines for a *speed*
target; `trailing_junk_rate` and `wer_mean` are not. Step 2's sanity gate is
the empirical check on that assumption, and it aborts the plan rather than
absorbing a discrepancy into a verdict.

**Stratum dependence.** `window_end_time` is `time_offset + 30 s`
(transcribe.py:1169-1172), so the `long` stratum with the VAD off is the only
place a second window — and the `window_end_time - end < 2.0` clause — becomes
live. Step 4's per-tag breakdown plus the manifest's `short`/`medium`/`long`
tags make that visible; do not generalise a `long`-only effect to dictation
without saying so.

**Determinism.** `temperature = (0.0,)` everywhere, so HARNESS.md §8.3 applies:
greedy decoding on a fixed model/compute type/GPU is deterministic, `repeats:
1`, no seeding needed. `condition_on_previous_text = False` (`model.py:121`)
means the one `Model` per variant cannot carry state between clips, so the
byte-identity test in step 4 is sound.

**Invariant checklist (HARNESS.md §9), restated for this plan.**

- *No transcript text.* Text stays in `build/asr-experiments/*/clips.jsonl`.
  Step 4's snippet compares `hypothesis_norm` and prints counts only; the
  Outcome section, `result.json`, `report.md`, `verdict.json`, everything under
  `docs/experiments/variants/Q07/` and this file carry numbers only.
- *No network in the ASR path.* Nothing here fetches: the corpus already
  exists, `local_files_only=True` stands (`model.py:87`), the in-process engine
  never leaves the venv.
- *No platform imports.* This plan adds no code; the harness's own isolation
  grep in `tests/platform/test_core_isolation.py` covers the scripts.
- *Test policy.* No new mocks. The only code an accept touches is a literal and
  its pinning test (§9).
- *Fixed behaviour stays fixed.* No variant is reachable from user config; the
  23-key surface is untouched; `DecodeOptions()` defaults change only through
  §9's merge, together with their pinning test.
- *Venv only*, SPDX headers, ruff clean at line length 100 for anything the
  merge touches.

## 9 Deliverables & follow-through

**On accept** (§6 selected a winner, step 5 attributed it, step 8 confirmed
it):

1. `src/stenographer/transcribe/model.py:27` —
   `_HALLUCINATION_SILENCE_SECONDS = 2.0` becomes the winning value. If the
   winner is `None`, set the constant to `None` and keep passing it explicitly
   at `model.py:119` with a one-line comment naming Q07, so the library default
   remains a visible decision rather than an omission.
2. `DecodeOptions.hallucination_silence_seconds` (HARNESS.md §3.2's dataclass
   in `model.py`) — its default must keep tracking the literal.
3. `tests/transcribe/test_model.py` — the `dataclasses.asdict(DecodeOptions())`
   pinning test's literal dict (HARNESS.md §3.2). Nothing else in the suite
   references the constant today (`grep -rn "hallucination" tests/ src/` hits
   only `model.py`), so this is the sole test edit; add no new unit test that
   merely restates the literal — `AGENTS.md` hard rule 4 forbids that kind of
   coverage.
4. `AGENTS.md:229-231` — the sentence naming the fixed anti-hallucination stack
   ("VAD pre-filter, no-speech gate, silence trimming, short-audio token
   ceiling, output validation"). A value change adds a clause recording that
   Q07 set it and the run id; an accepted `None` removes "silence trimming"
   from that list, because the stack no longer contains it. Same commit as the
   code, per `AGENTS.md`'s preamble.
5. Re-baseline per HARNESS.md §7.3 case 1 after the merge to `dev`, with the
   reason in the commit message; the re-baseline commit touches
   `docs/experiments/baseline.json` only.
6. `AGENTS.md` acceptance gates before dev → main, on a real machine:
   `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest` green, and real dictation
   end-to-end in `hold`, `toggle` and `hybrid`. A decode change that can drop
   leading words also re-runs the capture gate — "a cold-start dictation
   retains its opening words, and an inspection of `stenographer.log` plus the
   journal shows metrics but no transcript or audio content".
7. Set this file's Status to `accepted (<date>)` and append an Outcome section
   with the winning variant name, its run id, the verdict line, the paired
   attribution delta, and step 8's confirmation numbers.

**On a row-B-only win**: merge nothing. Append the Outcome, set Status to
`denied`, and open the finding against Q02 — "`hst` becomes live at
`min_silence_duration_ms = 2000`; re-run Q07 after any accepted Q02 change" —
with the paired numbers.

**On deny** (including the *not decidable* stop at step 0), per HARNESS.md §10:
append an Outcome section carrying every variant's verdict line and run id, the
five differ-counts from step 4 with their per-tag breakdown, the two paired
deltas from step 5, and the row of §6's evidence table the result matches; copy
each `verdict.json` to
`docs/experiments/results/Q07-<run-id>.json`; set Status to `denied (<date>)`.
Numbers only.

**On the "every pair identical, D included" outcome**, add one recommendation
to the Outcome: `hallucination_silence_threshold` is inert for this workload
and `_HALLUCINATION_SILENCE_SECONDS` is a candidate for deletion as dead
configuration — a separate change, requiring its own `AGENTS.md` edit, not made
by this plan.

## 10 Out of scope

- **`hst = 0.5`.** `docs/experiments/README.md`'s index lists it; this plan
  demotes it to step 7's conditional run because it is only interesting once
  `1.0` shows movement, and §2's correction 2 says it narrows two clauses
  further. The variant JSON ships ready.
- **The leading rewind (Branch A) as a first-word-loss cause.** The `cue` lane
  and leading silence belong to Q10, and the VAD parameters that control
  leading audio belong to Q02. This plan only guards against making leading
  recall worse.
- **Any VAD default change.** Q02 owns `vad_threshold`,
  `min_silence_duration_ms` and `speech_pad_ms`; Q07's row B is instrumentation,
  not a proposal.
- **`asr.vad_filter` as a shipped default.** Fixed by `AGENTS.md` hard rule 5.
- **Other routes to the same symptom**: the temperature fallback ladder and
  `compression_ratio_threshold` (Q01), `repetition_penalty` /
  `no_repeat_ngram_size` (Q05), a pure post-decode terminal-n-gram filter
  (Q11), the `_assemble` no-speech gate (Q06). If Q07 lands in the "it is
  `is_segment_anomaly`, not silence" cell of §6's table, Q05 and Q11 are the
  successors.
- **How much trailing junk the `tail` lane carries at all**, and its dependence
  on appended duration: that is Q09's characterisation, consumed here as the
  baseline's `per_lane.tail` numbers.
- **Speed.** `rtf_p95` is a guard only; `decode_ms` differences from retained
  silence are not this plan's subject (S-series, subprocess engine).
