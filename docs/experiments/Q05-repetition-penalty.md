# Q05 — repetition penalty × no-repeat n-gram size

Status: planned (2026-08-29)

Baseline for every `file:line` citation: `dev` @ `a1b9807` (v0.11.6),
faster-whisper 1.2.1, CTranslate2 4.8.1, Python 3.14.7 in the repo venv —
verified in this venv, not assumed.

## 1 Hypothesis

A mild `repetition_penalty` (1.05–1.2) and/or a different `no_repeat_ngram_size`
(0 / 3 / 5) reduces `trailing_junk_rate` by ≥ 50 % relative on the `base + tail`
lanes without moving `wer_mean` by more than +0.002, `rtf_p95` by more than
×1.25, the corpus `deletion_rate` by more than +0.003, or the `deletion_rate`
restricted to repeat-bearing references by more than +0.005.

## 2 Symptom & mechanism

**Symptom.** `docs/experiments/README.md`, owner report (2): some utterances end
in hallucinated loops — a repeated short phrase, or a single stock closer,
appended after the speech has ended. `HARNESS.md` §5.5 turns exactly this into
`trailing_junk`: (a) ≥ 2 hypothesis words after the last aligned reference word,
or (b) a terminal 1/2/3-gram repeated three times that the reference does not
itself repeat.

**Today's call.** `src/stenographer/transcribe/model.py:110-125` passes
`no_repeat_ngram_size=3`, `temperature=0.0` (scalar), `beam_size=cfg.beam_size`
(default `1`, `src/stenographer/config.py:255`), `condition_on_previous_text=False`,
`word_timestamps=True`. `repetition_penalty` is never passed, so it takes the
library default `1` (`faster_whisper/transcribe.py:757`), i.e. inert.

**Where the two knobs act.** `WhisperModel.transcribe` copies both into
`TranscriptionOptions` (`transcribe.py:975-976`, fields at `transcribe.py:76-77`)
and `generate_with_fallback` forwards them verbatim to the CTranslate2 decoder
(`transcribe.py:1446-1457`: `self.model.generate(..., repetition_penalty=…,
no_repeat_ngram_size=…)`). Confirmed against
`ctranslate2.models.Whisper.generate`'s own signature in this venv
(`repetition_penalty: float = 1`, `no_repeat_ngram_size: int = 0`). CT2 applies
the penalty to the score of tokens already present in the decoding history and
blocks any n-gram of the given size that would repeat inside the *same generated
sequence*.

**Why `no_repeat_ngram_size=3` is not already enough.** Three structural facts,
each read out of the library in this venv:

1. **Scope is one 30 s window, not the utterance.** `generate_segments` loops
   over seek windows and calls `generate_with_fallback` once per window
   (`transcribe.py:1213`). Each call is a fresh CT2 sequence, so nothing blocks a
   phrase in window *n+1* that also occurred in window *n*. With
   `condition_on_previous_text=False` the prompt is reset after every window
   (`transcribe.py:1372-1383`), so there is not even a prompt-side trace of the
   earlier text. `audio.max_recording_seconds` defaults to `600`
   (`config.py:250`), so multi-window utterances are ordinary.
2. **Timestamp tokens sit between segments.** `word_timestamps=True` keeps
   timestamps in the generated sequence, so a phrase recurring across a segment
   boundary is separated by timestamp tokens and never forms the same literal
   3-gram; only a loop contiguous *within* one segment is blocked.
3. **It cannot touch a one-shot closer.** A single appended stock phrase repeats
   no n-gram at all; `no_repeat_ngram_size` is silent on it by construction, and
   `HARNESS.md` §5.5 branch (a) still flags it.

`repetition_penalty > 1` attacks a different surface: it discourages *any*
already-seen token, so a loop is dampened as soon as its first repetition
starts, within a window and regardless of intervening timestamp tokens. The
price is that it also discourages legitimately repeated tokens — function words
("the", "and", "of") in long sentences most of all — which shows up as
**deletions**, not as insertions. That is what §6's deletion guards exist to
catch.

**Downstream couplings the change can disturb.** The penalty applies to
timestamp tokens too, so segment/word boundaries can shift. Those timestamps
feed `hallucination_silence_threshold` (`model.py:119`, consumed at
`transcribe.py:1294-1320`) and `_validate_output`'s timestamp sanity and word
density ceiling (`model.py:178-205`), whose `PathologicalOutputError` discards a
whole utterance. So a variant can change the *error* population, not only the
text — §8 says how that is detected.

## 3 Prerequisites

- **Harness pieces** (`HARNESS.md` §1): `scripts/asr_corpus.py` (corpus fetched,
  `base` and `tail` lanes generated), `scripts/asr_metrics.py` (`normalize`,
  `wer`, `trailing_junk`, `aggregate`, `decide`), `scripts/asr_experiment.py`
  with `preflight` and `run --baseline … --thresholds …`, all passing their pure
  tests.
- **Injection fields** (`HARNESS.md` §3.2, `DecodeOptions`): exactly two —
  `repetition_penalty: float` and `no_repeat_ngram_size: int`. Every other field
  stays at its default; in particular `temperature` stays `(0.0,)` and
  `word_timestamps` stays `True`. No `config` overrides at all (`"config": {}`),
  so `asr.model`, `asr.compute_type`, `asr.beam_size`, `asr.vad_filter`,
  `asr.silence_threshold`, `asr.hotwords` and `asr.initial_prompt` are the
  shipped defaults.
- **Engine**: `inprocess`, mandatory — both fields are `decode`-lane, and
  `HARNESS.md` §3 makes a non-empty `decode` with `engine: "subprocess"` a
  harness error.
- **Corpus lanes/tags**: `base` (100 clips) and `tail` (300 clips: 1 s / 3 s /
  5 s of −60 dBFS room tone appended). The `tail` lane is produced and
  characterised by **Q09** — this plan does not build it and must not run before
  Q09's lane exists in `build/asr-corpus/manifest.json`. No tag filters
  (`tags_any: []`, `tags_all: []`).
- **Baseline**: `docs/experiments/baseline.json` present, with a `noise` block
  carrying `trailing_junk_rate` and `wer_mean` (`HARNESS.md` §7.1), and still
  describing the shipped defaults — `git diff --quiet <baseline git_commit> HEAD
  -- src/ pyproject.toml` exits `0` (§5 step 0). It is a **content** check, not a
  HEAD-equality check: an unrelated commit to `docs/` or `tests/` must not
  invalidate a baseline that still describes the decode stack exactly.
- **Ordering vs. Q01**: `HARNESS.md` §7.3 case 1 — if Q01 (or any other plan) is
  accepted and merged, the shipped defaults have moved and the baseline is
  re-established; every Q05 cell must then be re-run against the new baseline.
  Q05 never compares a run against a baseline written against different shipped
  code.

## 4 Variant matrix

Full 4 × 3 grid, 12 cells. Every variant: `"schema": 1`, `"plan": "Q05"`,
`"lanes": ["base", "tail"]`, `"tags_any": []`, `"tags_all": []`,
`"engine": "inprocess"`, `"repeats": 1`, `"config": {}`. `repeats` is `1`
because `temperature` stays `(0.0,)`: `HARNESS.md` §8.3 requires 3 repeats only
when a temperature above zero is in play, and greedy decoding at T=0 on a fixed
model/compute type/GPU is deterministic — the baseline's `noise` block is the
measured proof. Re-running a cell therefore adds no information; if a cell must
be re-run for an operational reason, its numbers must match bit-for-bit, and a
mismatch is a harness error (exit 2), not noise.

| # | Variant name | `repetition_penalty` | `no_repeat_ngram_size` | Role | Path |
|---|---|---|---|---|---|
| 1 | `q05-rp100-ng3` | 1.0 | 3 | **Control** — shipped literals, in-process | `docs/experiments/variants/Q05/q05-rp100-ng3.json` |
| 2 | `q05-rp100-ng0` | 1.0 | 0 | ngram blocking off (does it do anything today?) | `…/q05-rp100-ng0.json` |
| 3 | `q05-rp100-ng5` | 1.0 | 5 | wider ngram block | `…/q05-rp100-ng5.json` |
| 4 | `q05-rp105-ng0` | 1.05 | 0 | penalty alone, mild | `…/q05-rp105-ng0.json` |
| 5 | `q05-rp105-ng3` | 1.05 | 3 | penalty + shipped ngram | `…/q05-rp105-ng3.json` |
| 6 | `q05-rp105-ng5` | 1.05 | 5 | | `…/q05-rp105-ng5.json` |
| 7 | `q05-rp110-ng0` | 1.1 | 0 | | `…/q05-rp110-ng0.json` |
| 8 | `q05-rp110-ng3` | 1.1 | 3 | | `…/q05-rp110-ng3.json` |
| 9 | `q05-rp110-ng5` | 1.1 | 5 | | `…/q05-rp110-ng5.json` |
| 10 | `q05-rp120-ng0` | 1.2 | 0 | penalty ceiling; deletion risk highest | `…/q05-rp120-ng0.json` |
| 11 | `q05-rp120-ng3` | 1.2 | 3 | | `…/q05-rp120-ng3.json` |
| 12 | `q05-rp120-ng5` | 1.2 | 5 | | `…/q05-rp120-ng5.json` |

Names match `[a-z0-9-]{1,40}` (`HARNESS.md` §1); the penalty is encoded ×100
because a `.` is not allowed in a run id.

Cell 1 is not a duplicate of the baseline: the baseline was run with the
**subprocess** engine (`HARNESS.md` §7.1) and cell 1 runs the same literals
in-process. It is the engine-parity control, and §5 step 3 stops the plan if it
does not reproduce the baseline's text aggregates.

Variant file, cell 5, verbatim (every other cell differs only in `name` and the
two `decode` values):

```json
{
  "schema": 1,
  "name": "q05-rp105-ng3",
  "plan": "Q05",
  "lanes": ["base", "tail"],
  "tags_any": [],
  "tags_all": [],
  "engine": "inprocess",
  "repeats": 1,
  "config": {},
  "decode": {"repetition_penalty": 1.05, "no_repeat_ngram_size": 3}
}
```

**Reduced design (fallback, only if wall clock is constrained).** Stage A: cells
1, 5, 8, 11 (penalty sweep at the shipped `no_repeat_ngram_size = 3`). Selection
rule for stage A, mechanical: take the accepted cell with the lowest
`trailing_junk_rate`; ties by lower `wer_mean`, then by lower
`repetition_penalty`. If no cell in stage A is accepted, take the cell with the
lowest `trailing_junk_rate` that passes every guard in §6 except the target
margin, and call it `P`; if even that does not exist, stop and record the plan
denied. Stage B: run the two remaining `no_repeat_ngram_size` values (0 and 5)
at `P`'s penalty — 2 cells. Total 6 cells (≈ 30 min). The staged design cannot
see a penalty × ngram interaction, which is the reason it is the fallback and
not the plan.

## 5 Procedure

Every command runs from the repository root with the repo venv. No step needs a
human. `<variant>` is a path from §4; the loop runs the 12 cells **in matrix
order**.

**Step 0 — plan preconditions (stop on failure).**

```sh
.venv/bin/python - <<'PY'
import json, pathlib, subprocess, sys
b = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
base_commit = b["environment"]["git_commit"]
ok = True
# Content check, not HEAD equality: the baseline is stale only if the shipped
# code it measured has moved.
if subprocess.run(["git", "diff", "--quiet", base_commit, "HEAD", "--",
                   "src/", "pyproject.toml"]).returncode != 0:
    print(f"FAIL shipped code moved since baseline_commit={base_commit}"); ok = False
if b["variant"]["decode"] != {} or b["variant"]["config"] != {}:
    print("FAIL baseline is not the shipped-defaults variant"); ok = False
if "tail" not in b["aggregates"]["per_lane"]:
    print("FAIL baseline has no tail lane; run Q09 first"); ok = False
noise = b.get("noise", {})
for k in ("trailing_junk_rate", "wer_mean"):
    if k not in noise:
        print(f"FAIL baseline noise missing {k}"); ok = False
lanes = ("base", "tail")
rows = [r for r in b["clip_scores"] if r["lane"] in lanes and r.get("trailing_junk") is not None]
rate = sum(1 for r in rows if r["trailing_junk"]) / len(rows) if rows else 0.0
print(f"baseline_trailing_junk_rate_base_tail={rate:.4f} clips={len(rows)} "
      f"noise_junk={noise.get('trailing_junk_rate')}")
if rate < 0.02:
    print("FAIL symptom not reproduced on this corpus (rate < 0.02)"); ok = False
if rate * 0.5 < 2 * float(noise.get("trailing_junk_rate", 0.0)):
    print("FAIL relative margin 0.5 is below 2x baseline noise; corpus underpowered"); ok = False
sys.exit(0 if ok else 1)
PY
```

Exit `0` → continue. Exit `1` → **do not run any cell**. Set `Status: abandoned`
in this file with an `Outcome` section recording the printed numbers and which
line failed; a moved-shipped-code failure means re-baselining per `HARNESS.md` §7.3
and re-running this plan from step 0, a `rate < 0.02` or underpowered-margin
failure means the `tail` lane cannot measure this effect and the finding belongs
to Q09 (a longer/louder tail lane) before Q05 is retried.

**Step 1 — preflight.**

```sh
.venv/bin/python scripts/asr_experiment.py preflight
```

Exit `0` → continue. Exit `2` → harness error: record the message, stop. Never
work around a preflight failure (a missing model means
`.venv/bin/stenographer model download`, which is the owner's call, not this
plan's).

**Step 2 — write the check script** (gitignored working file; it is never
committed and prints numbers only, never text).

`HARNESS.md` §6.1's `guards` array is the **canonical** mechanism for everything
this script checks, and a guard row belongs in `thresholds.json` wherever the
metric is an ordinary aggregate. `q05-check.py` is the **fallback**: it exists
because this plan's guards are computed over clip *subsets* (reference-bearing
clips, the `long` stratum) that no aggregate key names, and because the plan must
still run if the foundation commit has not landed `guards` yet. Anything it checks
that `guards` can express should move there on the next pass.

```sh
mkdir -p build/asr-experiments
cat > build/asr-experiments/q05-check.py <<'PY'
# Q05 secondary guards: deletions, per-lane junk, error population.
# Usage: .venv/bin/python build/asr-experiments/q05-check.py <run>/result.json
import json, pathlib, sys
sys.path.insert(0, "scripts")
from asr_metrics import normalize

LANES = ("base", "tail")
base = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
run = json.loads(pathlib.Path(sys.argv[1]).read_text())
man = json.loads(pathlib.Path("build/asr-corpus/manifest.json").read_text())

refs = {c["id"]: normalize(c["reference"]) for c in man["clips"]}
tags = {c["id"]: set(c.get("tags") or ()) for c in man["clips"]}

def repeat_bearing(toks):
    if any(a == b for a, b in zip(toks, toks[1:])):
        return True
    return any(toks.count(t) >= 3 for t in set(toks))

R = {cid for cid, toks in refs.items() if repeat_bearing(toks)}

def rows(doc):
    return {r["clip_id"]: r for r in doc["clip_scores"] if r["lane"] in LANES}

b, r = rows(base), rows(run)
common = sorted(set(b) & set(r) & set(refs))

def del_rate(rowmap, ids):
    d = sum((rowmap[i].get("deletions") or 0) for i in ids)
    w = sum(len(refs[i]) for i in ids)
    return (d / w) if w else 0.0

def errs(rowmap, ids):
    return sum(1 for i in ids if rowmap[i].get("wer") is None)

ids_R = [i for i in common if i in R]
ids_long = [i for i in common if "long" in tags.get(i, ())]
noise = base.get("noise", {})
m_all = max(0.003, 2 * float(noise.get("wer_mean", 0.0)))
m_R = max(0.005, 3 * float(noise.get("wer_mean", 0.0)))
m_junk = max(0.01, 2 * float(noise.get("trailing_junk_rate", 0.0)))

print(f"clips_common={len(common)} clips_R={len(ids_R)} clips_long={len(ids_long)}")
ok = True
for label, ids, margin in (("all", common, m_all), ("R", ids_R, m_R),
                           ("long", ids_long, None)):
    bd, rd = del_rate(b, ids), del_rate(r, ids)
    verdict = "" if margin is None else (" PASS" if rd <= bd + margin else " FAIL")
    if margin is not None and rd > bd + margin:
        ok = False
    print(f"deletion_rate[{label}] base={bd:.5f} run={rd:.5f} delta={rd - bd:+.5f}"
          f"{'' if margin is None else f' margin={margin:.5f}'}{verdict}")
bj = base["aggregates"]["per_lane"]["base"]["trailing_junk_rate"]
rj = run["aggregates"]["per_lane"]["base"]["trailing_junk_rate"]
pass_j = rj <= bj + m_junk
ok = ok and pass_j
print(f"trailing_junk_rate[base_lane] base={bj:.4f} run={rj:.4f} margin={m_junk:.4f}"
      f" {'PASS' if pass_j else 'FAIL'}")
tj = run["aggregates"]["per_lane"]["tail"]["trailing_junk_rate"]
print(f"trailing_junk_rate[tail_lane] base="
      f"{base['aggregates']['per_lane']['tail']['trailing_junk_rate']:.4f} run={tj:.4f}")
print(f"errors base={errs(b, common)} run={errs(r, common)}")
sys.exit(0 if ok else 1)
PY
```

**Step 3 — the control cell, then the engine-parity gate.**

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q05/q05-rp100-ng3.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q05/thresholds.json
```

If `asr_experiment.py run --help` shows the variant is positional rather than
`--variant`, use the positional form; nothing else changes.

The control is expected to be **denied** (exit `1`) — it changes nothing, so it
cannot beat the target margin. That is not a failure. What matters is parity:

```sh
.venv/bin/python - "$(ls -d build/asr-experiments/*-q05-rp100-ng3 | tail -1)/result.json" <<'PY'
import json, pathlib, sys
b = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())["aggregates"]
r = json.loads(pathlib.Path(sys.argv[1]).read_text())["aggregates"]
n = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())["noise"]
ok = True
for k in ("wer_mean", "trailing_junk_rate"):
    tol = max(2 * float(n[k]), 0.002 if k == "wer_mean" else 0.01)
    d = abs(r[k] - b[k])
    print(f"parity {k} base={b[k]:.4f} run={r[k]:.4f} |d|={d:.4f} tol={tol:.4f}"
          f" {'PASS' if d <= tol else 'FAIL'}")
    ok = ok and d <= tol
sys.exit(0 if ok else 1)
PY
```

Exit `0` → the in-process engine reproduces the baseline; continue. Exit `1` →
**stop the plan**: the two engines disagree on text metrics, which invalidates
every comparison this plan would make. Record the printed numbers, set
`Status: abandoned`, and raise it as a harness defect (`HARNESS.md` §3.1 claims
cross-engine text-metric comparability; this is its test).

**Step 4 — the eleven remaining cells**, in matrix order. For each `<variant>`:

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant <variant> \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q05/thresholds.json
RUN=$(ls -d build/asr-experiments/*-$(basename <variant> .json) | tail -1)
.venv/bin/python build/asr-experiments/q05-check.py "$RUN/result.json"
CHECK=$?
.venv/bin/python - "$RUN" "$CHECK" <<'PY'
import json, pathlib, sys
p = pathlib.Path("build/asr-experiments/q05-checks.json")
d = json.loads(p.read_text()) if p.exists() else {}
d[pathlib.Path(sys.argv[1]).name] = int(sys.argv[2])
p.write_text(json.dumps(d, indent=2, sort_keys=True))
PY
```

`q05-checks.json` is what makes step 5 mechanical: it maps each run directory
name to that cell's `q05-check.py` exit code, so the selection script drops a
failed-check cell by reading a file rather than by a human remembering which
ones failed.

Exit-code handling, per cell:

- `run` exit `0` **and** check exit `0` → the cell is a **candidate**.
- `run` exit `0` **and** check exit `1` → **not a candidate** (a secondary guard
  failed); record its numbers, continue to the next cell.
- `run` exit `1` → denied; record, continue.
- `run` exit `2` → harness error. Record the message and stop the whole plan;
  do not run further cells and do not select a winner from a partial matrix.
  (Exception: exit `2` on a *single* cell whose message names an invalid
  variant is a typo in that variant file — fix the file, re-run that cell only,
  and continue.)

Never re-run a denied cell hoping for a different number; decoding is
deterministic at T=0.

**Step 5 — selection (mechanical, no judgement).**

```sh
.venv/bin/python - <<'PY'
import json, pathlib, sys
checks_path = pathlib.Path("build/asr-experiments/q05-checks.json")
if not checks_path.exists():
    print("FAIL q05-checks.json missing; step 4 did not complete"); sys.exit(2)
checks = json.loads(checks_path.read_text())
cands = []
for d in sorted(pathlib.Path("build/asr-experiments").glob("*-q05-*")):
    v, res = d / "verdict.json", d / "result.json"
    if not (v.exists() and res.exists()):
        continue
    ver, r = json.loads(v.read_text()), json.loads(res.read_text())
    if not ver.get("accepted"):
        continue
    if checks.get(d.name) != 0:            # secondary guards failed, or never ran
        print("drop", d.name, "check=", checks.get(d.name))
        continue
    dec = r["variant"]["decode"]
    cands.append((r["aggregates"]["trailing_junk_rate"], r["aggregates"]["wer_mean"],
                  dec.get("repetition_penalty", 1.0),
                  abs(dec.get("no_repeat_ngram_size", 3) - 3), r["run_id"]))
for c in sorted(cands):
    print("candidate", *(f"{x}" for x in c))
print("WINNER", sorted(cands)[0][-1] if cands else "none")
PY
```

The winner is the accepted cell whose `q05-check.py` also exited `0` — the script
reads that from `build/asr-experiments/q05-checks.json`, so no cell is ever
dropped by hand — with the **lowest `trailing_junk_rate`**; ties break by lower
`wer_mean`, then lower `repetition_penalty`, then smaller
`|no_repeat_ngram_size − 3|` — i.e. the smallest deviation from the shipped
stack. If no cell qualifies, the plan is **denied**; follow §9's deny path.

## 6 Metrics & accept/deny

**Target**: `trailing_junk_rate`, direction `lower`, margin `0.5`,
`margin_kind` `relative` — the run must halve the baseline's rate over the
thresholds' lanes. A relative margin is used, not the `0.03` absolute of
`HARNESS.md` §6.1's example, because the baseline rate is unknown until Q09's
lane is characterised and an absolute margin is either unmeetable (small
baseline) or trivial (large baseline). `HARNESS.md` §7.1's "margin ≥ 2× recorded
noise" rule is checked mechanically against the relative margin's *effective*
value in §5 step 0, before anything runs.

**Lanes.** `["base", "tail"]` for both the variant and the thresholds — the two
must be equal (`HARNESS.md` §6.1), and the verdict's aggregates are therefore
computed over the union of the 400 clips. The union dilutes the tail-lane effect
(300 of 400 clips carry the trailing noise), which makes the target *harder*,
not easier — an acceptable direction. What the union could hide is a variant
that improves `tail` while making `base` worse; §5's `q05-check.py` closes that
with an explicit per-lane guard on the `base` lane, and prints both lanes'
numbers for the Outcome.

`docs/experiments/variants/Q05/thresholds.json`, verbatim:

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.25,
  "forbid_empty_regressions": true,
  "target": {
    "metric": "trailing_junk_rate",
    "direction": "lower",
    "margin": 0.5,
    "margin_kind": "relative"
  },
  "lanes": ["base", "tail"],
  "min_clips": 400
}
```

**Guards enforced by the harness** (`HARNESS.md` §6.2): `wer_mean` ≤ baseline +
0.002; target improves by ≥ 50 % relative; `rtf_p95` ≤ ×1.25 baseline; no clip
non-empty in the baseline goes empty; no clip errors in the run that succeeded
in the baseline.

**Guards enforced by `q05-check.py`** (the deletion story `thresholds.json` has
no field for):

| Guard | Rule |
|---|---|
| Corpus deletions | `deletion_rate[all]` ≤ baseline + `max(0.003, 2 × noise.wer_mean)` |
| Repeat-bearing deletions | `deletion_rate[R]` ≤ baseline + `max(0.005, 3 × noise.wer_mean)` |
| `base`-lane junk | `per_lane.base.trailing_junk_rate` ≤ baseline + `max(0.01, 2 × noise.trailing_junk_rate)` |

`R` is the set of clips whose **reference** already repeats: any adjacent
identical token pair, or any token occurring ≥ 3 times (which captures
high-frequency function words automatically, without a hand-written stop list to
maintain). Both rates are token-weighted — `Σ deletions / Σ reference words` over
the subset, matching `HARNESS.md` §4.2's `*_rate` definition — and are computed
over the **intersection** of clip ids present in both baseline and run, so a
partial run cannot be compared against a fuller baseline. The `long` stratum's
deletion rate is printed without a guard: a penalty's damage grows with sequence
length, so a `long` figure that moves while `all` does not is the signature to
record for a follow-up, not a verdict.

**Deciding the matrix**: best accepted by target metric, with the deterministic
tie-break in §5 step 5 (not first-in-order). Rationale: the cells are cheap and
non-monotone in two dimensions, so first-in-order would pick an arbitrary cell.

## 7 Cost estimate

`HARNESS.md` §8.4, in-process ≈ 0.7 s per clip after one load, plus ≈ 5 s of
interpreter/import and ≈ 0.7–2.8 s of cold model load per variant.

- Per cell: 400 clips (100 `base` + 300 `tail`) × 1 repeat × 0.7 s = **280 s**,
  plus ≈ 8 s start-up ≈ **4.8 min**.
- Full grid: 12 × 4.8 min = **≈ 58 min**.
- `preflight` (one cold load, `HARNESS.md` §8.2 step 5): ≈ **1 min**.
- Check scripts: seconds.
- **Total ≈ 60 min; budget 90 min** on the reference machine (RTX 3080 Laptop).
- Reduced design (§4 fallback): 6 × 4.8 min ≈ **29 min**.

Disk: the corpus already exists (base WAV ≈ 24 MB, tail ≈ 100 MB). This plan
adds 12 run directories at a few MB each — **≈ 50 MB** under `build/`, well
inside `HARNESS.md` §8.2's 1 GiB floor. Nothing is written outside `build/`
except this file, the 12 variant JSONs, `thresholds.json`, and (on deny) one
`verdict.json` copy under `docs/experiments/results/`.

## 8 Risks, confounds, invariants

**What else the change can move.**

1. **Deletions of legitimate repeats** — the intended cost of
   `repetition_penalty > 1`. Caught by the two deletion guards in §6; the `R`
   subset exists precisely because a corpus-wide rate can absorb a real loss on
   the minority of clips that repeat words. Residual risk: LibriSpeech read
   speech repeats words less than dictation does, so `R` may be small; the check
   prints `clips_R` so an underpowered subset is visible in the Outcome rather
   than silently passing. If `clips_R < 40`, treat a passing `R` guard as
   uninformative and say so in the Outcome.
2. **Timestamp-token drift.** The penalty is applied to timestamp tokens as
   well, so segment boundaries and word times can shift, which feeds
   `hallucination_silence_threshold` (`model.py:119`) and `_validate_output`'s
   timestamp and word-density checks (`model.py:178-205`). Two directions:
   *new* `PathologicalOutputError` clips are caught by `HARNESS.md` §6.2 guard 5
   (no clip errors that succeeded in the baseline); *fewer* errors are not a
   guard failure but silently change the denominator of every text aggregate —
   a clip that errored in the baseline (no `wer`) and decodes in the run enters
   `wer_mean`. `q05-check.py` prints the error count on both sides so this is
   recorded; if the counts differ, the Outcome must say so and the accepted
   cell's `wer_mean` delta is read as approximate.
3. **`trailing_junk_rate`'s denominator** is the clips with a hypothesis
   (`HARNESS.md` §4.2), so the same error-population shift moves the target
   metric's base too. Same mitigation: the printed error counts.
4. **Overlap with Q07 and Q11.** `hallucination_silence_threshold` (Q07) and a
   post-decode tail filter (Q11) attack the same symptom. If two of them accept
   independently, their gains are not additive; `HARNESS.md` §7.3 forces one
   merge at a time with a re-baseline between, which resolves it empirically.
5. **Interaction with Q01 (ordering).** Q01 replaces the scalar `temperature`
   with the fallback ladder, which makes `compression_ratio_threshold` live —
   itself a loop detector. If Q01 merges first, the shipped defaults move and
   `DecodeOptions.temperature` changes with them, so a Q05 cell run afterwards
   decodes at *every* fallback temperature with the penalty applied. Handling,
   mechanically: §5 step 0 refuses to run unless `git diff --quiet
   <baseline.environment.git_commit> HEAD -- src/ pyproject.toml` exits `0`, so a
   merge that moves the shipped decode stack invalidates the plan run rather than
   corrupting it, and the whole 12-cell matrix is re-run against the re-baselined
   defaults. A Q05 result is only ever valid against the shipped code recorded in
   its Outcome. `compare` deliberately does *not* refuse on the commit
   (`HARNESS.md` §6.4: it checks the compared lanes' digests, device and model,
   never `git_commit`) — which is exactly why step 0 exists, and why it asks about
   content rather than about HEAD.
6. **CT2 penalty scope vs. prompt tokens.** Whether CTranslate2's penalty
   includes prompt tokens (`initial_prompt` / `hotwords`, injected at
   `transcribe.py:1200-1206`, `get_prompt` at `transcribe.py:1532-1552`) is not
   determined from the compiled extension. It does not affect this plan — both
   are empty in the shipped defaults and this plan sets no `config` — but Q08
   (initial prompt) must not assume the answer.
7. **Multiple comparisons over 12 cells.** With deterministic decoding the risk
   is not sampling noise but corpus overfit: one cell may clear a margin by
   luck of this 400-clip set. Mitigations: the margin is relative and large
   (50 %); the guards are five-deep; and the Outcome must record whether the
   winner is *isolated* — i.e. whether either of its grid neighbours (same
   `no_repeat_ngram_size`, adjacent `repetition_penalty`; or same penalty,
   adjacent ngram size) also accepted. An isolated winner is recorded as a
   caveat, **not** converted into a denial; the acceptance gate on the real
   machine (§9) is the second opinion.
8. **`no_repeat_ngram_size = 0` cells** are expected to be worse, not better;
   they exist to measure whether today's `3` is doing anything at all. A grid
   where ngram 0 ≈ ngram 3 ≈ ngram 5 is itself the finding — record it, because
   it would mean the shipped `3` is inert and Q11's post-decode filter is the
   more promising route.
9. **Corpus realism.** LibriSpeech is read speech with unpunctuated uppercase
   references; the tail lane's −60 dBFS Gaussian tone is not room noise from the
   owner's microphone. A junk rate measured here is a proxy. `HARNESS.md` §5.1
   notes normalization biases every variant equally, so within-plan deltas hold
   even where absolute numbers do not.

**Invariant checklist** (`HARNESS.md` §9, restated for this plan):

- **No transcript text** in `result.json`, `report.md`, `verdict.json`, stdout,
  this file, any file under `docs/experiments/variants/Q05/`, or
  `docs/experiments/results/`. `q05-check.py` reads corpus references and prints
  only counts and rates. Text stays in `clips.jsonl` under `build/`.
- **No network in the ASR path.** `local_files_only=True` (`model.py:87`)
  unchanged; this plan runs in-process with no config overrides and downloads
  nothing. The corpus is already fetched (Q09 prerequisite).
- **No platform imports.** The plan adds no code to `src/` and no new script;
  `q05-check.py` imports `scripts/asr_metrics.py` and stdlib only.
- **Test policy** (`AGENTS.md` hard rule 4): this plan writes no test. On accept,
  the only test touched is the existing `DecodeOptions` pinning test — a literal
  comparison, not a mock.
- **Fixed behaviour stays fixed.** `repetition_penalty` and
  `no_repeat_ngram_size` are never exposed to user config; the config stays at
  exactly 23 keys in 4 sections (`AGENTS.md` hard rule 9). Only `scripts/`
  constructs a non-default `DecodeOptions`.
- **Venv only**, SPDX header on any new `.py` (none is committed by this plan),
  ruff clean, line length 100.

## 9 Deliverables & follow-through

**On accept**, the implementation commit (separate from the run) does all of:

1. `src/stenographer/transcribe/model.py:110-125` — the `self._impl.transcribe(...)`
   call: set `no_repeat_ngram_size=<winner>` (the literal is at `model.py:115`)
   and add `repetition_penalty=<winner>` as an explicit keyword next to it, even
   when the winning value equals the library default, so the stack states its
   own choice rather than inheriting one.
2. `DecodeOptions` (`HARNESS.md` §3.2, in the same module): update the
   `repetition_penalty` and `no_repeat_ngram_size` defaults to the same values —
   the dataclass defaults must stay byte-for-byte the shipped literals — and
   update the pinning test's literal dict in `tests/transcribe/test_model.py`.
   Editing both is the intended friction.
3. `AGENTS.md` hard rule 5, the sentence naming the anti-hallucination stack
   ("The anti-hallucination decode stack (VAD pre-filter, no-speech gate,
   silence trimming, short-audio token ceiling, output validation) is fixed
   behavior, not configuration") — extend the parenthesised list to name the
   repetition controls, e.g. "… short-audio token ceiling, the repetition
   penalty and no-repeat n-gram block, output validation …". One sentence, in
   the same commit as the code.
4. **No new test asserts the `transcribe()` kwargs**, deliberately: `AGENTS.md`
   hard rule 4 forbids mocking the model to prove a call would have happened,
   and a green mock here would prove nothing. The `DecodeOptions` pinning test
   plus the integration smoke suite are the guard.
5. **Re-baseline** (`HARNESS.md` §7.3 case 1): after the merge to `dev`, re-run
   `baseline` over the seven baseline lanes (`HARNESS.md` §7.1) with the
   subprocess engine and 3 repeats, and
   say in the commit message that an accepted experiment moved the defaults. The
   re-baseline commit touches `docs/experiments/baseline.json` and nothing under
   `src/`.
6. **Acceptance gates** (`AGENTS.md`, real machine, before dev → main):
   `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest` green; real dictation
   end-to-end in `hold`, `toggle` and `hybrid`; and — because this changes the
   decode stack — the capture/logging gate: a cold-start dictation retains its
   opening words, and `stenographer.log` plus the journal show metrics with no
   transcript or audio content. Watch specifically for legitimate repeated words
   surviving ("that that", a repeated proper noun); that is the failure mode the
   corpus can under-detect (§8 risk 1).
7. Set `Status: accepted (<date>)` at the top of this file and append an
   `Outcome` section: the winning variant name, its run id, the verdict line,
   the baseline commit it was compared against, the `q05-check.py` output, and
   whether the winner was isolated (§8 risk 7). Numbers only.

**On deny** (no cell qualifies, or step 0 / step 3 stopped the plan): append an
`Outcome` section with the verdict line and run id of the best cell, copy each
denied cell's `verdict.json` to
`docs/experiments/results/Q05-<run-id>.json` (numbers only), set
`Status: denied (<date>)`, and record which of the three grid observations held:
whether the penalty moved junk at all, whether ngram size moved anything, and
whether deletions were the binding constraint. That record is the input to Q11
(post-decode tail filter), which is the fallback route to the same symptom.

## 10 Out of scope

- **`temperature` and the fallback ladder** — Q01. This plan holds
  `temperature = (0.0,)`, which also keeps `compression_ratio_threshold` inert
  (`HARNESS.md` §3.2).
- **`hallucination_silence_threshold`** — Q07, on the same `tail` lane.
- **A post-decode terminal-n-gram filter** — Q11; the non-decoder route to the
  same symptom, and the fallback if this plan denies.
- **Building or characterising the `tail` lane** — Q09; this plan consumes it.
- **The `cue` lane, leading-word recall, VAD parameters** — Q02, Q10.
- **`beam_size`** — Q03; held at the shipped `1`. A penalty interacts with beam
  search, so a later `beam_size` change re-opens this question; that is Q03's
  ordering problem, resolved by `HARNESS.md` §7.3's one-merge-at-a-time rule.
- **`asr.initial_prompt` / `asr.hotwords`** — Q08; both empty here.
- **Model changes** — Q12.
- **`length_penalty`, `patience`, `suppress_tokens`, `best_of`** — no plan; not
  reachable through `DecodeOptions` today, and adding a field for them is a
  `HARNESS.md` §3.2 change, not a Q05 change.
- **Exposing either knob in user config** — forbidden (`AGENTS.md` hard rules 5
  and 9); the outcome of this plan is a new fixed literal, never a new key.
- **A per-lane target metric in `thresholds.json`** — would remove §6's union
  dilution, but it is a `HARNESS.md` §6.1 schema change and belongs to the
  harness owner, not to this plan.
