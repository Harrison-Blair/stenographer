# Q12 — alternate models

Status: planned (2026-08-29)

Baseline for every `file:line` citation: `dev` @ `a1b9807` (v0.11.6),
faster-whisper 1.2.1, CTranslate2 4.8.1, Python 3.14.7, in the repo venv.
Reference machine: RTX 3080 Laptop, 8192 MiB VRAM (`nvidia-smi`, verified
2026-08-29); 851 GiB free on `/`.

## 1 Hypothesis

At least one of `mobiuslabsgmbh/faster-whisper-large-v3-turbo`,
`Systran/faster-whisper-large-v3`, `Systran/faster-distil-whisper-medium.en`
and `Systran/faster-whisper-small.en`, swapped into `asr.model` with every
other shipped decode literal unchanged, **dominates** the shipped
`Systran/faster-whisper-medium.en` on `base + tail + cue`: `wer_mean` lower by
at least the plan margin (§6), `rtf_p95` no worse than ×1.25, and
`trailing_junk_rate` / `leading_miss_rate` no worse than their tolerances,
with no empty regressions and no new clip errors.

This is a **ranking** experiment. Its product is a Pareto table over five
points (four candidates plus the shipped reference) and a recommendation;
it changes no literal by itself (§9).

## 2 Symptom & mechanism

The three symptoms this plan scores are the owner's (README.md of this
directory, items 1–3), plus speed (item 4):

- **General hallucination rate** → `wer_mean` / `insertion_rate` on `base`.
- **Trailing loops** ("thank you", "and more and more") → `trailing_junk_rate`
  on the `tail` lane (the lane `Q09` characterises).
- **Missing opening words** → `leading_miss_rate` /
  `leading_word_recall_mean` on the `cue` lane (`Q10`).
- **Latency** → `load_ms_*`, `decode_ms_*`, `first_response_ms_*`, `rtf_*`.

Mechanism. The model id is the one decode input the daemon already exposes as
configuration: `asr.model` is read as a free string
(`src/stenographer/config.py:196`, `_Reader.str` — no allow-list) and handed
straight to `WhisperModel(cfg.model, …)`
(`src/stenographer/transcribe/model.py:82-88`). Everything downstream is
model-independent by construction: `language="en"` is fixed
(`model.py:112`), so a multilingual checkpoint never runs language detection;
`temperature=0.0`, `no_repeat_ngram_size=3`,
`hallucination_silence_threshold=2.0`, `max_new_tokens=_token_budget(…)`,
`condition_on_previous_text=False` and `word_timestamps=True` are call-site
literals (`model.py:110-125`); the VAD pre-filter is `_VAD_PARAMETERS`
(`model.py:32-37`); the post-decode gate is `no_speech_prob <
cfg.silence_threshold` in `_assemble` (`model.py:207-227`).

Capacity and architecture are therefore the only variables. Larger encoders
reduce substitutions on hard audio (symptom 3); the distilled and turbo
decoders are shallower and are the ones reported to loop on non-speech, which
is precisely what the `tail` lane provokes (symptom 2); encoder capacity and
the VAD/no-speech interaction drive first-word survival under cue bleed
(symptom 1). Decode cost scales roughly with decoder depth × beam, and cold
`load_ms` scales with weight bytes — the two halves of symptom 4.

## 3 Prerequisites

**Harness pieces.** `scripts/asr_corpus.py`, `scripts/asr_metrics.py`,
`scripts/asr_experiment.py` with `preflight` and `run`, per `HARNESS.md` §1.
`DecodeOptions` is *not* used by this plan.

**Injection fields.** One config key only: `asr.model`. No `decode` block —
every variant is a pure `config`-lane variant, so `engine: "subprocess"` is
legal (`HARNESS.md` §3, a non-empty `decode` with `subprocess` is a harness
error).

**Corpus lanes.** `base`, `tail`, `cue` — all three, 700 clips, produced by
`asr_corpus.py` and characterised by `Q09` / `Q10`.

**Baseline.** `docs/experiments/baseline.json` present, written from a clean
tree, with a `noise` block carrying `wer_mean`, `trailing_junk_rate` and
`leading_miss_rate` (`HARNESS.md` §7.1). Its `environment.model` must be
`Systran/faster-whisper-medium.en` — it is the reference point of the Pareto
table, not merely a guard.

**Cross-model comparison route (read this before writing thresholds).**
`compare` normally refuses when `environment.model` differs, and `HARNESS.md`
§6.4 grants exactly one exception: *"or when `environment.model` differs
unless the plan is Q12 (the thresholds file then carries
`"allow_model_change": true`)"*. So the route is:

1. **Per model, one `run` against the shipped baseline**, with
   `"allow_model_change": true` in that model's thresholds file. The harness's
   own `decide` (`HARNESS.md` §6.2) then yields a per-model exit code covering
   `wer_mean`, `rtf_p95`, empty regressions and new errors.
2. **A plan-level Pareto table across the five points**, built by §5's script
   from the four `result.json` files plus `baseline.json`. `decide` carries
   exactly one `target` metric, so the two *symptom* guards
   (`trailing_junk_rate`, `leading_miss_rate`) and the cross-model ranking
   cannot live inside it; they are computed at plan level, from numbers only.

`"allow_model_change"` is in `HARNESS.md` §6.1's `thresholds.json` field list
and in §6.4's refusal rule: boolean, default `false`, honoured only when
`plan == "Q12"`, and `validate_variant` rejects it for any other plan. If the implemented
harness does not know the key, Q12 stops with a harness error and that gap is
reported — do not work around it by editing `baseline.json` or by comparing
runs to each other.

**Order.** This plan is step 5 of the programme order (`README.md`). Run it
only when no accepted quality change is sitting unmerged/unbaselined: the
reference must be the shipped stack.

**Environment gates**, each checked before any download (§5 step 1):

- `nvidia-smi --query-gpu=memory.used,memory.free --format=csv` reports at
  least 6000 MiB free; otherwise abort (harness error) — a compositor or a
  stray process holding VRAM would silently change the large-v3 numbers.
- At least 8 GiB free on the filesystem holding `~/.cache/huggingface` and 1
  GiB free under `build/` (`HARNESS.md` §8.2 step 7).
- Network reachable — the four downloads are the only network use, and they
  happen through `stenographer model download` alone.

## 4 Variant matrix

Every variant overrides **only** `asr.model`. Nothing else is set, so
`beam_size`, `compute_type`, `silence_threshold`, `vad_filter`,
`idle_unload_seconds` and `cpu_threads` all come from `Config.defaults()`
(`config.py:305-320`) exactly as the baseline's did.

- **Beam rule.** No variant sets `asr.beam_size`. Every run inherits the
  shipped default — `1` today (`config.py:255`). If `Q03` was accepted and
  merged (and the baseline re-established, `HARNESS.md` §7.3 case 1), the new
  default is inherited automatically and the comparison stays matched. Record
  the effective value from `result.json` → `variant.config` (absent) and from
  the run's `config.toml` (absent) — i.e. state in the outcome that beam came
  from the defaults, and quote `config.py:255` as it read at run time.
- **Compute-type rule.** No variant sets `asr.compute_type` either. If `Q04`
  accepted a compute type and it was merged into `config.py`, the variants
  inherit it; if `Q04` has not merged, they inherit the shipped `"int8"`
  (`config.py:254`), which this GPU resolves to `int8_float16`
  (`HARNESS.md` §4.3, `compute_type_resolved`). Either way the four candidates
  and the reference share one compute type, which is the only property that
  matters here. Record `environment.compute_type_requested` and
  `compute_type_resolved` from each `result.json`.
- **The one exception** is the OOM contingency variant in §8, which is
  explicitly compute-type-unmatched and labelled as such.

| # | Variant name | `asr.model` | Lanes | Engine | Repeats | Variant JSON |
|---|---|---|---|---|---|---|
| 1 | `q12-small-en` | `Systran/faster-whisper-small.en` | base, tail, cue | `subprocess` | 1 | `docs/experiments/variants/Q12/q12-small-en.json` |
| 2 | `q12-distil-medium-en` | `Systran/faster-distil-whisper-medium.en` | base, tail, cue | `subprocess` | 1 | `docs/experiments/variants/Q12/q12-distil-medium-en.json` |
| 3 | `q12-large-v3-turbo` | `mobiuslabsgmbh/faster-whisper-large-v3-turbo` | base, tail, cue | `subprocess` | 1 | `docs/experiments/variants/Q12/q12-large-v3-turbo.json` |
| 4 | `q12-large-v3` | `Systran/faster-whisper-large-v3` | base, tail, cue | `subprocess` | 1 | `docs/experiments/variants/Q12/q12-large-v3.json` |
| C | `q12-large-v3-int8` (contingency, §8 only) | `Systran/faster-whisper-large-v3` + `compute_type: "int8"` | base, tail, cue | `subprocess` | 1 | `docs/experiments/variants/Q12/q12-large-v3-int8.json` |

Order is ascending by expected cost, so a cheap failure surfaces early.

Every row leaves `compute_type` at the shipped default except row C, so the
matrix is **only meaningful after Q04 has merged**: Q04 settles what that
default is, and a cross-model latency ordering measured at one compute type
says nothing about the ordering at another. `README.md`'s execution order puts
Q04 before this plan for exactly that reason.

`engine: "subprocess"` is mandatory here, not `auto`: this plan reports
`load_ms` and `first_response_ms` across model sizes, and only the subprocess
engine loads cold on every clip (`HARNESS.md` §3.1). `repeats: 1` — every
variant decodes at `temperature=0.0` (`model.py:114`), the deterministic case
(`HARNESS.md` §8.3).

**Repo ids.** `Systran/faster-whisper-small.en`,
`Systran/faster-distil-whisper-medium.en` and
`Systran/faster-whisper-large-v3` are faster-whisper 1.2.1's own canonical
targets for the shorthands `small.en`, `distil-medium.en` and `large-v3`
(`.venv/lib/python3.14/site-packages/faster_whisper/utils.py:11-31`); the same
table maps `large-v3-turbo` and `turbo` to
`mobiuslabsgmbh/faster-whisper-large-v3-turbo` (`utils.py:29-30`), which is why
that repo — not `deepdml/faster-whisper-large-v3-turbo-ct2` — is the one used
here. **The executing agent still confirms each id resolves** by running
`stenographer model download` under that model's config (§5 step 3) and, if a
download fails, records the failure and moves to the next model rather than
substituting an id of its own. A substituted id (e.g. the `deepdml`
conversion, if `mobiuslabsgmbh` has been withdrawn) is permitted **only** when
the canonical one 404s, must be recorded in the outcome with its reason, and
must be written into the checked-in variant JSON before the run.

**Never put a shorthand in `asr.model`.** `download_model` calls
`snapshot_download(model_id, …)` (`model.py:242-255`) and `is_model_cached`
calls `try_to_load_from_cache(model_id, "config.json")`
(`model.py:229-239`) — both treat the string as a Hub repo id — while
`WhisperModel` would silently expand `"turbo"` through `_MODELS`. A shorthand
therefore makes the harness's preflight cache probe (`HARNESS.md` §8.2 step 2)
disagree with the model actually loaded.

Every variant JSON is exactly (with `<name>` and `<repo id>` substituted):

```json
{
  "schema": 1,
  "name": "q12-small-en",
  "plan": "Q12",
  "lanes": ["base", "tail", "cue"],
  "tags_any": [],
  "tags_all": [],
  "engine": "subprocess",
  "repeats": 1,
  "config": {"asr": {"model": "Systran/faster-whisper-small.en"}},
  "decode": {}
}
```

## 5 Procedure

Every command runs from the repository root with the repo venv. No step needs
a human. Record every number this section asks for into
`build/asr-experiments/q12-notes.json` (a scratch file under `build/`, numbers
and ids only) as you go; §9 renders the outcome from it.

**Step 0 — bind the CLI surface.** `HARNESS.md` fixes the subcommands but not
every flag spelling:

```sh
.venv/bin/python scripts/asr_experiment.py run --help
```

Use the spellings it prints. Where this section writes
`run --variant <path> --baseline <path> --thresholds <path>`, substitute the
implemented form (a positional variant path is equally acceptable). If `run`
has no `--thresholds`, or the harness rejects `allow_model_change`, stop:
that is the §3 prerequisite gap, and it is a harness error (exit 2), not a
verdict.

**Step 1 — environment gates.**

```sh
nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv
df -h ~/.cache/huggingface build
git rev-parse --short HEAD && git status --porcelain
```

Abort if free VRAM < 6000 MiB, if free disk < 8 GiB, or if the tree is dirty
in a way that touches `src/` (a dirty tree is recorded, not refused, for a
`run` — `HARNESS.md` §8.2 step 6 — but a `src/` edit invalidates the
comparison with the checked-in baseline).

**Step 2 — write the variant and thresholds files.** Create the four variant
JSONs of §4 and the four thresholds files of §6 under
`docs/experiments/variants/Q12/`. These are checked-in inputs; write them
before any run so the run is reproducible from the repository alone.

**Step 3 — per model, in the §4 order.** For `<name>` and `<repo id>`:

*3a. Config for the download.* `stenographer model download` reads
`asr.model` from the configuration `STENOGRAPHER_CONFIG` points at
(`cli/commands/model.py:16-20` → `with_config` → `config.load_or_default()` →
`resolve_config_path()`, `config.py:384-389`, `config.py:370-380`), and
`load_or_default` **writes an annotated default file if the path does not
exist**, so always point it at a path you have written first:

```sh
mkdir -p build/asr-experiments/q12-configs
printf '[stenographer.asr]\nmodel = "<repo id>"\n' \
  > build/asr-experiments/q12-configs/<name>.toml
```

*3b. Download — the only network step, and the only permitted download.*
Do **not** set `HF_HUB_OFFLINE` here (it would break the fetch); do set it for
every later invocation.

```sh
BEFORE=$(du -sb ~/.cache/huggingface/hub | cut -f1)
time STENOGRAPHER_CONFIG=build/asr-experiments/q12-configs/<name>.toml \
  .venv/bin/stenographer model download
AFTER=$(du -sb ~/.cache/huggingface/hub | cut -f1)
echo "<name> bytes=$((AFTER-BEFORE))"
ls -1 ~/.cache/huggingface/hub/models--<org>--<repo>/snapshots/
```

Record: byte delta, wall time, and the snapshot directory name — that name is
the resolved commit sha, and it is the **exact revision** to report. A non-zero
exit (unknown repo, network failure) is recorded as
`status: "download_failed"` for that model; skip to the next model. Never
fetch weights by any other route.

*3c. Load-and-decode smoke, before spending an hour.* One clip, output
discarded so no transcript text reaches any recorded artifact:

```sh
CLIP=$(ls -1 build/asr-corpus/wav/base/*.wav | head -1)
STENOGRAPHER_CONFIG=build/asr-experiments/q12-configs/<name>.toml \
HF_HUB_OFFLINE=1 .venv/bin/stenographer transcribe "$CLIP" > /dev/null
echo "smoke exit=$?"
```

Exit 0 → continue. Exit 78 → the cache probe failed (usually a shorthand id or
a partial download); re-check 3a/3b once, then record
`status: "not_cached"` and skip. Any other exit or traceback → record
`status: "incompatible"` with the exception class name only (a CTranslate2
`RuntimeError` for missing alignment heads, a CUDA OOM, a missing weight file
— see §8) and skip that model. **Do not** relax `word_timestamps`, the VAD
parameters or `silence_threshold` to make a model work: that would be a
different experiment (Q02 / Q06 / Q07) run under Q12's name.

*3d. Preflight and run.*

```sh
.venv/bin/python scripts/asr_experiment.py preflight \
  --variant docs/experiments/variants/Q12/<name>.json
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q12/<name>.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q12/thresholds-<name>.json
RUN_STATUS=$?          # capture immediately: the next command overwrites $?
RUN_DIR=$(ls -1dt build/asr-experiments/*-<name> | head -1)
echo "<name> exit=$RUN_STATUS dir=$RUN_DIR"
```

Exit codes: `0` = this model passed the harness's own guards (wer margin,
rtf ratio, empties, errors) — record and continue; `1` = denied — record and
continue, the table still needs its numbers; `2` = harness error — read the
message, and if it is a preflight failure specific to this model (model not
cached, GPU busy) record it and continue to the next model, otherwise stop
the plan and report the harness gap.

Record for each model: exit code, run id, and from `<RUN_DIR>/result.json`
`environment.compute_type_requested`, `compute_type_resolved`, `cpu_threads`,
`git_commit`, `git_dirty`, plus `corpus.manifest_sha256`.

**Step 4 — the Pareto table.** After every model has been attempted:

```sh
mkdir -p build/asr-experiments/q12-pareto
.venv/bin/python - build/asr-experiments/q12-pareto/pareto.md <<'PY'
import json, math, pathlib, sys

BASE = pathlib.Path("docs/experiments/baseline.json")
RUNS = pathlib.Path("build/asr-experiments")
ref = json.loads(BASE.read_text())
runs = {}
for name in ("q12-small-en", "q12-distil-medium-en", "q12-large-v3-turbo",
             "q12-large-v3", "q12-large-v3-int8"):
    dirs = sorted(RUNS.glob(f"*-{name}"))
    if dirs:
        runs[name] = json.loads((dirs[-1] / "result.json").read_text())

for r in runs.values():
    assert r["corpus"]["manifest_sha256"] == ref["corpus"]["manifest_sha256"], "corpus mismatch"
    assert r["environment"]["device"] == ref["environment"]["device"], "device mismatch"

LANES = {"base", "tail", "cue"}

def rows(result):
    return {c["clip_id"]: c for c in result["clip_scores"] if c["lane"] in LANES}

ids = set(rows(ref))
for r in runs.values():
    ids &= set(rows(r))
ids = sorted(ids)

def pct(values, q):
    v = sorted(values)
    return v[math.ceil(q * len(v)) - 1] if v else None

def agg(result):
    rs = rows(result)
    sel = [rs[i] for i in ids]
    ok = [c for c in sel if c.get("rtf") is not None]
    # An errored clip has every metric null (HARNESS.md 4.1); scoring it would
    # raise, so text metrics are taken over the clips that produced one.
    scored = [c for c in sel if c.get("wer") is not None]
    n = len(scored) or 1
    return {
        "clips": len(sel),
        "scored": len(scored),
        "wer_mean": sum(c["wer"] for c in scored) / n,
        "trailing_junk_rate": sum(bool(c["trailing_junk"]) for c in scored) / n,
        "leading_miss_rate": sum(
            (c["leading_word_recall"] or 0.0) < 1.0
            for c in scored
            if c.get("leading_word_recall") is not None
        ) / n,
        "empty": {i for i in ids if rs[i]["empty"]},
        "errored": {i for i in ids if rs[i].get("rtf") is None},
        "rtf_p50": pct([c["rtf"] for c in ok], 0.50),
        "rtf_p95": pct([c["rtf"] for c in ok], 0.95),
        "decode_ms_p50": pct([c["decode_ms"] for c in ok], 0.50),
        "decode_ms_p95": pct([c["decode_ms"] for c in ok], 0.95),
    }

noise = ref.get("noise", {})
M_WER = max(0.004, 2 * noise.get("wer_mean", 0.0))
T_TAIL = max(0.010, 2 * noise.get("trailing_junk_rate", 0.0))
T_LEAD = max(0.020, 2 * noise.get("leading_miss_rate", 0.0))

a_ref = agg(ref)
table = [("medium.en (shipped)", a_ref, None)]
winners = []
for name, result in runs.items():
    a = agg(result)
    dom = (
        a["wer_mean"] <= a_ref["wer_mean"] - M_WER
        and a["rtf_p95"] <= 1.25 * a_ref["rtf_p95"]
        and a["trailing_junk_rate"] <= a_ref["trailing_junk_rate"] + T_TAIL
        and a["leading_miss_rate"] <= a_ref["leading_miss_rate"] + T_LEAD
        and not (a["empty"] - a_ref["empty"])
        and not (a["errored"] - a_ref["errored"])
    )
    table.append((name, a, dom))
    if dom:
        winners.append((a["wer_mean"], a["rtf_p95"], name))

out = [f"clips={len(ids)} margins: wer>={M_WER:.4f} tail<=+{T_TAIL:.3f} lead<=+{T_LEAD:.3f}", "",
       "| model | wer_mean | trailing_junk_rate | leading_miss_rate | rtf_p50 | rtf_p95 |"
       " decode_ms_p50 | decode_ms_p95 | empty | errors | dominates |",
       "|---|---|---|---|---|---|---|---|---|---|---|"]
for name, a, dom in table:
    out.append(
        f"| {name} | {a['wer_mean']:.4f} | {a['trailing_junk_rate']:.3f} |"
        f" {a['leading_miss_rate']:.3f} | {a['rtf_p50']:.4f} | {a['rtf_p95']:.4f} |"
        f" {a['decode_ms_p50']:.0f} | {a['decode_ms_p95']:.0f} | {len(a['empty'])} |"
        f" {len(a['errored'])} | {'' if dom is None else ('yes' if dom else 'no')} |")
winners.sort()
verdict = f"ACCEPT Q12: recommend {winners[0][2]}" if winners else "DENY Q12: no model dominates"
out += ["", verdict]
text = "\n".join(out)
pathlib.Path(sys.argv[1]).write_text(text + "\n")
print(text)
sys.exit(0 if winners else 1)
PY
```

Exit 0 → ACCEPT (§6); exit 1 → DENY. An `AssertionError` means a run used a
different corpus or device: that is a harness error, exit 2 in spirit — fix
the inputs, do not edit the assertion.

The script deliberately recomputes the four decision metrics from
`clip_scores` over the **intersection** of clip ids, mirroring `HARNESS.md`
§6.2, so a partially-completed model never compares against a fuller
reference. It reads no text field — `clip_scores` has none (`HARNESS.md`
§4.3), and the §1 baseline test enforces that.

**Step 5 — record per-lane numbers.** For each model, copy
`aggregates.per_lane.{base,tail,cue}`'s `wer_mean`, `trailing_junk_rate`,
`leading_miss_rate` from `result.json` into the outcome table (§9). The
per-lane split is what tells symptom 2 from symptom 3.

**Step 6 — cache hygiene.** The agent **lists** the candidate cache
directories in the Outcome and deletes nothing:

```sh
for d in ~/.cache/huggingface/hub/models--*; do
  case "$d" in
    *models--Systran--faster-whisper-medium.en) continue ;;
  esac
  printf '%s\t%s\n' "$(du -sh "$d" | cut -f1)" "$d"
done
```

The list goes into the Outcome as "reclaimable, on the owner's word": which
directories this plan caused, and how large each is. Deleting a model cache is
not a step an agent takes on its own — it is minutes to re-fetch at best and
gigabytes at worst, and the owner may want a candidate kept for a follow-up.
`models--Systran--faster-whisper-medium.en` is excluded from the list entirely:
it is the shipped model, the reference for every future run, and 1.5 GiB to
re-fetch.

## 6 Metrics & accept/deny

**Per-model harness verdict** (`decide`, `HARNESS.md` §6.2). Target metric
`wer_mean`, direction `lower`, `margin_kind` `absolute`. Because the target
and guard 1 are the same metric, an accepted run is one that genuinely
*improves* WER, not merely holds it.

One thresholds file per model —
`docs/experiments/variants/Q12/thresholds-<name>.json` — so each model's
verdict is reproducible from checked-in inputs alone and a later tightening of
one model's margin cannot silently re-decide another's. All four start
byte-identical:

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.25,
  "forbid_empty_regressions": true,
  "allow_model_change": true,
  "target": {
    "metric": "wer_mean",
    "direction": "lower",
    "margin": 0.004,
    "margin_kind": "absolute"
  },
  "lanes": ["base", "tail", "cue"],
  "min_clips": 700
}
```

**Margin substitution (mandatory).** `validate_variant` requires a margin of
at least twice the baseline's recorded noise for the target metric
(`HARNESS.md` §7.1). Before step 2, read `noise.wer_mean` from
`docs/experiments/baseline.json`; if `2 × noise.wer_mean > 0.004`, set
`margin` in all four files to that value rounded **up** to four decimals, and
record the substitution in the outcome. The same rule fixes the plan-level
tolerances: `T_TAIL = max(0.010, 2 × noise.trailing_junk_rate)`,
`T_LEAD = max(0.020, 2 × noise.leading_miss_rate)` — §5's script computes
them, so they never need hand-editing.

**Plan-level ACCEPT.** ACCEPT iff **at least one candidate dominates** the
shipped model over the clip-id intersection of `base + tail + cue`, where
*dominates* means all six of:

1. `wer_mean ≤ ref.wer_mean − M_WER`;
2. `rtf_p95 ≤ 1.25 × ref.rtf_p95`;
3. `trailing_junk_rate ≤ ref.trailing_junk_rate + T_TAIL`;
4. `leading_miss_rate ≤ ref.leading_miss_rate + T_LEAD`;
5. no clip empty in the run that was non-empty in the reference;
6. no clip errored in the run that succeeded in the reference.

**Multi-variant resolution:** *best accepted by target metric* — among
dominating candidates, the recommendation is the one with the lowest
`wer_mean`; ties (equal to four decimals) break on lower `rtf_p95`, then on
lower `first_response_ms_p95`, then on smaller download size. Matrix order is
a cost heuristic only, never a tie-break.

**The deliverable on ACCEPT is a recommendation, not a merge** (§9). On DENY
the deliverable is the same table with the shipped model shown to sit on the
front.

Reported for every model even when it loses, because the table is the point:
`wer_mean`, `wer_corpus`, `substitution_rate`, `deletion_rate`,
`insertion_rate`, `trailing_junk_rate`, `leading_word_recall_mean`,
`leading_miss_rate`, `empty`, `errors`, `load_ms_p50/p95`,
`decode_ms_p50/p95`, `first_response_ms_p50/p95`, `rtf_p50/p95`, the per-lane
split of the first three symptom metrics, plus download bytes, download wall
time and the resolved revision sha.

## 7 Cost estimate

Per `HARNESS.md` §8.4: subprocess ≈ 1 s interpreter and imports + 0.7–2.8 s
cold load + decode; ≈ 4–5 s/clip for the shipped medium.en. 700 clips × 1
repeat per model. Decode scales with decoder depth, load with weight bytes:

| Model | Weights (approx.) | Expected s/clip | 700 clips |
|---|---|---|---|
| `small.en` | ≈0.5 GB | 2.5–3 | 30–35 min |
| `distil-medium.en` | ≈0.8 GB | 3–4 | 35–47 min |
| `large-v3-turbo` | ≈1.6 GB | 5–6 | 58–70 min |
| `large-v3` | ≈3.1 GB | 8–11 (decode ≈3–4× medium) | 1.6–2.1 h |
| *(reference: medium.en)* | 1.5 GiB, already cached | 4–5 | — |

Runs total **≈3.5–4.5 h**, plus 4 × one cold load for preflight
(`HARNESS.md` §8.2 step 5) and four single-clip smokes — a few minutes. Budget
one unattended session of **5–6 h**.

Downloads: ≈6 GB across the four repos (only `*.json`, `model.bin`,
`tokenizer.json`, `vocabulary.*`, `preprocessor_config.json` are fetched —
`model.py:246-255`), 10–60 min depending on link speed. Disk: ≈6 GB of model
cache plus ≤1 GiB of run directories under `build/`; 851 GiB were free on
`/` on 2026-08-29. Step 6 lists the candidate caches rather than deleting them,
so the ≈6 GB stays until the owner says otherwise.

The contingency variant `q12-large-v3-int8` adds up to another 2 h if it
fires; it needs no additional download.

## 8 Risks, confounds, invariants

**VRAM (8192 MiB total, shared with the desktop).** `large-v3` in `float16`
is ≈3.1 GB of weights plus activations and beam state; in `int8_float16`
≈1.6 GB. Both fit on an idle GPU, which is what step 1's ≥6000 MiB free gate
enforces. These figures, and the contingency below, are **only meaningful once
Q04 has merged**, because they are stated against whatever compute type is then
the shipped default. If `Q04` accepted `float16` *and* `Q03` accepted a wide
beam, the headroom shrinks. **Contingency:** on a CUDA OOM (a CTranslate2 `RuntimeError`
at load or first decode) the agent re-runs that model exactly once as
`q12-large-v3-int8`, with `{"asr": {"model": "…large-v3", "compute_type":
"int8"}}`, and reports it in the table **flagged as compute-type-unmatched** —
its latency is not comparable with the other four points, and it may not be
the recommendation without the fork in §9 naming the compute-type change too.

**Distil models drop hotwords.** `AGENTS.md:236-237` and `AGENTS.md:366`
record that `asr.hotwords` silently deletes words on distil models and that
this is *why* the default is a full model; `hotwords` is passed unconditionally
at `model.py:122`. This plan does not measure hotword behaviour at all (no
hotword corpus exists). Therefore: **a `distil-medium.en` win is a fork, not a
recommendation to merge** — it would overturn a documented product invariant,
and the trade (hotwords vs. WER/latency) is the owner's to make. Report it as
"dominates, but changes a documented invariant".

**Turbo loops on non-speech.** `large-v3-turbo`'s shallow decoder is the one
with a reputation for repeating on silence — precisely the `tail` lane. Guard
3 (`trailing_junk_rate`) is the discriminator and it is deliberately a *no
worse* tolerance, not a *must improve* margin, so a turbo that trades WER for
loops fails the plan rather than winning it.

**Multilingual checkpoints against `.en`-tuned thresholds.** `large-v3` and
turbo are multilingual; `language="en"` is fixed (`model.py:112`), so no
detection confound, but their `no_speech_prob` distribution differs from an
`.en` model's, and it meets a fixed `silence_threshold = 0.6`
(`config.py:259`) in `_assemble` (`model.py:207-227`). The failure mode is
extra empties, caught by guard 5 / `forbid_empty_regressions`. A model that
fails **only** on empties is reported as "may need a per-model
`silence_threshold`" and pointed at `Q06`; it is not re-run with a different
threshold here.

**Alignment heads / `word_timestamps`.** `word_timestamps=True`
(`model.py:124`) makes faster-whisper call `self.model.align(…)`
(`faster_whisper/transcribe.py:1709`), which needs `alignment_heads` in the
CT2 `config.json` — verified present for the shipped medium.en. A conversion
lacking them fails on every clip. The step-3c single-clip smoke catches this
in seconds instead of after 700 failures, and the model is excluded rather
than accommodated.

**Download allow-list.** `download_model` fetches a fixed pattern set
(`model.py:246-255`). A repo whose weights are sharded or named otherwise
"downloads" successfully and then fails to load; again, 3c catches it.

**Corpus validity.** LibriSpeech `test-clean` is read speech from 40
speakers, not this owner's dictation on this microphone. A cross-model WER
ordering measured on it may not transfer, and the absolute numbers are not
comparable to published LibriSpeech WERs (`HARNESS.md` §5.1). The `tail` and
`cue` lanes are synthetic proxies for two of the three symptoms. The mitigation
is a `user` or `pseudo-gold` lane (`HARNESS.md` §2.4) — out of scope here, and
a strong candidate for confirming any recommendation before it ships.

**Cache growth.** Four candidates add ≈6 GB to a shared HF cache, and they stay
there: step 6 lists them with their sizes in the Outcome and deletes nothing.
Reclaiming the space is the owner's call, and the shipped model is excluded from
the list so it can never be the one reclaimed by mistake.

**Invariant checklist** (`HARNESS.md` §9), restated:

- **No transcript text** anywhere but `clips.jsonl` under `build/`. This plan
  additionally redirects the step-3c smoke's stdout to `/dev/null`, because
  `stenographer transcribe` prints the transcript
  (`cli/commands/transcribe.py:107-108`). The Pareto script reads
  `clip_scores` only. `q12-notes.json`, `pareto.md`, the variant and
  thresholds files and this document's Outcome section are numbers, ids and
  option names only.
- **No network in the ASR path.** `local_files_only=True` stays
  (`model.py:87`); every invocation except step 3b sets `HF_HUB_OFFLINE=1`;
  the runner writes `feedback.update_check = false` into every temp config
  (`HARNESS.md` §3). Step 3b is `stenographer model download` — the one
  command permitted to download (`AGENTS.md:213`) — and nothing here fetches
  weights by any other route.
- **No platform imports.** This plan adds no code; the harness's import rules
  are unchanged.
- **Test policy** (`AGENTS.md` hard rule 4): no new mocks, no new tests. The
  only new artifacts are JSON inputs and a `build/`-local script.
- **Fixed behaviour stays fixed.** No `DecodeOptions` field is touched; user
  config still has exactly 23 keys; `asr.model` is an existing key with no
  schema change (`config.py:196`).
- **Venv only.** Every command above is `.venv/bin/…`.

## 9 Deliverables & follow-through

**Always** (accept or deny): append an "Outcome" section to this file with,
per model — repo id, resolved revision sha, download bytes and wall time,
harness exit code and run id, the full metric list of §6 including the
per-lane split — followed by the §5 Pareto table verbatim and the plan-level
verdict line. Copy each run's `verdict.json` to
`docs/experiments/results/Q12-<run-id>.json`. Numbers, ids and option names
only. Set Status to `accepted` or `denied`.

**On ACCEPT the deliverable is a recommendation, and the default change is a
fork for the owner — not an automatic edit.** Changing `asr.model` is not a
one-line change; the executing agent writes the ripple list into the Outcome
section and stops:

- `src/stenographer/config.py:253` — the annotated template's `model = …`.
- `src/stenographer/config.py:308` — `Config.defaults()`.
- `tests/test_config.py:31` — asserts the default id.
- `tests/transcribe/test_transcribe_smoke.py:36` and `:64` — `_MODEL_ID`, and
  the comment asserting the default is a full, non-distil model.
- `tests/transcribe/test_worker_smoke.py:35` — `_MODEL_ID`.
- `AGENTS.md:236-237` — the hard-rule-5 hotword sentence ("why the default is
  `faster-whisper-medium.en`"). A distil recommendation **rewrites the
  invariant itself**; a full-model recommendation only renames the model.
- `AGENTS.md:365` — "The ASR model (~1.5 GB) …"; update the size.
- `README.md:100` — "approximately 1.5 GB model download"; update the size.
- **Existing users are unaffected by a default change.** Config is fixed with
  no migrations (`AGENTS.md` hard rule 9) and `asr.model` is written into
  every config file `setup` has ever produced (`config.py:253`), so anyone who
  has run setup keeps the old model until they edit it or run
  `setup --default`. A recommendation therefore needs a README note, not a
  migration — and it means the new model must be downloaded by each user
  (`stenographer model download`).
- **Re-baseline** (`HARNESS.md` §7.3 case 1) after the change merges to `dev`:
  the shipped defaults moved, so every other plan's reference must be rebuilt
  — ≈5.5 h. Sequence it as the last accepted change of a batch.
- **Acceptance gates** (`AGENTS.md`, real machine, before dev → main): the
  full integration suite; real dictation end-to-end in `hold`, `toggle` and
  `hybrid`; a cold-start dictation that retains its opening words; and an
  inspection of `stenographer.log` showing metrics but no transcript. A model
  change moves cold-start timing, so the cold-start gate is the load-bearing
  one.

**On DENY**: no source file changes at all. The Outcome table stands as the
recorded evidence that `medium.en` is on the front for these three symptoms on
this GPU, and `S01`/`S02` own the remaining latency questions.

## 10 Out of scope

- `asr.beam_size` (`Q03`) and `asr.compute_type` (`Q04`) — inherited here, not
  varied; the one exception is §8's labelled OOM contingency.
- Every decode-stack knob: temperature fallback (`Q01`), VAD grid (`Q02`),
  repetition penalty (`Q05`), the `_assemble` no-speech gate (`Q06`),
  `hallucination_silence_threshold` (`Q07`), `initial_prompt` (`Q08`), the
  post-decode tail filter (`Q11`). A candidate that only needs a different
  knob is reported and handed to that plan.
- Speed decomposition (`S01`), batched inference (`S02`), idle unload
  (`S03`) — this plan reports `load_ms`/`decode_ms` as ranking inputs, not as
  a latency investigation.
- Hotword *quality* on any candidate: no hotword corpus exists. The distil
  hotword loss is taken from `AGENTS.md:236-237` as a documented invariant,
  not re-measured.
- Other checkpoints — `distil-large-v3`, `distil-large-v3.5`, `large-v2`,
  `base.en`, `tiny.en` (`faster_whisper/utils.py:11-31`), and non-CT2
  backends, our own quantizations, or fine-tuning. If the front turns out flat
  between `small.en` and `medium.en`, a follow-up sweep down to `base.en` is
  the cheap next question; it is a new plan, not an extension of this one.
- Multilingual use: the product is English-only and `language="en"` is fixed
  (`model.py:112`).
- Real-microphone confirmation of any recommendation (`X01`-style, owner
  present) — recommended before shipping, but not part of this hands-off run.
