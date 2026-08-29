# S01 — first-utterance (cold-start) latency

Status: planned (2026-08-29)

Baseline for every `file:line` citation: `dev` @ `a1b9807` (v0.11.6),
faster-whisper 1.2.1, CTranslate2 4.8.1, Python 3.14 in the repo venv, RTX 3080
Laptop (8 GiB).

This plan is executed end-to-end by an agent. No step needs a human.

## 1 Hypothesis

Loading the Silero VAD session during the model-load window and switching
`asr.compute_type` to the value `Q04` settles reduces `press_to_ready_ms` p50
by ≥ 30 % on the cold-start rig, with byte-identical transcripts on the
20-clip check set, no `wer_mean` change, and no violation of the press-lazy
model-load invariant.

Secondary, decided separately (§4 V3/V7, §6.4): spawning the ASR child — and
importing `faster_whisper` in it — at daemon start rather than at the first
press removes a further ≥ 0.5 s from `press_to_ready_ms`, at the cost of a
resident idle child. That variant is measured here but **cannot be accepted by
the harness alone**; it is a recorded-decision fork for the owner (§8.6).

## 2 Symptom & mechanism

### 2.1 Symptom

`README.md`/`docs/experiments/README.md` symptom (4): the first utterance after
a cold start waits ≈ 4 s. Observed on this machine, one cold utterance:

```
pipeline: utterance ... cold=1 lock_wait_ms=4048.6 decode_ms=702.9 capture_s=0.85
asr: model_loaded elapsed_ms=4215        (also 4077 and 5340 on other cold starts)
```

### 2.2 What `lock_wait_ms` actually measures — correct this before planning

`lock_wait_ms` is **not** the load time. It is the time `Worker.transcribe`
spent blocked on `Worker._lock`
(`src/stenographer/transcribe/worker.py:338-342`), which on a cold utterance is
the *remainder* of the warm-up thread's spawn + import + load after capture has
already ended:

1. The accepted press starts capture, plays `record_start`
   (`src/stenographer/daemon.py:499`), then starts the warm-up thread
   (`src/stenographer/daemon.py:500` → `_start_model_warmup`, `daemon.py:363-375`
   → `_warm_model`, `daemon.py:353-361` → `Worker.warmup`,
   `worker.py:321-335`).
2. `warmup` takes `_lock`, calls `_begin_request` (`worker.py:377-383`), which
   spawns the child because none exists (`_spawn`, `worker.py:504-542`), then
   `_ensure_model_loaded` (`worker.py:385-404`) puts `("load", utt)` and blocks.
3. The user releases; the pipeline thread runs the gate, then calls
   `Worker.transcribe` (`daemon.py:588`), which blocks on the same `_lock`.
   That block **is** `lock_wait_ms`.
4. When the warm-up finishes, `transcribe` acquires the lock, finds
   `_model_ready` set, so `_ensure_model_loaded` returns `False` and
   `load_ms` is `None` (`worker.py:346-350`) — which is why the cold line
   reports `cold=1` with no `load_ms` at all. `record.cold` was sampled before
   the lock (`daemon.py:582`), so it correctly says "this utterance paid for a
   load".

So the felt cold cost is `capture_s + gate + lock_wait_ms` ≈
`0.85 + ~0.01 + 4.05` ≈ **4.9 s from press to decode start**, and the shipped
log has no field that names it. Call it `press_to_ready_ms`; this plan's target
metric is that quantity, measured directly.

### 2.3 Where the 4.9 s goes — and a correction to the working assumption

The working assumption in `docs/experiments/README.md` was that ≈ 2 s of the
child's 4–5 s is non-weight overhead sitting *inside* the reported
`model_loaded elapsed_ms`. It is not. `model.py:73` imports `faster_whisper`
and `model.py:81` starts the clock **after** that import
(`src/stenographer/transcribe/model.py:71-95`), so `elapsed_ms` covers only:

- `download_model(..., local_files_only=True)` — a Hugging Face cache
  resolution, filesystem only
  (`.venv/lib/python3.14/site-packages/faster_whisper/transcribe.py:681-687`);
- `ctranslate2.models.Whisper(...)` — CUDA context creation, weight read,
  and int8 quantization
  (`faster_whisper/transcribe.py:689-698`);
- `tokenizers.Tokenizer.from_file` and the feature-extractor config read
  (`faster_whisper/transcribe.py:700-712`).

Measured on this machine, `import faster_whisper` is **343 ms** cumulative with
a warm page cache (`.venv/bin/python -X importtime -c "import faster_whisper"`;
`faster_whisper.audio` 222 ms of it, dominated by `av` 93 ms, `numpy` 118 ms,
`ctranslate2` 73 ms). Interpreter start plus the `multiprocessing` spawn
bootstrap plus unpickling `AsrConfig` adds roughly another 200–400 ms. So:

| Phase | Estimate | Where it is measured today |
|---|---|---|
| `Process.start()` → child interpreter running | ~0.1–0.3 s | nowhere |
| child imports `stenographer.transcribe.worker` + (on `load`) `faster_whisper` | ~0.4–0.6 s | nowhere |
| `WhisperModel(...)` | **4.08–5.34 s** | `asr: model_loaded elapsed_ms` |
| first `model.transcribe` incl. lazy Silero/onnxruntime load | 0.70 s | `decode_ms` |

The unexplained gap is therefore **inside `WhisperModel(...)`**: 4.1–5.3 s in
the daemon's child against 1.9–2.8 s for the same constructor in a fresh
interpreter with nothing else running (2.82 s for the first-ever load,
including CUDA context creation; 0.7–1.2 s at `float16`). Four candidate
causes, all testable by the rig in §3:

- **(a) Concurrent daemon CPU.** The load runs while the daemon is capturing:
  the PortAudio callback copies blocks, the overlay supervisor thread runs a
  32 ms Hann FFT over 18 bands per block
  (`src/stenographer/overlay/spectrum.py:161`), and the overlay helper process
  renders. int8 quantization on load is CPU work; `cpu_threads` (8 here) sets
  CTranslate2's `intra_threads` (`model.py:76-88` →
  `faster_whisper/transcribe.py:689-697`).
- **(b) Page cache.** ~1.5 GB of weights. The in-process figures were repeat
  loads; the daemon's genuine first load of the day is not.
- **(c) CUDA context creation, charged per process.** Unavoidable within a
  process, but paid again on every respawn — and
  `asr.idle_unload_seconds = 900` (`src/stenographer/config.py:260`) makes
  respawns routine, so this cost recurs many times a day. (`S03` owns the
  default; `S01` only measures the per-process price.)
- **(d) `intra_threads`.** 8 threads may be worse than 4 for a CUDA load whose
  CPU work is a one-shot quantization pass.

### 2.4 The Silero VAD load is charged to `decode_ms`, not to the load window

`faster_whisper.vad.get_vad_model()` is an `lru_cache`'d loader of
`silero_vad_v6.onnx` that imports `onnxruntime` and builds an
`InferenceSession` on first use
(`.venv/lib/python3.14/site-packages/faster_whisper/vad.py:288-313`), and it is
first called from inside `transcribe`
(`faster_whisper/vad.py:84`). With `asr.vad_filter = true`
(`config.py:258`) every first decode therefore pays it inside `decode_ms`
(702.9 ms total for 0.85 s of audio). Priming it during the *load* moves that
cost into a window that already overlaps capture, shortening the wait the user
feels without changing a single decode input — `get_vad_model` returns the same
cached object either way.

### 2.5 When the child is spawned — the fact the fork turns on

**The ASR child is spawned at the first accepted press, not at daemon
startup.** `Daemon.build` constructs the `Worker` object at
`src/stenographer/daemon.py:284`, but `Worker.__init__`
(`worker.py:257-285`) only creates a spawn context
(`worker.py:273`); no process exists until `_begin_request`
(`worker.py:377-383`) calls `_spawn` (`worker.py:504`), and the first caller is
`Worker.warmup` from `daemon.py:500`.

The consequence for candidate (a) in the task brief — "pre-import the heavy
modules in the child immediately at spawn, before the first job" — is that on
its own it **buys nothing**. The parent puts the `load` request essentially the
instant `Process.start()` returns (`worker.py:537` then `worker.py:391`), so
the child's `import faster_whisper` already begins as early as it can. Moving
the import from the `load` handler to `_child_main`'s top overlaps it with
nothing. Pre-importing is only worth anything if the *spawn* moves earlier —
i.e. to daemon start. That is the fork (§8.6).

## 3 Prerequisites

### 3.1 A new rig — `scripts/asr_cold_start.py` (prerequisite, not optional)

`HARNESS.md` §3.1's subprocess engine measures `stenographer transcribe`, which
loads the model **in-process in the CLI** (`cli/commands/transcribe.py:74-77`).
That is not the daemon's path: it has no `multiprocessing` spawn, no queue
round-trip, no warm-up thread, and no lock. Its `load_ms` cannot answer this
plan. S01 therefore needs its own rig, built to the same conventions
(`HARNESS.md` §1): development tooling under `scripts/`, never shipped, never
imported by `src/stenographer/`, writing only under gitignored `build/`,
invoked as `.venv/bin/python scripts/asr_cold_start.py <subcommand>`. It is not
`bench` and must never become a `stenographer` subcommand.

| Path | Role | Tests |
|---|---|---|
| `scripts/asr_cold_start.py` | Rig + CLI: `preflight`, `probe`, `baseline`, `run`, `compare`, plus `idle` and `idle-check` (S03 reuses the rig). | `tests/test_asr_cold_start.py` — pure helpers only. |
| `docs/experiments/variants/S01/*.json` | The variant files of §4. | — |
| `docs/experiments/variants/S01/thresholds.json` | §6.2. | — |
| `build/asr-coldstart/<run-id>/` | One directory per run (gitignored). | — |

It imports `scripts/asr_metrics.py`'s percentile helper rather than
re-implementing it (`sys.path.insert` at module scope, the
`tests/test_cue_audition.py:18-29` precedent). Add `scripts/asr_cold_start.py`
to `tests/platform/test_core_isolation.py`'s source grep alongside the other
three scripts.

**What it drives.** The rig imports the real
`stenographer.transcribe.worker.Worker`, `stenographer.config`,
`stenographer.transcribe.pipeline` and `stenographer.audio`, and reproduces the
daemon's cold sequence *exactly*:

1. `t_press` — `perf_counter()`.
2. Start a thread that calls `worker.warmup(utt)` — the daemon's warm-up
   thread (`daemon.py:363-375`).
3. Sleep `capture_s` (default `0.85`, the observed capture; `--capture-s`
   overrides) to reproduce the overlap the daemon gets for free, optionally
   with the contention generator (§3.3) running.
4. Call `worker.transcribe(samples, utt)` on another thread — the pipeline
   thread — and record its `Worker.last_timings` (`worker.py:369-373`).
5. `t_ready` — the moment `transcribe` acquired the lock, derived as
   `t_transcribe_call + lock_wait_ms`. `t_text` — `transcribe` returned.
6. `worker.shutdown()`, then **a fresh `Worker` for every repeat**: each
   repeat is a genuine cold start, child and CUDA context included.

Recorded per repeat, all milliseconds:

- `press_to_ready_ms` = `t_ready − t_press` — **the target metric**, the
  daemon's `capture_s + lock_wait_ms` written as one number.
- `press_to_text_ms` = `t_text − t_press`.
- `lock_wait_ms`, `load_ms`, `decode_ms` from `WorkerTimings`.
- `ct2_load_ms` — parsed from the `asr: model_loaded elapsed_ms=` line
  (`model.py:91-95`) in **the run's own `stenographer.log`**: the rig calls
  `setup_logging(env=…)` with `XDG_STATE_HOME=<run>/state` and correlates the
  line to an utterance by its `utt=` stamp. A handler the rig attaches to the
  `stenographer` logger **cannot** see the child's records — the child's listener
  targets the sinks `owned_handlers()` hands it, not the parent's logger
  (`worker.py:518-523`, `logging_setup.py:334-342`) — though such a handler does
  see the parent's own `worker: spawned pid=`, which is why the log file is the
  only sound source for this number.
- `overhead_ms` = `press_to_ready_ms − capture-overlap − ct2_load_ms` — the
  spawn + bootstrap + import residue. It is therefore computed **after** the run,
  once that log has been parsed, and is `null` for any utterance whose
  `model_loaded` line could not be correlated by `utt=`.
- `text_sha256` — SHA-256 of `transcript_text(result)` (§6.3). Never the text.

### 3.2 Isolating import time and CUDA time — `probe`

The end-to-end numbers above decide accept/deny. Attribution needs two more
measurements, both hands-off and neither requiring an edit to shipped code:

**Import time in the real child.** Run the whole rig with
`PYTHONPROFILEIMPORTTIME=1` in the environment (`-X importtime`'s env-var
form). `multiprocessing`'s spawned child inherits the environment and its
stderr, so the child's own import profile lands on the rig's stderr; the rig
redirects it to `<run>/importtime.txt` and its pure
`parse_importtime(text) -> dict[str, float]` sums the cumulative column for
`faster_whisper`, `ctranslate2`, `av`, `numpy`, `onnxruntime`. Enabled by
`--importtime`; off for timing runs, because the profiler itself perturbs them.

**CUDA context vs weight load** — `asr_cold_start.py probe`. A fresh
subprocess per repeat that, with no `Worker` and no daemon in play:

```
t0 → import ctranslate2                                   → t1
   → ctranslate2.get_cuda_device_count()                   → t2
   → ctranslate2.models.Whisper(path, device="cuda", compute_type=<ct>,
                                intra_threads=<n>)         → t3
   → the same construction a second time, same process     → t4
```

`t3−t2` is first-construction cost (context + weights + quantization);
`t4−t3` is the same work with the CUDA context and the page cache already
warm. Their difference sizes candidate (c). `path` comes from
`faster_whisper.utils.download_model(cfg.model, local_files_only=True)`, so no
network is touched (`HARNESS.md` §9). `probe` writes `probe.json`; it informs
the plan's conclusions and never feeds the verdict.

**Attribution, not verdict.** The mirror child in `probe` replicates the real
child's import graph but is not `_child_main`. Every accept/deny number comes
from the `Worker`-driven path of §3.1.

### 3.3 Contention generator (`--contend`)

To size candidate (a) without a microphone: a daemon thread that, at 20 Hz for
the duration of the simulated capture, calls the real
`stenographer.overlay.spectrum.analyze_spectrum` on a synthetic 32 ms block of
seeded Gaussian noise, mirroring the supervisor's per-block analysis
(`overlay/spectrum.py:161`; `overlay/supervisor.py:227-243`). Core, pure,
deterministic, no PortAudio, no helper process. It reproduces the *daemon-side*
CPU only; the overlay helper process is not simulated, so `--contend` is a
lower bound on real contention.

### 3.4 Other prerequisites

- **`Q04` decided.** `S01`'s V1/V6/V7 use whatever `compute_type` `Q04`
  accepted. If `Q04` denied every alternative, V1 is dropped and V6 ≡ V2; say
  so in the Outcome section rather than substituting a guess.
- **Model cached.** `stenographer.transcribe.model.is_model_cached(cfg.asr.model)`
  (`model.py:230-239`). The rig never downloads.
- **Check set.** 20 clips from the corpus `base` lane, the first 20 by sorted
  id, used only for the transcript-identity guard (§6.3). If
  `build/asr-corpus/manifest.json` is absent the rig refuses (exit 2) rather
  than synthesising audio: an identity guard over noise proves nothing.
- **No `docs/experiments/baseline.json` dependency.** S01's verdict rests on
  its own `coldstart-baseline.json` (§6.1). The corpus baseline is used only by
  the follow-through quality run (§9.3).
- **Injection fields.** None from `DecodeOptions`; V1 and V5 are config keys
  (`asr.compute_type`, `asr.cpu_threads`), V2/V3/V4 are code variants selected
  by an env var the rig sets (§4.1).

## 4 Variant matrix

### 4.1 How code variants are selected

V2, V3 and V4 are code changes, not config. To keep the rig honest about
measuring the *shipped* code path, the executing agent applies each as a real
edit to `src/stenographer/transcribe/worker.py` (and `model.py` for V2) on a
scratch branch, and the rig records `git rev-parse --short HEAD` and
`git status --porcelain` in every result. A variant JSON carries
`"patch": "<path under docs/experiments/variants/S01/patches/>"`; the rig
refuses to run (exit 2) if the named patch is not currently applied, which it
checks by `git diff --stat` against the recorded patch's file list. No
production code learns an experiment-only env switch.

### 4.2 The matrix

All variants: `repeats: 5`, `blocks: 3` (§6.1), `capture_s: 0.85`,
`contend: false` unless stated, engine = the S01 rig (there is no
`HARNESS.md` engine choice here; `HARNESS.md` §3.1's "S-series uses
`engine: subprocess`" governs the *corpus* harness, which S01 uses only in §9.3).

| # | Name | Change | Variant JSON |
|---|---|---|---|
| V0 | `s01-baseline` | Shipped defaults: `compute_type = "int8"`, `cpu_threads = 0` (→ 8), spawn context, VAD lazy, child spawned at press. | `variants/S01/s01-baseline.json` |
| C0 | `s01-baseline-contend` | V0 with `--contend`. Sizes candidate (a). Not a candidate change; never accepted. | `variants/S01/s01-baseline-contend.json` |
| V1 | `s01-compute-type` | `asr.compute_type` = the value `Q04` accepted (expected `float16`). Config only. | `variants/S01/s01-compute-type.json` |
| V2 | `s01-vad-preload` | In the child's `load` handler, after `Model(cfg)` succeeds, call `faster_whisper.vad.get_vad_model()` when `cfg.vad_filter` is true, inside its own `try` that logs a DEBUG failure and continues. Patch touches `worker.py:206-228` (or, better, a `Model.prime_vad()` in `model.py` so `worker.py` keeps no faster-whisper import). | `variants/S01/s01-vad-preload.json` |
| V3 | `s01-spawn-at-start` | The fork. `Worker.prespawn()` — spawn the child and have `_child_main` import `faster_whisper` at entry — called from `Daemon.run` after the capability gate. Rig simulates by calling `prespawn()` and waiting for child readiness before `t_press`. | `variants/S01/s01-spawn-at-start.json` |
| V4 | `s01-forkserver` | `multiprocessing.get_context("forkserver")` at `worker.py:273` with `set_forkserver_preload(["faster_whisper"])`. **POSIX only** — see §8.5. | `variants/S01/s01-forkserver.json` |
| V5 | `s01-cpu-threads-4` | `asr.cpu_threads = 4`. Config only; tests candidate (d). | `variants/S01/s01-cpu-threads-4.json` |
| V6 | `s01-combo` | V1 + V2. **The candidate the harness may accept on its own.** | `variants/S01/s01-combo.json` |
| V7 | `s01-combo-prespawn` | V1 + V2 + V3. Reported separately; needs the fork resolved. | `variants/S01/s01-combo-prespawn.json` |

Variant JSON schema (S01's own, schema 1):

```json
{
  "schema": 1, "name": "s01-combo", "plan": "S01",
  "repeats": 5, "blocks": 3, "capture_s": 0.85, "contend": false,
  "config": {"asr": {"compute_type": "float16"}},
  "patch": "patches/vad-preload.diff",
  "check_set": 20
}
```

`config` follows `HARNESS.md` §3 exactly: two-level, sections `asr`/`audio`
only, rendered into `<run>/config.toml`, passed via `STENOGRAPHER_CONFIG`, with
`[stenographer.feedback] update_check = false` written unconditionally and
`Config.load` validating it before the first repeat.

## 5 Procedure

Every command is run from the repository root. `.venv/bin/python` only.

```sh
# 0. Gates that must already be green (AGENTS.md, Commands).
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration"

# 1. Rig preflight: venv, model cached, corpus manifest, CUDA present, disk.
.venv/bin/python scripts/asr_cold_start.py preflight
#    exit 0 continue; exit 2 stop and report the printed reason.

# 2. Attribution probe (informational; feeds §2.3's table, not the verdict).
.venv/bin/python scripts/asr_cold_start.py probe --repeats 3 \
  --compute-type int8 --compute-type float16 --intra-threads 8 --intra-threads 4
.venv/bin/python scripts/asr_cold_start.py run \
  --variant docs/experiments/variants/S01/s01-baseline.json --importtime

# 3. Baseline: 3 blocks x 5 repeats of V0, with the per-block noise record.
.venv/bin/python scripts/asr_cold_start.py baseline \
  --variant docs/experiments/variants/S01/s01-baseline.json \
  --out docs/experiments/coldstart-baseline.json
#    exit 2 stops the plan. Record the printed p50 and noise.

# 4. Contention control (informational).
.venv/bin/python scripts/asr_cold_start.py run \
  --variant docs/experiments/variants/S01/s01-baseline-contend.json \
  --baseline docs/experiments/coldstart-baseline.json \
  --thresholds docs/experiments/variants/S01/thresholds.json
#    Any exit code is informational; C0 is never accepted.

# 5. Single-lever variants, in this order. Before each: apply the variant's
#    patch if it has one (git apply), confirm with `git diff --stat`; after
#    each: `git checkout -- src/` to restore the tree.
for v in s01-compute-type s01-vad-preload s01-cpu-threads-4 \
         s01-forkserver s01-spawn-at-start; do
  .venv/bin/python scripts/asr_cold_start.py run \
    --variant docs/experiments/variants/S01/$v.json \
    --baseline docs/experiments/coldstart-baseline.json \
    --thresholds docs/experiments/variants/S01/thresholds.json
done

# 6. Combinations.
.venv/bin/python scripts/asr_cold_start.py run \
  --variant docs/experiments/variants/S01/s01-combo.json \
  --baseline docs/experiments/coldstart-baseline.json \
  --thresholds docs/experiments/variants/S01/thresholds.json
.venv/bin/python scripts/asr_cold_start.py run \
  --variant docs/experiments/variants/S01/s01-combo-prespawn.json \
  --baseline docs/experiments/coldstart-baseline.json \
  --thresholds docs/experiments/variants/S01/thresholds.json
```

Exit codes, for every `run`:

- **0 (accept)** — record the run id and the verdict line; keep the patch in a
  branch commit; continue the matrix (a later variant may accept too; §6.4
  picks the winner).
- **1 (deny)** — restore the tree, append the verdict line to the unnumbered
  `## Outcome` section (`HARNESS.md` §10),
  copy `verdict.json` to `docs/experiments/results/S01-<run-id>.json`, and
  continue with the next variant. A denial is a result, not a failure.
- **2 (harness error)** — stop the whole plan, restore the tree, and report the
  printed reason. Never re-run a variant to get a different number; a
  legitimate re-run is only ever the whole matrix after fixing the rig.

Then, for the winning variant only, the quality confirmation of §9.3.

Ordering note: the rig interleaves nothing, so page-cache warmth grows
monotonically through a session (§8.2). The baseline's three blocks are run
**first, last, and in the middle** of the matrix — `baseline` writes block 0
at step 3, and the rig re-runs blocks 1 and 2 automatically after steps 5 and 6
(`--baseline-blocks-interleaved`, on by default), so the noise record spans the
whole session rather than its first minute.

## 6 Metrics & accept/deny

### 6.1 Baseline and noise

`docs/experiments/coldstart-baseline.json`, schema 1: the V0 aggregates plus a
`noise` block holding the max absolute spread of `press_to_ready_ms_p50`,
`press_to_text_ms_p50` and `ct2_load_ms_p50` across the three blocks of five.
Percentiles use `HARNESS.md` §4.2's nearest rank. Following `HARNESS.md` §7.1,
**a declared margin must be at least twice the recorded noise for its metric**,
and `validate_variant` enforces it.

The three observed individual cold loads (4215 / 4077 / 5340 ms) span 1.26 s,
≈ 26 % of their mean — which is precisely why the verdict is on the p50 of five
repeats across three blocks and not on a single number.

### 6.2 `thresholds.json`

`docs/experiments/variants/S01/thresholds.json`:

```json
{
  "schema": 1,
  "target": {
    "metric": "press_to_ready_ms_p50",
    "direction": "lower",
    "margin": 0.30,
    "margin_kind": "relative"
  },
  "guards": {
    "press_to_text_ms_p50_max_ratio": 1.00,
    "decode_ms_p50_max_ratio": 1.10,
    "transcripts_identical": true,
    "min_repeats": 15
  }
}
```

**This object form is rig-local and never passes through `decide`.** S01 runs on
its own rig against its own metrics (`press_to_ready_ms`, `ct2_load_ms`), not on
the corpus harness, so `scripts/asr_cold_start.py compare` reads this file itself
and `HARNESS.md` §6.1's `guards` **array** never sees it. The two spellings do not
compete because no file is ever read by both; a metric that ever needs deciding by
`decide` moves to the array form and this object shrinks accordingly.

### 6.3 The rule

Accept iff **all** of:

1. `run.press_to_ready_ms_p50 <= baseline.press_to_ready_ms_p50 * (1 - 0.30)`;
2. that improvement exceeds `2 x noise.press_to_ready_ms_p50` from §6.1;
3. `run.press_to_text_ms_p50 <= baseline.press_to_text_ms_p50` — the change may
   not move cost from the wait into the decode;
4. `run.decode_ms_p50 <= 1.10 * baseline.decode_ms_p50`;
5. **transcript identity**: for each of the 20 check-set clips, the SHA-256 of
   `transcript_text(result)` is byte-identical between baseline and run. Any
   mismatch is a *deny*, printed as the clip id and "hash differs" — never as
   text. (For V1 this guard **will** trip: changing `compute_type` changes
   arithmetic. §6.5.)
6. no repeat errored in the run that succeeded in the baseline.

`verdict.json` carries `accepted`, every guard with both values, the target
delta, and `hash_mismatches: [<clip id>, ...]`. Exit 0/1/2 per `HARNESS.md`
§6.3. `report.md` prints the same table on accept and on deny.

### 6.4 Choosing among accepted variants

**Best accepted by target metric**, not first-in-order — the matrix is
deliberately ordered from cheapest to most invasive, so first-wins would
under-shoot. Report every accepted variant's number; recommend the best one
whose §8.6 fork is *not* engaged (i.e. prefer V6 over V7 unless the owner
resolves the fork in favour of pre-spawning).

### 6.5 Why 30 %, and the V1 exception

Baseline `press_to_ready_ms` ≈ 4.9 s. The realistically available savings are
`float16` instead of `int8_float16` (in-process: 0.7–1.2 s vs 1.9–2.8 s, so
≈ 1.0–1.9 s) plus the VAD preload moving ≈ 0.2–0.4 s off the critical path into
the capture-overlapped window — together ≈ 1.2–2.3 s, or **25–47 %**. A bar
below 30 % would accept changes sitting inside the observed run-to-run spread
(§6.1); a bar much above 45 % would deny the entire realistic space. 30 %
relative, guarded by the 2x-noise rule, is the honest line.

**V1 exception.** `compute_type` changes numerics, so guard 5 cannot hold for
it. V1 (and V6/V7, which contain it) is therefore evaluated with
`transcripts_identical: false` in its own thresholds file
(`variants/S01/thresholds-compute-type.json`, identical but for that flag), and
the transcript question is delegated to `Q04`, which already decided it on the
full corpus with WER guards. If `Q04` denied every alternative compute type,
V1/V6/V7 drop to V2 alone and the 30 % bar almost certainly cannot be met by
V2 by itself — that outcome is a legitimate plan-level deny, recorded as such.

## 7 Cost estimate

Per repeat: spawn + import ≈ 0.6 s, load 1–5 s, simulated capture 0.85 s
(overlapped), decode ≈ 0.7 s, teardown ≈ 0.3 s → **≈ 6 s** at `int8`, ≈ 3 s at
`float16`.

| Step | Repeats | Wall |
|---|---|---|
| `preflight` | — | < 30 s |
| `probe` (2 compute types x 2 thread counts x 3 repeats x 2 constructions) | 24 loads | ≈ 2 min |
| `--importtime` run of V0 | 5 | ≈ 1 min |
| `baseline` (3 blocks x 5) | 15 | ≈ 2 min |
| C0 + V1 + V2 + V4 + V5 + V3 (15 each) | 90 | ≈ 8 min |
| V6 + V7 (15 each) | 30 | ≈ 2 min |
| Interleaved baseline blocks 1–2 | (counted above) | — |
| §9.3 quality confirmation (`asr_experiment.py run`, `base` lane, 100 clips, subprocess) | 100 | ≈ 8 min |

**Total ≈ 25 min wall**, plus the patch apply/restore cycles. Disk: run
directories a few MB each; `probe.json` and `importtime.txt` are kilobytes; the
corpus is already on disk from the foundation step. Budget 100 MB beyond what
`HARNESS.md` §8.4 already reserves. No new download.

## 8 Risks, confounds, invariants

### 8.1 CUDA context per process

Every respawn pays the context. `probe`'s `t4−t3` sizes it. If it dominates,
the honest conclusion is that S01 cannot remove it and the lever is
`asr.idle_unload_seconds` — which is **`S03`'s** question, not this plan's
(§10). Do not let an S01 variant quietly change that default.

### 8.2 Page cache and ordering

The first load of a session reads ~1.5 GB from disk; later ones do not. This
biases the *first* variant run pessimistically. Mitigations, all in the rig:
the baseline's three blocks are spread across the session (§5); every result
records `block_index` and session-relative start time; and `probe` reports the
first-vs-second construction delta so a page-cache-dominated session is
visible. The rig must **not** attempt `drop_caches` — it needs root, and a
plan step that needs root is a plan step that needs a human.

### 8.3 systemd environment vs the shell

The rig runs from an interactive shell; the daemon runs under
`packaging/stenographer.service` (`Type=simple`,
`ExecStart=%h/.local/share/stenographer/stenographer run`, a **PyInstaller
onedir bundle**, not the venv). Concrete differences that can move the numbers:
`LD_LIBRARY_PATH` and the CUDA/cuDNN libraries resolved from the bundle rather
than the venv; no login-shell environment; a systemd cgroup with its own CPU
accounting; a frozen interpreter whose `multiprocessing` spawn re-executes the
bundle rather than `sys.executable`. **The rig's numbers are therefore
comparative, not absolute**, and every result records
`{"context": "venv-shell"}`. The plan's acceptance gate (§9.4) closes this: the
accepted change must be confirmed once on the real installed daemon by reading
`lock_wait_ms` from `stenographer.log` on a genuine cold dictation.

### 8.4 A pre-imported or pre-spawned idle child costs memory

V3/V7 leave a child resident from daemon start. Measured cost to record in the
result: child RSS after import but before `WhisperModel` (expected ~250–400 MB
for numpy + av + ctranslate2 + tokenizers). A dictation daemon that idles all
day at +350 MB for a 0.5 s saving is a real trade, and the owner — not the
harness — makes it.

### 8.5 `forkserver` is a platform decision, not a free win

`multiprocessing.get_context("forkserver")` does not exist on Windows. Today
`worker.py:273` hardcodes `"spawn"`, which is portable, and
`tests/platform/test_core_isolation.py` deliberately exempts
`transcribe/worker.py` from the `PROCESS_MODULES` grep ("the worker child and
the helper process are their own processes, not the daemon's portable core").
That exemption permits process machinery in `worker.py`; it does **not**
license a POSIX-only constant there. If V4 wins, the start method becomes a
host concern and must move behind the platform boundary — a
`Platform.worker_start_method() -> str` on `platform/base.py`, `"forkserver"`
in `platform/linux/`, `"spawn"` in `platform/windows/` — per `AGENTS.md`
*Platform boundary*, "How to add or change host behaviour" (1)-(3). Forkserver
also forks a preloaded parent, so the child inherits CUDA-unsafe state if the
preload list ever touches CUDA: preload `faster_whisper` only, never
`ctranslate2.models`, and treat any CUDA error in a V4 repeat as a deny for V4,
not a harness error.

### 8.6 The fork the orchestrator must resolve — pre-spawn at daemon start

`AGENTS.md` hard rule 5: *"Model load is press-lazy (starts on the first
accepted recording, never at daemon startup) and intentionally silent so no cue
contaminates captured audio."*

- **What V3 does:** spawn the child and import `faster_whisper` in it at daemon
  start. It does **not** construct `WhisperModel`; no weights are read, no CUDA
  context is created, no cue plays, no audio is captured.
- **Reading in favour:** the rule's stated purpose is that the load is silent
  so no cue contaminates captured audio, and that startup does not do the heavy
  thing. V3 loads no model and plays no cue; the model load remains strictly
  press-lazy. On this reading V3 is compatible.
- **Reading against:** "never at daemon startup" plainly covers the whole
  worker bring-up, and V3 moves ~0.6 s of CPU and ~350 MB of RSS to startup,
  which is exactly the lightness the rule protects. On this reading V3 needs a
  recorded decision.
- **My reading:** the second. `AGENTS.md` says cut/authorized lifecycle
  decisions are recorded *before* the code changes, and V3 is a lifecycle
  change to when the ASR child exists. **Recommendation:** do not accept V3 or
  V7 on the harness's word. Measure them, report the saving and the RSS, and
  let the owner decide; if accepted, the same commit adds a sentence to
  `AGENTS.md` hard rule 5 and the "Already authorized" list, e.g. *"the ASR
  child may be spawned and pre-import its stack at daemon start; the model load
  itself stays press-lazy and silent."*
- **V2 and V4 are not the fork.** Both act strictly after the press, inside the
  existing warm-up window. V2 loads no Whisper weights at startup and changes
  no decode input. V5 and V1 are config values.

### 8.7 Other confounds

- **GPU clocks / thermals.** A cold GPU boosts differently. The rig records
  `nvidia-smi --query-gpu=clocks.sm,temperature.gpu --format=csv,noheader` per
  repeat when the binary exists, and omits the field when it does not. It never
  fails a run over a missing binary.
- **`decode_ms` is a single 0.85 s utterance.** It is a guard here, not a
  measurement; the corpus harness owns decode latency.
- **V2 changes what fails first.** If the VAD session fails to build, today the
  failure surfaces during decode; with V2 it surfaces during load. The patch
  must catch and DEBUG-log it and continue, so a preload failure can never turn
  a working dictation into a failed one.

### 8.8 `HARNESS.md` §9 invariant checklist, restated

- **No transcript text** anywhere the rig writes. S01 stores only
  `text_sha256`; it has no `clips.jsonl` equivalent and writes no text at all —
  a stricter position than `HARNESS.md` §4.1 allows, and deliberately so.
- **No network in the ASR path.** `local_files_only=True` stays
  (`model.py:87`); the rig sets `HF_HUB_OFFLINE=1` for the child; `probe`
  resolves the model path with `download_model(..., local_files_only=True)`.
  The rig opens no socket at all, so no `AGENTS.md` download sentence changes.
- **No platform imports.** `scripts/asr_cold_start.py` imports core only
  (`stenographer.config`, `stenographer.transcribe.*`, `stenographer.audio`,
  `stenographer.overlay.spectrum`) and never `stenographer.platform.linux`,
  `evdev`, `fcntl`, or any name in `test_core_isolation.py`'s `BLOCKED`. The
  *child* resolves the provider through `current_platform()` exactly as the
  daemon's child does (`model.py:74-79`) — that is the core dispatcher, which
  is allowed. Add the script to that test's grep.
- **Test policy** (`AGENTS.md` hard rule 4): only the pure helpers get unit
  tests, each seen to fail first; nothing mocks `multiprocessing`, `Worker`,
  the model, or a subprocess. Timings are not unit-testable and are not
  unit-tested (§9.5).
- **Fixed behaviour stays fixed.** No `DecodeOptions` field is used; user
  config still has exactly 23 keys in 4 sections; the anti-hallucination stack
  is untouched.
- **Venv only**, SPDX header on `scripts/asr_cold_start.py` and
  `tests/test_asr_cold_start.py`, ruff clean (`E,F,I,B,UP,N,SIM,RUF`, line
  length 100, py312 target).
- **Privacy in logs** (hard rule 6): the rig's own output is numbers,
  identifiers and hashes; the child's `stenographer` records reaching the run's
  `stenographer.log` are the shipped ones, already lengths-only.

## 9 Deliverables & follow-through

### 9.1 Always (accept or deny)

- `scripts/asr_cold_start.py`, `tests/test_asr_cold_start.py`,
  `docs/experiments/variants/S01/*.json` (+ `patches/`), and
  `docs/experiments/coldstart-baseline.json`, committed as `feat:` — the rig is
  a deliverable even if every variant denies.
- `scripts/asr_cold_start.py` added to
  `tests/platform/test_core_isolation.py`'s source grep, in the same commit.
- One sentence in the `AGENTS.md` `packaging/`, `scripts/` row naming the rig
  alongside `cue_audition.py` and the `HARNESS.md` scripts.
- The unnumbered `## Outcome` section appended to this file after §10
  (`HARNESS.md` §10): the verdict line and run id for
  every variant, numbers only; `verdict.json` copied to
  `docs/experiments/results/S01-<run-id>.json` for each deny; Status updated.
- The §2.3 decomposition table filled in with the measured `probe` numbers, so
  the next reader does not have to re-derive where the 4.9 s went.

### 9.2 On accept of V2 (VAD preload)

- Add `Model.prime_vad()` to `src/stenographer/transcribe/model.py` (beside
  `Model.__init__`, `model.py:72-95`): imports
  `faster_whisper.vad.get_vad_model` and calls it, so `worker.py` gains no
  faster-whisper import.
- Call it from the child's `load` branch after `model = Model(cfg)` and before
  the `worker: child_started` line, at
  `src/stenographer/transcribe/worker.py:206-228`, wrapped in its own
  `try`/`except Exception` that `log_failure(..., logging.DEBUG, ...,
  safe=True)` and continues (§8.7).
- Gate it on `cfg.vad_filter` (`config.py:258`) — priming a filter the user
  disabled is wasted work.
- `AGENTS.md`: extend the `transcribe/` architecture-map row's `worker.py`
  clause — "load-only warm-up" becomes "load-only warm-up that also primes the
  VAD session when `asr.vad_filter` is on, so the first decode does not pay for
  it".

### 9.3 On accept of V1 / V6 (compute type)

- The default lives at `src/stenographer/config.py:254` (template) and
  `config.py:309` (the in-code default). Change both, in the same commit.
- Confirm quality on the corpus harness before merging — S01's rig has no WER:
  `.venv/bin/python scripts/asr_experiment.py run --variant
  docs/experiments/variants/Q04/<accepted>.json --baseline
  docs/experiments/baseline.json --thresholds
  docs/experiments/variants/Q04/thresholds.json`. If `Q04` already merged the
  change, S01 inherits it and this step is a no-op — say which in the Outcome.
- Re-baseline the corpus harness per `HARNESS.md` §7.3 reason 1, and re-run
  `asr_cold_start.py baseline` (this plan's own baseline is equally stale).

### 9.4 On accept of anything — the `AGENTS.md` acceptance gate

`AGENTS.md` *Acceptance gates* must pass on a real machine before `dev` →
`main`. This change touches capture-adjacent and logging-adjacent behaviour, so
the relevant gates are: `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest` green;
real dictation end-to-end in `hold`, `toggle` and `hybrid`; a cold-start
dictation that retains its opening words; and an inspection of
`stenographer.log` showing metrics but no transcript or audio. Add one plan-
specific check: on the **installed** daemon (not the venv), a genuine cold
dictation's `lock_wait_ms` must show the predicted reduction — this is the only
step that closes the §8.3 environment gap. If the overlay is affected (it is
not, for V1/V2/V5), the overlay gates apply too.

### 9.5 What is testable, and what is not

Timings are not unit-testable and must not be faked into one. New pure unit
tests in `tests/test_asr_cold_start.py`, each seen to fail against a stub
first:

- `parse_importtime` — a fixture of three literal `-X importtime` stderr lines
  → the cumulative-microsecond map, including the "self | cumulative | name"
  column split and the indentation that must be stripped from the name.
- `decompose(press_to_ready_ms, capture_s, ct2_load_ms)` → the `overhead_ms`
  residue, including the clamp at 0 when the load finished before capture ended.
- `decide_coldstart(baseline, run, thresholds)` — every clause of §6.3 as its
  own case: target met but inside 2x noise (deny); `press_to_text_ms`
  regression (deny); one hash mismatch (deny, and the mismatching id reported);
  all clauses met (accept). Worked numbers, no I/O.
- `validate_variant` — unknown key, unknown config section, `margin` below
  `2 x noise` when a baseline is present, `patch` naming a file that is not
  applied.
- `render_variant_config` — the two-level dict → TOML, with the unconditional
  `[stenographer.feedback] update_check = false`.
- The result-file privacy test, mirroring `HARNESS.md` §1: assert
  `coldstart-baseline.json` parses, has `schema == 1`, and carries no key named
  `text`, `hypothesis*`, or `transcript`.

For V2, one additional non-timing behavioural test is possible and worth it:
`Model.prime_vad()` on a real cached model is an `integration`-marked smoke
assertion that a second call is free (the `lru_cache` hit) and that a raised
exception inside it does not propagate out of the child's load branch. It goes
in the smoke suite (`AGENTS.md` hard rule 4), never in the unit suite.

## 10 Out of scope

- **Warming the model at daemon start.** Explicitly excluded: `AGENTS.md` hard
  rule 5 makes the model load press-lazy, and changing that needs a recorded
  decision in `AGENTS.md` first, not an experiment. No S01 variant loads
  weights before the first press. (V3 pre-*spawns* and pre-*imports* without
  loading weights, and is itself only reported, not accepted — §8.6.)
- **`asr.idle_unload_seconds`.** How often a cold start happens at all is
  `S03`'s question. S01 measures the price of one cold start, not its
  frequency.
- **Decode latency and batching.** `S02` (`BatchedInferencePipeline`) and `Q03`
  (`beam_size`).
- **WER, hallucination, first-word loss.** Every quality question belongs to
  the Q-series; S01's only text guard is byte identity (§6.3).
- **Which `compute_type` is right.** `Q04` decides it on the full corpus with
  WER guards; S01 consumes that decision and only measures its latency effect
  on the daemon's own path.
- **The overlay helper's start-up cost.** The pill is independent of dictation
  and the helper's own latency is not on the transcript path.
- **A Windows measurement.** The rig is Linux-only in practice (CUDA, systemd
  comparison); §8.5 is the only place a Windows consequence is decided, and it
  is decided by design, not by measurement.
