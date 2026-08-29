# Q04 — compute type on CUDA

Status: planned (2026-08-29)

Baseline for all `file:line` citations: `dev` @ `a1b9807` (v0.11.6),
faster-whisper 1.2.1, CTranslate2 4.8.1, in the repo venv. Reference machine:
RTX 3080 Laptop (8 GiB), `ctranslate2.get_cuda_device_count() == 1`.

## 1 Hypothesis

Setting `asr.compute_type = "float16"` reduces `load_ms_p50` by ≥ 40 %
relative on the `base` + `tail` lanes without moving `wer_mean` by more than
+0.002, `rtf_p95` by more than ×1.25, or `trailing_junk_rate` above the
plan-level parity bound of §6.4.

## 2 Symptom & mechanism

**Symptom.** README's list, items (3) and (4): a high general hallucination
rate, and the first utterance after a cold start waiting ≈ 4 s
(`lock_wait_ms=4048` in the log). Item (4) is the target here; item (3) is the
guard — a speed win that costs transcript quality is not a win.

**Mechanism.** The shipped default is `compute_type = "int8"`
(`src/stenographer/config.py:309`, template comment at `config.py:254`), passed
straight into the CTranslate2 model constructor
(`src/stenographer/transcribe/model.py:82-88`) and timed by the
`asr: model_loaded elapsed_ms=…` line at `model.py:91-95`. The same value
reaches the daemon's ASR child at `src/stenographer/transcribe/worker.py:223`
and is echoed into the startup banner at `src/stenographer/daemon.py:793`.

The cached model is stored in half precision: the CTranslate2 `model.bin` for
`Systran/faster-whisper-medium.en` is 1 527 904 330 bytes for a ≈ 769 M
parameter model — ≈ 1.99 bytes per parameter, i.e. `float16` weights.
Consequences at load:

- `float16` requires **no conversion pass**: the weights are memory-mapped and
  copied to the device as stored.
- `int8` requires a **quantization pass** over every weight at load time
  (float16 → int8 plus scales), which is where the measured difference lives.
- Any other target (`float32`, `bfloat16`) requires a **widening/conversion
  pass**, so none of them can be faster to load than `float16`.

Measured in-process cold loads on the reference machine: `float16` 0.7–1.2 s;
`int8` (resolved `int8_float16`) 1.9–2.8 s. The daemon child's own
`model_loaded` is 4.1–5.3 s because it additionally pays `multiprocessing`
spawn and import cost (`worker.py:273`, `worker.py:504-542`) — that component
is S01's subject, not this plan's.

**Resolution is not identity.** CTranslate2 resolves a requested compute type
against the device's supported set at load and silently substitutes the
nearest supported one, logging *"The compute type inferred from the saved
model is {}, but the target device or backend do not support efficient {}
computation. The model weights have been automatically converted to use the {}
compute type instead."* (verified in
`.venv/lib/python3.14/site-packages/ctranslate2.libs/libctranslate2-*.so.4.8.1`).
Verified supported sets on this machine, CTranslate2 4.8.1:

| Device | Supported compute types |
|---|---|
| `cuda` | `bfloat16`, `float16`, `float32`, `int8`, `int8_bfloat16`, `int8_float16`, `int8_float32` |
| `cpu` | `float32`, `int16`, `int8`, `int8_float32` |

So on this GPU a request for `int8` resolves to `int8_float16`: **`int8` and
`int8_float16` are the same variant** and only one is run (the control). The
plan verifies rather than assumes this, from the run's own
`environment.compute_type_requested` / `compute_type_resolved`
(HARNESS.md §4.3, §8.2 step 5). The CPU row is why §9's follow-through is a
fork and not an automatic default change: `float16` is **not** a supported CPU
type, so on a CPU-only host it resolves to `float32` — the slowest and most
memory-hungry option, where `int8` is the correct one.

## 3 Prerequisites

- **Harness pieces.** All of HARNESS.md §1: `scripts/asr_corpus.py`,
  `scripts/asr_metrics.py`, `scripts/asr_experiment.py` with the subcommands
  `preflight`, `baseline`, `run`, `compare`, and their pure tests green
  (`.venv/bin/pytest -m "not integration" tests/test_asr_*.py`).
- **Injection fields.** None. This is a **config-lane** plan: it varies
  `asr.compute_type` only, through the variant's `config` object
  (HARNESS.md §3). `decode` is `{}` in every variant, and
  `DecodeOptions.device` stays `"auto"` — setting any `decode` field would
  force the in-process engine (HARNESS.md §3, `engine: auto`) and destroy the
  cold `load_ms` this plan measures.
- **Corpus lanes.** `base` (100 clips) and `tail` (300 clips, produced by
  `Q09`). The `cue` lane is not used (§10).
- **Baseline.** `docs/experiments/baseline.json` present, `schema == 1`,
  `environment.device == "cuda"`, `environment.compute_type_requested ==
  "int8"`, and a `noise` block containing at least `wer_mean` and
  `trailing_junk_rate`. The baseline must have been produced with
  `--engine subprocess` (HARNESS.md §7.1) — a speed comparison across engines
  is refused (HARNESS.md §6.4).
- **Model cached**, CUDA visible, ≥ 1 GiB free under `build/` (preflight
  checks all three, HARNESS.md §8.2).
- **Nothing else on the GPU.** Record `nvidia-smi
  --query-compute-apps=pid,used_memory --format=csv` before starting; if
  another process holds > 1 GiB, stop and report rather than measuring under
  contention.

## 4 Variant matrix

All variants: `"engine": "subprocess"` (mandatory — only the subprocess engine
gives a cold `load_ms` per clip, HARNESS.md §3.1), `"decode": {}`,
`"repeats": 1`, `"tags_any": []`, `"tags_all": []`, `"plan": "Q04"`.

| # | Variant name | `config.asr.compute_type` | Lanes | Clips | Role | Expected verdict |
|---|---|---|---|---|---|---|
| 1 | `q04-int8-control` | `"int8"` | `base`, `tail` | 400 | Control / replication of the baseline | DENY (cannot beat itself) — **expected, not a failure** |
| 2 | `q04-float16` | `"float16"` | `base`, `tail` | 400 | The candidate | ACCEPT if the hypothesis holds |
| 3 | `q04-default` | `"default"` | `base` | 100 | Equivalence probe: does `"default"` resolve to `float16` on a fp16-stored model? | DENY on the base-lane threshold unless the load win alone carries it; the *resolved type* is the deliverable |
| 4 | `q04-float32-reference` | `"float32"` | `base` | 100 | Numerical reference: brackets how much WER `int8` quantization costs, so "parity" is a measured claim | DENY (loads and decodes slower) — **expected** |

Checked-in variant files, all under `docs/experiments/variants/Q04/`:

- `q04-int8-control.json`
- `q04-float16.json`
- `q04-default.json`
- `q04-float32-reference.json`
- `thresholds.json` (lanes `base`, `tail` — variants 1 and 2)
- `thresholds-base.json` (lane `base` — variants 3 and 4)

Variant file body, with `<name>`, `<compute type>` and `<lanes>` substituted
per the table:

```json
{
  "schema": 1,
  "name": "<name>",
  "plan": "Q04",
  "lanes": <lanes>,
  "tags_any": [],
  "tags_all": [],
  "engine": "subprocess",
  "repeats": 1,
  "config": {"asr": {"compute_type": "<compute type>"}},
  "decode": {}
}
```

### 4.1 Why each variant, and what is excluded

- **`int8` control (1).** Two jobs. (a) It documents the
  `int8 → int8_float16` resolution on the run that matters. (b) It is the
  **noise estimate for the target metric**: `load_ms_p50` has no entry in the
  baseline's `noise` block (HARNESS.md §7.1 records noise for `wer_mean`,
  `trailing_junk_rate`, `leading_miss_rate`, `decode_ms_p50` and
  `first_response_ms_p50` only), so this same-config replicate supplies it
  empirically — see §6.5. Without it a 40 % margin would rest on an unmeasured
  variance.
- **`float16` (2).** The hypothesis. Zero conversion at load, native Ampere
  tensor-core path, ≈ 1.5 GB of VRAM for `medium.en` on an 8 GiB card.
- **`default` (3).** `"default"` means "use the type inferred from the saved
  model", which for fp16-stored weights should be `float16` on a GPU that
  supports it. It is the only *device-adaptive* value in the allowed set, so
  whether it resolves to `float16` here decides whether it is even a candidate
  for a shipped default (§9). Base lane only: if it resolves to `float16` its
  quality numbers are a duplicate of variant 2, and the second load-time
  sample is a bonus.
- **`float32` (4).** Included, against the option of excluding it. It is the
  unquantized numerical reference: it is the only way to state "`float16`
  matches `int8`" as a bracketed measurement rather than an assertion — if
  `float32` and `int8` differ by less than the `wer_mean` guard, the corpus
  cannot resolve precision effects at all and every quality claim in this plan
  is a null result, which is itself worth knowing. VRAM ≈ 3.0 GB, fits the
  8 GiB card. Base lane only, and never a candidate default.
- **`int8_float16` — excluded as a duplicate.** It resolves to the same
  CTranslate2 type as `int8` on this GPU (§2). Running it would spend 30 GPU-
  minutes re-measuring the control. The equivalence is verified from the
  control's `environment` block (§6.5, guard G2).
- **`bfloat16` / `int8_bfloat16` — excluded, twice over.**
  1. **Blocked by config validation.** `ALLOWED_COMPUTE_TYPES`
     (`src/stenographer/config.py:18-20`) is
     `{int8, int8_float16, float16, float32, default}`. A variant rendering
     `compute_type = "bfloat16"` fails `Config.load` with a key-scoped
     `ConfigError`, which the runner treats as a harness error, exit 2
     (HARNESS.md §3). Running it at all needs a change under `src/` plus its
     tests — see the Fork D note in §9.
  2. **Dominated on both axes of this experiment.** The weights are stored
     `float16`, so `bfloat16` needs a conversion pass at load and cannot beat
     `float16`'s load time — the one thing this plan is trying to reduce. And
     `bfloat16` has 8 fewer mantissa bits than `float16` at the same Ampere
     (SM 8.6) tensor-core throughput, so it cannot beat `float16` on quality
     either; its advantage is dynamic range, which matters for training
     stability, not for a 769 M-parameter inference forward pass.

  The one scenario that would justify it is a `float16` **numerical-range
  failure** — fp16 overflow in the encoder, which shows up as NaN-driven
  garbage rather than mild WER drift. §6.5 guard G6 defines that trigger
  precisely; only if it fires does the conditional Stage B of §9 apply.

## 5 Procedure

Every command is run from the repository root with the repo venv. No step
requires a human. `scripts/asr_experiment.py`'s exact flag spelling is
authoritative: the agent runs `.venv/bin/python scripts/asr_experiment.py
run --help` once and uses the implemented spelling for the variant argument if
it is positional rather than `--variant`; nothing else below varies.

### 5.0 Environment check (before anything else)

```sh
nvidia-smi --query-gpu=name,persistence_mode,clocks.sm,temperature.gpu,memory.used \
  --format=csv > build/asr-experiments/q04-gpu-before.csv
nvidia-smi --query-compute-apps=pid,used_memory --format=csv
.venv/bin/python -c "import ctranslate2 as c; print(c.get_cuda_device_count(), sorted(c.get_supported_compute_types('cuda')))"
```

Stop and report if `get_cuda_device_count()` is `0`, if `float16` is absent
from the CUDA set, or if another process holds > 1 GiB of VRAM. `mkdir -p
build/asr-experiments` first if it does not exist.

### 5.1 Preflight

```sh
.venv/bin/python scripts/asr_experiment.py preflight
```

Exit `0` → continue. Exit `2` → stop and report the preflight reason verbatim
(missing model, corpus digest mismatch, no CUDA, dirty-tree baseline, disk).
Never work around a preflight failure.

### 5.2 Warm-up (discarded, once per variant, immediately before its run)

The **first** process to touch the GPU after an idle period pays CUDA context
creation and driver module load, and the first process to read `model.bin`
pays ≈ 1.46 GB of cold page-cache misses. Both land inside `load_ms`
(`src/stenographer/cli/commands/transcribe.py:74-77` times `Model(cfg.asr)`
alone), so an un-warmed first clip is a several-hundred-millisecond outlier at
the head of every run. Warm up with the variant's own compute type — the
quantization pass differs per type, and so does what gets cached.

```sh
mkdir -p build/asr-experiments/q04-warmup
for ct in int8 float16 default float32; do
  cat > build/asr-experiments/q04-warmup/$ct.toml <<EOF
[stenographer.asr]
compute_type = "$ct"

[stenographer.feedback]
update_check = false
EOF
done
```

Then, immediately before each variant's `run`, with `$ct` set to that
variant's compute type:

```sh
for w in $(ls build/asr-corpus/wav/base/*.wav | head -3); do
  STENOGRAPHER_CONFIG=build/asr-experiments/q04-warmup/$ct.toml \
  XDG_STATE_HOME=build/asr-experiments/q04-warmup/state \
  HF_HUB_OFFLINE=1 \
  .venv/bin/stenographer transcribe "$w" > /dev/null 2>&1
done
```

Three invocations, ≈ 15 s. Their output is discarded and they are not scored.
A non-zero exit here means the environment is broken — stop and report; do not
proceed to the measured run.

### 5.3 The four runs, in this order

Order matters: the control runs first, so a machine that has already drifted
is caught before 60 GPU-minutes are spent.

```sh
# 1 — control (warm up with ct=int8 first)
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q04/q04-int8-control.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q04/thresholds.json

# 2 — the candidate (warm up with ct=float16 first)
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q04/q04-float16.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q04/thresholds.json

# 3 — resolution probe (warm up with ct=default first)
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q04/q04-default.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q04/thresholds-base.json

# 4 — numerical reference (warm up with ct=float32 first)
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q04/q04-float32-reference.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q04/thresholds-base.json
```

**Exit-code handling, per run:**

| Run | `0` | `1` | `2` |
|---|---|---|---|
| 1 control | Unexpected — the control cannot beat itself by 40 %; treat as a harness or baseline-integrity problem, stop, report | **Expected.** Continue; only its numbers matter (G1, G2, G5) | Stop, report |
| 2 float16 | Candidate accepted, subject to G3–G6 | Candidate denied; still run 3 and 4, then write the Outcome | Stop, report |
| 3 default | Note it; the resolved type is what this run is for | Expected; continue | Stop, report |
| 4 float32 | Unexpected; note it and continue | **Expected.** Continue | Stop, report |

After each run, record the run directory
(`build/asr-experiments/<run-id>/`). Then:

```sh
nvidia-smi --query-gpu=clocks.sm,temperature.gpu --format=csv \
  >> build/asr-experiments/q04-gpu-after.csv
```

### 5.4 Plan-level guards

`HARNESS.md` §6.1's `guards` array is the canonical mechanism, and every guard
below that reads an ordinary aggregate belongs in `thresholds.json` as one row.
The script here is the **fallback**: it keeps this plan runnable if the
foundation commit has not landed `guards` yet, and it also prints numbers the
verdict line does not carry.

After all four runs, evaluate §6.5's guards with this command, once per
candidate run directory (`$RUN` = that directory):

```sh
.venv/bin/python - "$RUN" <<'PY'
import json, pathlib, sys
run = json.loads((pathlib.Path(sys.argv[1]) / "result.json").read_text())
base = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
noise = base.get("noise", {})
a, b = run["aggregates"], base["aggregates"]
env = run["environment"]
junk_bound = max(0.02, 2 * noise.get("trailing_junk_rate", 0.0))
print("requested", env["compute_type_requested"], "resolved", env["compute_type_resolved"])
print("device", env["device"], "cuda_device_count", env["cuda_device_count"])
for k in ("load_ms_p50", "load_ms_p95", "first_response_ms_p50",
          "decode_ms_p50", "rtf_p95", "wer_mean", "wer_corpus",
          "trailing_junk_rate", "leading_miss_rate", "empty", "errors"):
    print(f"{k}: baseline={b.get(k)} run={a.get(k)}")
print("G3 trailing_junk ok:",
      (a["trailing_junk_rate"] - b["trailing_junk_rate"]) <= junk_bound,
      f"(bound +{junk_bound:.4f})")
print("G4 empties ok:", a["empty"] <= b["empty"], "G4 errors ok:", a["errors"] <= b["errors"])
PY
```

Numbers only; the command reads no text field and prints none.

## 6 Metrics & accept/deny

### 6.1 Target

`load_ms_p50`, direction `lower`, margin `0.40`, `margin_kind` `relative` —
the run must be at least 40 % below the baseline's `load_ms_p50`. Computed
over `cold == true` clips only, which for the subprocess engine is every clip
(HARNESS.md §3.1, §4.2).

### 6.2 `thresholds.json` (verbatim)

`docs/experiments/variants/Q04/thresholds.json` — variants 1 and 2:

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.25,
  "forbid_empty_regressions": true,
  "target": {
    "metric": "load_ms_p50",
    "direction": "lower",
    "margin": 0.40,
    "margin_kind": "relative"
  },
  "lanes": ["base", "tail"],
  "min_clips": 400
}
```

`docs/experiments/variants/Q04/thresholds-base.json` — variants 3 and 4:

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.25,
  "forbid_empty_regressions": true,
  "target": {
    "metric": "load_ms_p50",
    "direction": "lower",
    "margin": 0.40,
    "margin_kind": "relative"
  },
  "lanes": ["base"],
  "min_clips": 100
}
```

### 6.3 Why 40 %

The measured in-process cold loads are `float16` 0.7–1.2 s against `int8`
1.9–2.8 s — a 37 % reduction in the worst pairing (1.2 vs 1.9) and 60 % at the
midpoints. The subprocess engine adds a per-process CUDA-context term that is
common to both types and therefore *dilutes* the ratio: with a common term
`c ≈ 0.5–1.0 s`, the expected subprocess reduction is ≈ 45–55 %. A 40 % bar
therefore sits below the expected effect but above the worst credible pairing,
so it is a real test rather than a formality; and it is high enough that a
merely marginal win cannot be used to argue for moving a shipped default. It
is also ≥ 4× the replication noise this plan measures for itself (§6.5, G1).

### 6.4 The harness guards (HARNESS.md §6.2)

Applied by `decide` and reflected in the exit code:

1. `run.wer_mean <= baseline.wer_mean + 0.002` — the quality-parity guard.
2. `load_ms_p50` improves by ≥ 40 % relative.
3. `rtf_p95 <= 1.25 × baseline.rtf_p95` — one-sided; a decode *speedup* is
   free.
4. No clip non-empty in the baseline is empty in the run.
5. No clip errored in the run that succeeded in the baseline.

**Conditional edit, applied before run 1 and only then.** If
`baseline.noise.wer_mean > 0.001`, the fixed `wer_mean_max_delta` of `0.002`
is below twice the measured baseline noise and would deny on noise alone: set
`wer_mean_max_delta` to `round(2 * baseline.noise.wer_mean, 4)` in **both**
thresholds files, and record the substituted value and its justification in
the Outcome section. Make no other threshold edit for any reason; in
particular, never relax a threshold after seeing a run's numbers.

If `validate_variant` refuses the thresholds because the baseline's `noise`
block has no `load_ms_p50` entry, fall back — in both files, before run 1 — to
`"metric": "first_response_ms_p50"` with `"margin": 0.30`, `"margin_kind":
"relative"`. Justification for the fallback bar: `first_response_ms_p50` is
`load_ms + decode_ms`, and with a short-clip decode of ≈ 0.6 s the baseline's
≈ 3.1 s load becomes ≈ 3.7 s of first response against `float16`'s
≈ 1.7 + 0.6 = 2.3 s, a ≈ 38 % reduction — so 30 % preserves the same
"below the expected effect, above the worst pairing" property on the diluted
metric. Record the substitution in the Outcome.

### 6.5 Plan-level guards (not expressible in `thresholds.json`)

`decide` evaluates exactly the five guards above; these six are evaluated by
§5.4's command and by reading `result.json`. **A run that exits `0` but fails
any of G1–G6 is a plan-level DENY**, recorded as such with the failing guard
named.

- **G1 — replication.** `|control.load_ms_p50 − baseline.load_ms_p50| /
  baseline.load_ms_p50 <= 0.10`. The control is the same configuration as the
  baseline, so anything larger means the machine (thermals, driver, page
  cache, background load) has drifted and no speed comparison against that
  baseline is sound. On failure: stop, report, and recommend a re-baseline
  under HARNESS.md §7.3 reason 4 rather than reinterpreting the numbers. This
  guard is also the empirical noise figure the 40 % margin is measured
  against.
- **G2 — resolution.** The control's `environment.compute_type_requested`
  is `"int8"` and `compute_type_resolved` is `"int8_float16"`; the candidate's
  are `"float16"` and `"float16"`. Any other pairing means the device is not
  the one this plan was written for — stop and report. (The documented
  exception is exactly this `int8 → int8_float16` mapping; a resolved type
  that differs from the requested type in any *other* way invalidates the
  variant, because the run then measured something the variant did not name.)
- **G3 — trailing junk parity.** `run.trailing_junk_rate −
  baseline.trailing_junk_rate <= max(0.02, 2 × baseline.noise.trailing_junk_rate)`,
  on `base` + `tail`. This is the hallucination-rate symptom the speed win must
  not buy. It is a plan-level guard because `thresholds.json` carries exactly
  one `target`, which this plan spends on `load_ms_p50`. (An alternative is a
  second `compare` invocation against a thresholds file whose target is
  `trailing_junk_rate` at margin `0.0`; use it only if `validate_variant`
  accepts a zero margin, since HARNESS.md §7.1 requires a margin ≥ 2× the
  recorded noise. The §5.4 command is the mechanism that always works.)
- **G4 — no quality cliff.** `run.empty <= baseline.empty` and
  `run.errors <= baseline.errors` in aggregate, in addition to the harness's
  per-clip empty-regression guard.
- **G5 — device.** `environment.device == "cuda"` and
  `environment.cuda_device_count == 1` in every run. HARNESS.md §6.4 already
  refuses a cross-device comparison; this makes the check explicit in the
  record.
- **G6 — `float16` range failure (the Stage B trigger).** Fires if the
  `float16` run shows `errors > 0` where the baseline had none, **or**
  `empty` at least 3 clips above the baseline, **or** `wer_mean` more than
  0.05 above the baseline. Mild WER drift is quantization noise; those three
  are the signature of fp16 overflow producing NaNs. Only a G6 firing makes
  `bfloat16` worth its config change (§9, Fork D).

### 6.6 Deciding the matrix

**Best accepted by target metric**, among the *candidate* variants only —
`q04-float16` and `q04-default`. Variants 1 and 4 are reference runs and are
never candidates whatever their exit code. If both candidates accept and
`q04-default` resolved to `float16`, prefer `q04-float16`: it names what it
gets, whereas `"default"` means a different type on a different host or a
differently quantized model. If no candidate accepts, the plan's status is
denied and §9's deny path applies.

## 7 Cost estimate

Per-clip subprocess cost is ≈ 1 s of interpreter + imports, plus the load,
plus the decode (HARNESS.md §8.4). Load differs per variant, which is the
point, so the arithmetic is done per variant rather than from the flat 4–5 s
figure:

| Run | Clips | ≈ s/clip (1 + load + decode) | Wall |
|---|---|---|---|
| 1 `q04-int8-control` (base+tail) | 400 | 1.0 + 3.0 + 0.6 ≈ 4.6 | ≈ 31 min |
| 2 `q04-float16` (base+tail) | 400 | 1.0 + 1.7 + 0.6 ≈ 3.3 | ≈ 22 min |
| 3 `q04-default` (base) | 100 | ≈ 3.3 | ≈ 6 min |
| 4 `q04-float32-reference` (base) | 100 | 1.0 + 3.5 + 1.2 ≈ 5.7 | ≈ 10 min |
| Warm-ups | 4 × 3 | ≈ 5 | ≈ 1 min |
| Preflight (one cold load per run) | 4 | ≈ 10 | ≈ 1 min |

Total ≈ 71 min. **Budget 1 h 45 min** of uninterrupted GPU time; nothing else
may use the GPU during it.

Disk: four run directories. Each holds `clips.jsonl` (≈ 1 KB × clips ≈ 0.4 MB
at 400 clips), the small JSON/Markdown outputs, and `state/stenographer.log`,
which is the shipped rotating sink capped at 5 MiB × 3 = 15 MiB — so ≤ 20 MB
per run, **≈ 80 MB total**, plus the warm-up state directory. Budget 200 MB
under `build/`, on top of the corpus that already exists (base ≈ 24 MB, tail
≈ 100 MB). No new download: the corpus and the model are prerequisites.

## 8 Risks, confounds, invariants

### 8.1 CPU fallback (the decisive risk for the default)

**Verified**, CTranslate2 4.8.1 on this machine:
`get_supported_compute_types("cpu")` is
`{float32, int16, int8, int8_float32}` — `float16` and `bfloat16` are absent.
CTranslate2 does not error on an unsupported request; it converts the weights
to the nearest supported type at load and logs the "automatically converted"
warning quoted in §2. For an fp16-stored model on a CPU-only host, that target
is `float32`: the slowest CPU path and ≈ 3 GB of RAM, where `int8`
(`int8_float32` after resolution) is the correct choice.

Consequences for this plan: none for the *measurement* (every run is on CUDA,
enforced by preflight and G5). Everything for the *conclusion*: an accepted
`float16` result is a statement about CUDA hosts only, which is why §9's
default change is a fork rather than a foregone conclusion. Windows is
currently a stub provider with no ASR path of its own, but the same config key
is shared vocabulary, so a default change would reach a future Windows host
that may have no CUDA at all.

### 8.2 The daemon's environment may differ from the shell's

The systemd user unit (`packaging/stenographer.service`) sets no
`Environment=` and inherits the user manager's environment, which is not the
login shell's: a `LD_LIBRARY_PATH` or CUDA library path set in a shell profile
is not visible to the daemon. The ASR child is a `multiprocessing` spawn from
the daemon (`src/stenographer/transcribe/worker.py:273`, `:504-542`) and
inherits that same environment. So the harness could measure a CUDA
`float16` win that the daemon never sees because it is silently running on
CPU — where `float16` would resolve to `float32` and be *worse* than today.

**Hands-off probe** (no human, no daemon restart, no service change), run once
before writing the Outcome:

```sh
systemd-run --user --wait --pipe --collect --same-dir \
  .venv/bin/python -c "import ctranslate2 as c; d=c.get_cuda_device_count(); print(d, sorted(c.get_supported_compute_types('cuda' if d else 'cpu')))"
```

This executes under the user manager, i.e. the daemon's environment. A `0`
device count there while the shell reports `1` means the finding must not be
applied to the daemon's config until that gap is closed, and the Outcome says
so.

**Confirming check from the shipped log, no new instrumentation.** The daemon
already logs `asr: model_loaded elapsed_ms=…` (`model.py:91-95`) and
`asr: decode_complete elapsed_ms=… audio_frames=…` (`model.py:146-155`), and
the per-utterance summary carries both. Real-time factor separates the two
devices by an order of magnitude: `medium.en` on this GPU decodes at
RTF ≈ 0.05–0.15, on 8 CPU threads at RTF ≈ 0.8–2.0. Reading `decode_ms`
against `audio_frames / 16000` in `~/.local/state/stenographer/stenographer.log`
tells the agent which device the daemon actually used, from numbers the log
already contains.

### 8.3 Other confounds

- **Thermal and clock drift over ~1.5 h.** Mitigated by running the control
  first (G1), by the `nvidia-smi` before/after snapshots in §5.0 and §5.3, and
  by the fact that both baseline and control are the same configuration.
- **Page cache.** The first process to read the 1.46 GB `model.bin` pays disk;
  later ones do not. Mitigated by the discarded warm-up (§5.2). If the machine
  has < 4 GiB of free RAM the cache may not hold the model between clips and
  `load_ms` will be dominated by I/O rather than by the quantization pass —
  record `free -m` alongside the GPU snapshot and note it if so.
- **VRAM contention.** 8 GiB also drives the desktop. `float32` at ≈ 3.0 GB is
  the tightest run; an allocation failure surfaces as per-clip errors, caught
  by G4 and by harness guard 5. §5.0 refuses to start under contention.
- **`decode_ms` is not free of the compute type.** `int8` GEMMs can be faster
  than `float16` at large batch, but this workload is beam 1 on short
  utterances and largely memory-bound, so the two should be close. The
  `rtf_p95 ≤ ×1.25` guard is the protection; a decode *regression* larger than
  that denies even with a large load win, which is correct — cold-start cost is
  paid once per model load, decode cost on every utterance.
- **A `float16` WER *improvement* is plausible** (it is numerically closer to
  `float32` than `int8` is) and is not a problem: guard 1 is one-sided.
- **`empty` and the gate.** Compute type cannot change the RMS speech gate
  (`src/stenographer/audio.py`, `speech_gate_stats`), which runs before decode
  on identical samples; any `empty` change comes from the VAD/no-speech path
  and is caught by G4.

### 8.4 Invariant checklist (HARNESS.md §9, restated)

- **No transcript text** anywhere but `clips.jsonl` under `build/`. This plan
  adds four variant JSONs and two thresholds JSONs, all numbers and option
  names; the §5.4 command reads and prints only numeric aggregates and the
  compute-type/device strings; the Outcome appended to this file is numbers
  and a verdict line.
- **No network in the ASR path.** Nothing here downloads. `Model` keeps
  `local_files_only=True` (`model.py:87`), the subprocess env sets
  `HF_HUB_OFFLINE=1`, and the warm-up configs set
  `feedback.update_check = false` so the daemon's one permitted metadata
  request is not even in play. The model must already be cached; preflight
  refuses otherwise and the harness never downloads.
- **No platform imports.** This plan runs existing harness code and the
  shipped `stenographer transcribe` CLI; it adds no Python.
- **Test policy** (`AGENTS.md` hard rule 4): nothing is mocked. The evidence
  is 1000 real subprocess decodes on real audio through the shipped code path.
- **Fixed behaviour stays fixed.** `decode` is `{}` in every variant, so
  `DecodeOptions()` is constructed at its pinned defaults throughout; the
  anti-hallucination stack is untouched. User config keeps exactly 23 keys in
  4 sections (`AGENTS.md` hard rule 9) — this plan varies the *value* of an
  existing key and, in its recommended follow-through, adds no key.
- **Venv only.** Every command above is `.venv/bin/...`.

## 9 Deliverables & follow-through

### On accept (`q04-float16` exits `0` and G1–G6 pass)

The measured claim is: *on this CUDA host*, `float16` cuts cold model load by
≥ 40 % at WER and trailing-junk parity. Turning that into a change is a fork,
because `float16` is not a supported CPU compute type (§8.1).

**Fork A — user-config change only (recommended).** No `src/` change, no
default change, no re-baseline. The owner's own
`~/.config/stenographer/config.toml` gets `compute_type = "float16"` under
`[stenographer.asr]`, and README's *Configure* section (`README.md:92-121`)
gains a short note: on a CUDA host, `float16` loads the model appreciably
faster than the default `int8` at equal quality; on a CPU-only host keep
`int8`, because CTranslate2 resolves `float16` to `float32` there. Cite the
measured percentage from the run. Gate to re-run before dev → main: the
README-only change touches no behaviour, so the standard quick loop (ruff,
unit suite, `--help`) suffices; if the owner also changes their own config,
`AGENTS.md`'s "real dictation end-to-end in `hold`, `toggle`, and `hybrid`
modes" plus the cold-start-retains-opening-words check apply to their machine,
not to the repository.

*Why recommended:* it captures the entire win for the machine the measurement
was made on, costs one README paragraph, and cannot regress a host this plan
did not measure.

**Fork B — change the shipped default to `float16`.** Files, exactly:

- `src/stenographer/config.py:309` — `compute_type="int8"` → `"float16"`.
- `src/stenographer/config.py:254` — the annotated template line
  `compute_type = "int8"` and its trailing choice comment.
- `tests/test_config.py:32` — `assert d.asr.compute_type == "int8"`.
- `tests/cli/test_setup.py:268` — the `"  compute_type = int8"` summary row.
- `README.md:92-121` — the *Configure* section, plus a CPU-host caveat.
- `AGENTS.md` — hard rule 5 gains a sentence stating the default compute type
  and the CUDA/CPU asymmetry, in the same commit as the code (the file's own
  rule).
- Re-baseline under HARNESS.md §7.3 reason 1 (the shipped defaults moved), in
  its own commit touching only `docs/experiments/baseline.json`.
- Acceptance gates before dev → main (`AGENTS.md`): the integration suite
  green, real dictation end-to-end in `hold`, `toggle` and `hybrid`, and the
  cold-start check that a first dictation retains its opening words with
  `stenographer.log` showing metrics and no transcript.

*Why not recommended:* it silently degrades every CPU-only host from the
CPU-optimal `int8` to `float32` (§8.1), for a benefit only CUDA hosts see, and
Windows — a target platform with no ASR backend yet — is the likeliest
CPU-only host.

**Fork C — a device-aware default.** The genuinely correct fix if the default
is to move: resolve `int8` on CPU and `float16` on CUDA at load. Note that
`compute_type = "default"` is **not** this: it means "the type stored in the
model file", which is `float16` for this model and therefore resolves to
`float32` on CPU as well (variant 3 measures the CUDA half of that claim).
A real device-aware default is new behaviour in `Model.__init__`
(`model.py:82-88`) plus a decision about what the config value `"int8"` then
means, so it is out of scope here and belongs in its own plan. Record it in
the Outcome as an open question; do not implement it under this plan.

Whichever fork: append an **Outcome** section to this file with the verdict
line for each of the four runs, their run ids, the `load_ms_p50` /
`first_response_ms_p50` / `wer_mean` / `trailing_junk_rate` figures, the G1
replication delta, the `compute_type_resolved` string for each variant, and
the §8.2 probe result. Numbers only. Set Status to `accepted`.

### On deny

Append the same **Outcome** section with the verdict lines and run ids, copy
each `verdict.json` to
`docs/experiments/results/Q04-<run-id>.json`, and set Status to `denied`.
Numbers only. If the denial was on the load-time margin rather than on
quality, record the achieved percentage: a 25 % win is still a real fact for
S01, which will be measuring the same load from the other end.

**Fork D — conditional Stage B (`bfloat16`), only if G6 fired.** Only a
`float16` numerical-range failure justifies it (§4.1). It requires, before any
run: adding `bfloat16` (and, if `int8_bfloat16` is also to be tested,
that name) to `ALLOWED_COMPUTE_TYPES` at `src/stenographer/config.py:18-20`,
updating the template choice comment at `config.py:254`, and extending
`tests/test_config.py`'s validation cases (`tests/test_config.py:233` is the
rejection case for an unknown value). That widens a shipped, user-facing
validation surface to run an experiment, which is a decision for the owner and
not something this plan authorizes: if G6 fires, stop and report it as a fork
rather than editing `src/`.

## 10 Out of scope

- **The rest of the ≈ 4 s cold start.** `multiprocessing` spawn, interpreter
  start-up and imports in the ASR child (`worker.py:273`, `:504-542`) are the
  larger share of the daemon's 4.1–5.3 s `model_loaded`. Decomposing and
  attacking that is **S01**; this plan only removes the quantization pass
  inside it.
- **`asr.idle_unload_seconds` and the reload penalty** — **S03**.
- **Model choice**, including pre-quantized int8 checkpoints (which would load
  without any conversion pass and could beat `float16` on load) and distil
  variants — **Q12**. This plan holds `asr.model` fixed at
  `Systran/faster-whisper-medium.en`; HARNESS.md §6.4 refuses a comparison
  across models outside Q12.
- **`asr.beam_size`** — **Q03**. Held at the shipped `1`.
- **Batched inference** — **S02**.
- **Any decode-stack parameter.** `decode` is `{}` throughout; VAD, thresholds,
  penalties and the token budget belong to Q01/Q02/Q05/Q06/Q07/Q11.
- **The `cue` lane and leading-word loss** — **Q10**/**Q02**. Compute
  precision has no plausible mechanism for cue bleed or capture onset, and the
  extra 300 clips per variant would cost ≈ 25 min each for a null result.
- **CPU-only tuning**, `asr.cpu_threads`, and the correct compute type for a
  CPU host. §8.1 establishes the constraint that shapes §9's fork; measuring
  the CPU side needs `--allow-cpu` and a separate CPU baseline that is never
  comparable to this one (HARNESS.md §6.4).
- **Multi-GPU and any GPU other than the reference RTX 3080 Laptop.**
