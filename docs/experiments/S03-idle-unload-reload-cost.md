# S03 — idle-unload reload cost

Status: planned (2026-08-29)

Baseline for every `file:line` citation: `dev` @ `a1b9807` (v0.11.6),
faster-whisper 1.2.1, CTranslate2 4.8.1, in the repo venv, on the RTX 3080
Laptop (8 GiB) reference machine (`HARNESS.md` §8.1).

This is a **data-collection plan**. It changes no decode behaviour and
proposes no code change by itself; its product is a measured table and one
mechanically derived recommendation about the default value of
`asr.idle_unload_seconds`. Its verdict is *data delivered and internally
consistent*, not *a variant beat a baseline* — `HARNESS.md` §6's
`decide()` is deliberately not used (§6 below says what replaces it).

## 1 Hypothesis

Idle unload terminates the entire ASR child process, so the first utterance
after the idle window pays a **full cold start again, not a weight load**:
on N=5 forced-unload cycles the median `reload_total_ms` sits within ×1.25 of
the same process's own first cold load and at least 1.5 s above the
weight-load-only component (`asr: model_loaded elapsed_ms=`), while the
child's per-pid GPU footprint and RSS return to zero within 10 s of the
unload.

Falsified if the reload is at or below the weight-load-only figure (something
survives the unload, so the cost is cheaper than a cold start), or if the
per-pid GPU memory does not return while the daemon keeps running (the trade
has no benefit side, and the default should be raised or disabled instead of
lowered).

## 2 Symptom & mechanism

**Symptom.** `README.md`'s fourth reported symptom: the first utterance after
a cold start waits ≈4 s (`lock_wait_ms=4048` in the owner's log). The same
wait recurs after every idle window, because `asr.idle_unload_seconds`
(default 900) puts the daemon back in the cold-start state on purpose.

**What the unload releases.** The whole child process, its interpreter, its
`faster_whisper` / CTranslate2 imports and its CUDA context — not just the
model object:

- `Worker._idle_kill` (`src/stenographer/transcribe/worker.py:544-561`) logs
  `worker: unload phase=idle` and calls `_teardown`.
- `_teardown` (`worker.py:563-590`) `terminate()`s the child, `join`s for
  `_JOIN_SECONDS = 2.0` (`worker.py:42`), `kill()`s if it survives, clears
  `_model_ready`, and closes both queues and the log listener.
- The child is a **spawn**-context process
  (`worker.py:273`, `multiprocessing.get_context("spawn")`), so the next one
  is a fresh interpreter. `model.py` imports `faster_whisper` *inside*
  `Model.__init__` (`src/stenographer/transcribe/model.py:73`), so the parent
  never holds it and every child imports it from scratch.
- The next request respawns transparently: `_begin_request`
  (`worker.py:377-382`) spawns when `_process is None or not is_alive()`, and
  `_ensure_model_loaded` (`worker.py:385-401`) sends `("load", utt)` and waits
  up to `_MODEL_LOAD_TIMEOUT_SECONDS = 120.0` (`worker.py:43`) for
  `MODEL_READY`. The child builds `Model(cfg)` on that message
  (`worker.py:206-231`) and answers `("model_ready",)`.

So the predicted reload cost is `spawn + interpreter + imports + CUDA init +
weight load`, i.e. S01's whole 4.1–5.3 s child figure, of which only the
1.9–2.8 s (`int8_float16`) / 0.7–1.2 s (`float16`) weight load is the part an
in-process measurement sees. **This plan measures it rather than asserting
it**, and it measures the split, because the split decides whether the fix is
a different default (§9 Fork A) or a different unload mechanism (§9 Fork B).

**When the clock starts.** The idle timer is armed at the *end of the last
request*, not at the last press: `_restart_idle_timer`
(`worker.py:592-602`, gated by the pure `should_arm_idle_timer`,
`worker.py:114-122`) runs at the tail of `warmup` (`worker.py:335`) and of
`transcribe` (`worker.py:374`). `should_arm_idle_timer` returns `False` for
`idle_seconds <= 0`, which is how `0` disables the feature; the config range
is `0..86400` (`src/stenographer/config.py:203`), the default is `900`
(`config.py:315`) and the annotated template says so (`config.py:260`).
A recording-scoped hold (`hold_model`, `worker.py:287`; taken at
`src/stenographer/daemon.py:479` and released at `:486`, `:518`, `:641`) defers
an unload that would land mid-utterance (`worker.py:549-558`).

**How the cost surfaces to the user.** An accepted press starts a warm-up
thread (`daemon.py:500` → `_start_model_warmup`, `daemon.py:363-375`) that
loads the model *while the user is still speaking*. The decode then runs on
the pipeline thread and takes the same `Worker._lock`
(`worker.py:337-346`). Therefore, after an idle unload:

- if the load finished before the user released, `transcribe` sees
  `_model_ready` set, `loaded` is `False`, and the summary shows `cold=0`,
  `load_ms` absent, `lock_wait_ms≈0` — the user paid nothing;
- if it did not, the decode blocks on the lock and the wait is reported as
  **`lock_wait_ms`, not `load_ms`** (`worker.py:339-341`, folded into the
  summary at `daemon.py:649-653`; `cold` is `not is_model_ready` sampled at
  `daemon.py:582`). That is exactly the owner's `cold=0 lock_wait_ms=4048`.

So the user-felt penalty is `max(0, reload_total − speaking_time)`, and the
recommendation rule in §6 is built on that quantity, not on the raw reload.

## 3 Prerequisites

- **Harness pieces** (`HARNESS.md` §1): `scripts/asr_corpus.py` (corpus and
  `manifest.json` present, base lane) and `scripts/asr_experiment.py preflight`
  (`HARNESS.md` §8.2) for the venv / model-cached / corpus-digest / GPU /
  resolved-compute-type / git / disk checks. `scripts/asr_metrics.py` is **not**
  used: no text is scored.
- **`docs/experiments/baseline.json` is NOT required.** S03 compares nothing
  against the baseline, and `idle_unload_seconds` cannot move a baseline
  number (the subprocess engine loads cold per clip and never constructs a
  `Worker`). S03 may therefore run before the ≈5.5 h baseline exists — a
  deliberate deviation from `README.md`'s execution order, which sequences the
  S-series after the baseline for the plans that do compare.
- **The worker rig `scripts/asr_cold_start.py` — shared with S01.** Neither
  `HARNESS.md` engine exercises the worker child: the subprocess engine runs
  `stenographer transcribe` (one cold `Model` per clip, no `Worker`), and the
  in-process engine constructs `Model` directly (`HARNESS.md` §3.1). Idle
  unload lives only in `Worker`, so a third rig is needed, and
  `S01-cold-start-latency.md` §3.1 already specifies it: the same file, driving
  the real `stenographer.transcribe.worker.Worker` through the daemon's
  sequence (warm-up thread → sleep the capture → `transcribe` → per-repeat
  fresh `Worker`), with subcommands `preflight`, `probe`, `baseline`, `run`,
  `compare`, run directories under `build/asr-coldstart/<run-id>/`, and its
  pure helpers tested in `tests/test_asr_cold_start.py`.
  **S03 adds two disjoint subcommands to that same file — `idle` and
  `idle-check` — plus the footprint sampler; it defines no second rig.**
  **Fork (shared file, merge coordination):** whichever plan runs first writes
  the module skeleton (SPDX header, the `sys.path.insert` convention of
  `tests/test_cue_audition.py:18-29`, the config-rendering and clip-loading
  helpers, the `Worker` driver) and the other extends it. If S03 runs first it
  writes only `preflight`, `idle`, `idle-check` and leaves S01's subcommands
  unwritten; S01 must not narrow the interface below. Both plans add the one
  file to `tests/platform/test_core_isolation.py`'s script grep, once.
- **One correction to S01 §3.1 that S03 depends on.** S01 says the child's
  `asr: model_loaded elapsed_ms=` record is captured "by the rig installing its
  own handler on the `stenographer` logger". It cannot be: `Worker._spawn`
  builds its `QueueListener` over `owned_handlers()`
  (`worker.py:518-523`), which returns only handlers carrying the module's
  private owned marker plus the module listener's own handlers
  (`src/stenographer/utils/logging_setup.py:328-341`) — a rig-attached plain
  handler is never in that tuple, so **no child record reaches it**. The
  working route, which S03 specifies below and S01 should adopt, is to call
  `setup_logging(env=…)` with `XDG_STATE_HOME` pointed into the run directory
  and parse the always-DEBUG `stenographer.log` it writes. A logger-attached
  handler still works for *parent* records (`worker: spawned pid=`).
- **Q04 (`compute_type`) is optional.** §4 runs both `int8` and `float16`
  regardless, because the two footprints are half the trade being decided and
  the extra cost is ≈2 min. Q04's outcome only decides which row the §6
  recommendation is read from (`compute-type-of-record`, default: the shipped
  `int8`).

### 3.1 The `idle` / `idle-check` subcommands — minimum interface

Added to `scripts/asr_cold_start.py`, on the `HARNESS.md` §1 conventions:
never shipped, never imported by `src/stenographer/`, writes only under
`build/`, SPDX header, ruff clean, `.venv/bin/python` only.

```
.venv/bin/python scripts/asr_cold_start.py preflight
.venv/bin/python scripts/asr_cold_start.py idle \
    --variant docs/experiments/variants/S03/<name>.json \
    --out build/asr-coldstart/<run-id>/
.venv/bin/python scripts/asr_cold_start.py idle-check \
    --runs build/asr-coldstart/<run-id>/ [more…] \
    --checks docs/experiments/variants/S03/checks.json \
    --out docs/experiments/results/S03-<run-id>.json
```

`idle` also accepts `--repeats N`, overriding the variant file (§5 step 4).

`preflight` is S01's (it delegates to `asr_experiment.py`'s checks,
`HARNESS.md` §8.2; import them, do not re-implement) plus one S03 addition:
`nvidia-smi` present and answering both queries of the sampler below.
`<run-id>` is `YYYYMMDDTHHMMSSZ-<variant name>` in UTC, as in `HARNESS.md` §1.
`idle` reuses S01's config rendering, clip loading and `Worker` driver; only
the sequence interpreter and the sampler are new.

**Idle variant schema** (schema 1; a *different* object from `HARNESS.md`
§3's variant and from S01's — `idle` rejects a file whose `sequence` key is
missing, and S01's `run` rejects one where it is present, so the three can
never be confused):

```json
{
  "schema": 1,
  "name": "s03-idle-5-int8",
  "plan": "S03",
  "config": {"asr": {"idle_unload_seconds": 5, "compute_type": "int8"}},
  "clip": {"lane": "base", "index": 0},
  "repeats": 5,
  "sequence": ["load", "decode", "sample:resident", "await_unload:30",
               "sample:unloaded", "decode", "sample:reloaded"],
  "sampler_hz": 4,
  "gpu_settle_seconds": 10
}
```

- `config` is rendered and validated exactly as `HARNESS.md` §3 does: a
  two-level `{section: {key: value}}` over existing `stenographer.config` keys,
  written as `[stenographer.<section>]` tables to `<out>/config.toml`, plus an
  unconditional `[stenographer.feedback] update_check = false`, loaded with
  `Config.load`; a `ConfigError` is exit 2. Only `cfg.asr` reaches the
  `Worker`.
- `clip` selects one WAV from the corpus manifest by lane and index into the
  lane's id-sorted list (deterministic). It is read with `soundfile`,
  `stenographer.transcribe.pipeline.downmix` and
  `stenographer.audio._resample_poly`, as `HARNESS.md` §2.3 does.
- Env: `HF_HUB_OFFLINE=1`; the rig calls
  `stenographer.utils.logging_setup.setup_logging(env=…)`
  (`src/stenographer/utils/logging_setup.py:156`) with `XDG_STATE_HOME` set to
  `<out>/state`, so the always-DEBUG file sink lands in the run directory and
  never in the user's real state directory.
- A fresh `Worker` per repeat; `Worker.shutdown()` in a `finally`.

**Sequence primitives** (S03 needs exactly these; S01 may add more):

| Step | Meaning | Recorded |
|---|---|---|
| `load` | `Worker.warmup(utt)` (`worker.py:321`) | `warmup_ms` (rig `perf_counter` around the call) |
| `decode` | `Worker.transcribe(samples, utt)` | `lock_wait_ms`, `load_ms`, `decode_ms` from `Worker.last_timings` (`worker.py:68-77`); `chars_out = len(result.text)` — **never the text** |
| `overlap:<speak_s>` | `Worker.warmup(utt)` on a thread (mirroring `daemon.py:363-375`), sleep `speak_s`, then `Worker.transcribe(samples, utt)` | the same three timings; this is the user-felt number |
| `await_unload:<max_s>` | poll `Worker.is_alive()` at `sampler_hz` until false or deadline | `unload_latency_s`, measured from the rig's own stamp at the end of the previous request (where `_restart_idle_timer` armed, `worker.py:592`); deadline exceeded ⇒ recorded as `null` and the check in §6 fails |
| `await_alive:<s>` | poll for `s` seconds; the child must stay alive throughout | `stayed_alive: bool`, `observed_s` |
| `sample:<label>` | one immediate footprint sample | see below |
| `wait:<s>` | plain sleep | — |

Every step is stamped with `t_monotonic` at entry and exit into
`<out>/events.jsonl` (one JSON object per line), and every step carries the
repeat index and a distinct `utt` integer (so the child's own lines are
correlatable — the child stamps them via `set_utterance`, `worker.py:204`).

**Public API only.** `Worker(cfg)`, `.warmup()`, `.transcribe()`,
`.is_alive()`, `.is_model_ready`, `.shutdown()`, `.last_timings`. The rig
must not touch `_process`, `_idle_timer` or any other private attribute: the
child pid comes from the parent's own INFO record `worker: spawned pid=<pid>`
(`worker.py:542`), captured by a `logging.Handler` the rig attaches to the
`stenographer` logger.

**Weight-load-only component.** The child's records reach the sinks through
the worker's own `QueueListener` over `owned_handlers()`
(`worker.py:518-523`), bypassing the logger — so a logger-attached handler
cannot see them. The rig therefore parses `<out>/state/**/stenographer.log`
(always DEBUG, `AGENTS.md` hard rule 6) after the run for
`asr: model_loaded elapsed_ms=(\d+)` (`model.py:91-94`), which times
`WhisperModel(...)` construction alone (`model.py:81-88`), and correlates each
hit with its step by the `utt=` stamp, falling back to file order (the
sequence is strictly serial).

**Footprint sampler.** A daemon thread at `sampler_hz` from the first spawn
until the end of the repeat, plus every explicit `sample:` mark, plus
`gpu_settle_seconds` of continued sampling after an `await_unload` observes
the death (so a late driver reap is visible rather than assumed). Each sample:

```json
{"t_monotonic": 12.5, "label": "resident", "child_pid": 4711, "child_alive": true,
 "rss_kib": 2317884, "gpu_pid_mib": 968, "gpu_total_used_mib": 2106,
 "gpu_total_mib": 8192, "sm_clock_mhz": 1710, "gpu_temp_c": 64}
```

- `rss_kib`: `VmRSS` from `/proc/<pid>/status`; `null` once the path is gone.
- `gpu_pid_mib`: `nvidia-smi --query-compute-apps=pid,used_gpu_memory
  --format=csv,noheader,nounits`, **filtered to the child pid**, `0` when the
  pid is absent. Per-pid attribution is mandatory, not cosmetic: at planning
  time an unrelated process held 1138 MiB on this GPU, so the global figure
  cannot be differenced.
- `gpu_total_used_mib` / `gpu_total_mib` / `sm_clock_mhz` / `gpu_temp_c`:
  `nvidia-smi --query-gpu=memory.used,memory.total,clocks.sm,temperature.gpu
  --format=csv,noheader,nounits`, for context and for the throttling confound
  in §8.
- `nvidia-smi` missing or failing is exit 2 from `preflight`, and thereafter a
  `null` sample field — never a crash mid-run.

**Outputs per `idle` run directory:** `variant.json` (as validated),
`config.toml`, `state/` (the run's `stenographer.log`), `events.jsonl`,
`samples.jsonl`, `idle.json` (environment block copied from `HARNESS.md` §4.3 plus per-repeat
and median aggregates). None of them contains transcript text; `chars_out` is
the only thing derived from the decode's output.

**Pure helpers, unit-tested** (`AGENTS.md` hard rule 4; each test seen to fail
first): `parse_sequence`, `validate_idle_variant`, `parse_model_loaded_ms`,
`parse_spawned_pid`, `summarize_idle(events, samples) -> dict`,
`check_idle(summary, checks) -> Verdict`, and `recommend(summary, checks) -> str`
(§6's rule). Tests live at `tests/test_asr_cold_start.py` with the
`sys.path.insert` convention of `tests/test_cue_audition.py:18-29`. Nothing
that touches the model, `nvidia-smi`, `/proc` or a subprocess is mocked; the
I/O half is exercised only by running it for real.

## 4 Variant matrix

Checked in under `docs/experiments/variants/S03/`. Every variant uses
`"clip": {"lane": "base", "index": 0}` and `sampler_hz: 4`,
`gpu_settle_seconds: 10`. No `engine` key: `idle` has one driver.

| # | File | `idle_unload_seconds` | `compute_type` | `repeats` | Sequence | Purpose |
|---|---|---|---|---|---|---|
| V1 | `s03-idle-5-int8.json` | 5 | `int8` | 5 | `load, decode, sample:resident, await_unload:30, sample:unloaded, decode, sample:reloaded` | The reload curve at the shipped compute type. |
| V2 | `s03-idle-5-float16.json` | 5 | `float16` | 5 | same as V1 | The same curve at the other candidate, with its larger footprint. |
| V3 | `s03-overlap-int8.json` | 5 | `int8` | 3 | `load, decode, await_unload:30, overlap:2, wait:1, await_unload:30, overlap:4, wait:1, await_unload:30, overlap:6` | The user-felt penalty at 2 s / 4 s / 6 s of speech, measured the way the daemon produces it. |
| V4 | `s03-idle-900-int8.json` | 900 | `int8` | 1 | `load, decode, sample:resident, await_unload:960, sample:unloaded, decode, sample:reloaded` | Conformance at the real default: the 900 s timer fires, and the footprint drops, with no long-timer surprise. |
| V5 | `s03-idle-0-int8.json` | 0 | `int8` | 1 | `load, decode, sample:resident, await_alive:60, sample:resident-60s` | `0` disables: the child must survive the window and hold its footprint. |

V1 is the row of record unless Q04 accepted `float16`, in which case V2 is
(§6). V4 is the only slow variant and may be run last or in the background.

## 5 Procedure

Every step is non-interactive. Run from the repo root.

```sh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration" tests/test_asr_cold_start.py
.venv/bin/python scripts/asr_cold_start.py preflight
```

Preflight non-zero ⇒ stop; exit 2 with the `stenographer model download` hint
means the model is not cached and the plan cannot run (the harness never
downloads a model, `HARNESS.md` §8.2).

Then, in this order (fixed, so the GPU thermal state is comparable):

```sh
for v in s03-idle-5-int8 s03-idle-5-float16 s03-overlap-int8 s03-idle-0-int8 s03-idle-900-int8; do
  .venv/bin/python scripts/asr_cold_start.py idle \
    --variant docs/experiments/variants/S03/$v.json \
    --out build/asr-coldstart/$(date -u +%Y%m%dT%H%M%SZ)-$v/
done
```

Per-variant exit codes: `0` the run completed and wrote `idle.json`; `1`
never (an `idle` run has no verdict); `2` harness error — record which
variant, fix or report, and do not proceed to `idle-check` with a missing run.

Then:

```sh
.venv/bin/python scripts/asr_cold_start.py idle-check \
  --runs build/asr-coldstart/*-s03-* \
  --checks docs/experiments/variants/S03/checks.json \
  --out docs/experiments/results/S03-<run-id>.json
```

Step 4 — noise: if the verdict marks any variant `"noisy": true` (C7), re-run
that one variant once with `--repeats 9` (the flag overrides the variant file)
into a fresh run directory and re-run `idle-check` over the new set. Do this at
most once; a second breach is reported, not chased.

`idle-check` exit codes: `0` data complete and internally consistent; `1` complete
but a consistency check failed; `2` harness error (a missing run, a schema
mismatch, fewer repeats than `min_repeats`). On `0` **or** `1` the executing
agent appends the Outcome section (§9) with the table, the check list and the
recommendation line, and sets Status accordingly; only `2` leaves the plan at
`running` pending a fix.

Retry policy, no human: a single variant that exits 2 for a transient reason
(`nvidia-smi` timeout, a `WorkerError` on one repeat) is re-run **once**; a
second failure is reported as-is with `Status: denied` and the partial numbers
kept.

## 6 Metrics & accept/deny

No `HARNESS.md` §6 target metric and no baseline comparison: S03 proposes no
decode change, so there is nothing for `decide()` to weigh. Its verdict is
completeness plus internal consistency, computed by the pure
`check_idle(summary, checks)`.

**Derived quantities** (medians over repeats unless stated), per variant:

- `cold1_ms` — `warmup_ms` of the first `load` in each repeat (a genuine
  cold child).
- `reload_total_ms` — `load_ms` of the post-unload `decode` (or `warmup_ms`
  of a post-unload `load`); the number this plan exists to produce.
- `weight_load_ms` — the child's `asr: model_loaded elapsed_ms=` for that
  same load: weight construction only.
- `spawn_overhead_ms` = `reload_total_ms − weight_load_ms` — interpreter,
  imports and CUDA init.
- `unload_latency_s` — end of last request → `is_alive()` false.
- `vram_reclaimed_mib` = `gpu_pid_mib(resident) − max(gpu_pid_mib)` over the
  settle window after the unload; `rss_reclaimed_mib` likewise from `rss_kib`.
- `felt_ms(d)` — `lock_wait_ms + (load_ms or 0)` of the `overlap:<d>` decode
  in V3.
- `spread_rel` = `(max − min) / median` of `reload_total_ms`.

**`docs/experiments/variants/S03/checks.json`** (schema 1):

```json
{
  "schema": 1,
  "plan": "S03",
  "min_repeats": {"s03-idle-5-int8": 5, "s03-idle-5-float16": 5,
                  "s03-overlap-int8": 3, "s03-idle-900-int8": 1,
                  "s03-idle-0-int8": 1},
  "reload_vs_cold_max_ratio": 1.25,
  "reload_min_ratio_of_weight_load": 1.0,
  "spawn_overhead_bounds_s": [0.5, 4.0],
  "unload_latency_grace_s": 2.0,
  "felt_vs_derived_max_delta_s": 0.5,
  "footprint_returned_mib_max": 50,
  "spread_max_relative": 0.35,
  "recommendation": {
    "reload_low_s": 1.5, "reload_high_s": 3.0, "mechanism_fork_gap_s": 1.5,
    "vram_benefit_min_mib": 50, "rss_benefit_min_mib": 200,
    "lower_to_seconds": 300, "raise_to_seconds": 3600
  }
}
```

**Checks** (all must hold for exit 0):

- **C1 completeness** — every variant present, each with at least its
  `min_repeats` repeats, every step recorded, no `null` `reload_total_ms`.
- **C2 bounds** — `weight_load_ms ≤ reload_total_ms ≤ 1.25 × cold1_ms` for
  V1 and V2. The lower bound falsifies "something survived the unload"; the
  upper bound falsifies "the reload is somehow worse than a cold start".
- **C3 decomposition** — `spawn_overhead_ms / 1000` within `[0.5, 4.0]`, the
  envelope S01's 4.1–5.3 s child versus 1.9–2.8 s in-process load implies.
- **C4 unload timing** — `unload_latency_s ∈ [idle, idle + 2.0]` for V1, V2,
  V3 and V4; V5 reports `stayed_alive: true` over its 60 s window.
- **C5 footprint sampled** — for V1, V2 and V4 a `resident` and an
  `unloaded` sample both exist with non-`null` `gpu_pid_mib`, and the settle
  window was sampled to its end. **The *value* is a finding, not a check**:
  whether the memory came back is reported and feeds the recommendation, and
  only a *missing* sample fails C5.
- **C6 user-felt agreement** — for each `d ∈ {2, 4, 6}`,
  `|felt_ms(d) − max(0, reload_total_ms − 1000·d)| ≤ 500 ms`. This is the
  check with real teeth: it confirms the daemon's warm-up overlap behaves as
  §2 describes and that `lock_wait_ms` is the right quantity to reason about.
- **C7 repeatability** — `spread_rel ≤ 0.35`. Exceeding it sets
  `"noisy": true` in the verdict and does **not** fail the run; §5's step 4
  re-runs that variant once at `--repeats 9`, and a second breach is reported
  as noisy in the Outcome and accepted.

**Recommendation rule** — the pure `recommend(summary, checks)`, applied to
the compute-type-of-record row (V1, or V2 if Q04 accepted `float16`), with
`R = median reload_total_ms / 1000`, `W = median weight_load_ms / 1000`,
`G = vram_reclaimed_mib`, `S = rss_reclaimed_mib`. First matching clause wins:

1. `G < 50 and S < 200` → **`RAISE-OR-DISABLE`**: the unload frees nothing
   measurable while the daemon runs, so it is pure cost — set the default to
   `0` (disabled) and open Fork B to find out why the memory is retained.
2. `R ≤ 1.5` → **`LOWER 900 → 300`**: five minutes is a real break and the
   reload is imperceptible; take the footprint back sooner.
3. `R ≤ 3.0` → **`KEEP 900`**: the shipped default is the right trade.
4. `R > 3.0 and (R − W) ≥ 1.5` → **`FORK-B`**: most of the cost is process
   re-creation, not weights — keep `900` and open Fork B (release the model
   object inside a living child) rather than tuning the number.
5. otherwise → **`RAISE 900 → 3600`**: the cost is irreducible weight
   loading, so pay the idle footprint for longer.

`recommend` also reports `felt_ms(2)` beside its verdict, because clause 3
versus 5 is the owner's judgement about 0.8–1.5 GB of VRAM on an 8 GiB laptop
GPU shared with the compositor, and the felt penalty is the other half of it.
The rule fixes the recommendation; **it does not authorize the edit** — Fork A
in §9 is a separate, owner-reviewed commit.

## 7 Cost estimate

Model already cached; no corpus generation beyond the existing base lane.

| Variant | Arithmetic | Wall |
|---|---|---|
| V1 | 5 × (≈5 s cold + ≈1 s decode + 5 s idle + ≈2 s reap + ≈5 s reload + ≈1 s decode + 10 s settle) | ≈2.5 min |
| V2 | as V1, faster load | ≈2 min |
| V3 | 3 × (cold + 3 overlap cycles ≈ 45 s) | ≈2.5 min |
| V4 | 1 × (≈6 s + 900 s idle + ≈2 s reap + ≈6 s + 10 s settle) | ≈16 min |
| V5 | 1 × (≈6 s + 60 s + samples) | ≈1.5 min |
| preflight | one cold in-process load (`HARNESS.md` §8.2 step 5) | ≈10 s |

**Total ≈ 25 min wall**, of which 16 min is V4 idling. Disk: run directories
are a few MB each (`events.jsonl`, `samples.jsonl`, one `stenographer.log`);
budget 100 MB, well inside `HARNESS.md` §8.2's 1 GiB check. GPU: one child at
a time, ≤1.5 GB.

## 8 Risks, confounds, invariants

**Risks and confounds**

- **CUDA caching allocator / GPU memory not returned.** The stated risk is
  that VRAM stays held after the model is dropped. Here the whole process
  dies, so the driver should reap it — but that is exactly what C5 measures
  rather than assumes, per-pid, with a 10 s settle window. If the memory does
  not come back, clause 1 of the recommendation rule fires.
- **Another process holding VRAM.** Verified live at planning time (an
  unrelated compute app held 1138 MiB). Global `memory.used` is recorded for
  context only; every conclusion is drawn from the per-pid figure.
- **OS page cache.** The rig's reload reads `model.bin` from a warm page
  cache, so `reload_total_ms` is a *lower bound* on a genuine
  first-boot-after-reboot load. Dropping caches needs root and is not
  hands-off; the rig records `/proc/meminfo` `Cached` at each `sample:` mark
  and the plan reports the figure as warm-cache. Clause 2's threshold (1.5 s)
  is well below any measured value, so the bias cannot flip it.
- **GPU clocks and thermals.** Variants run in the fixed order of §5, and
  every sample carries `clocks.sm` and `temperature.gpu`; a run whose SM clock
  varies by more than 20 % across variants is annotated in the Outcome.
- **`threading.Timer` versus wall clock.** The idle timer is a
  `threading.Timer` (`worker.py:600`). Whether it accounts for a laptop
  suspend is untested here and untestable hands-off; it is called out in the
  Outcome as an open question, not measured (§10).
- **`_MODEL_LOAD_TIMEOUT_SECONDS = 120`** (`worker.py:43`) — a hung load
  raises `WorkerError` and is an `idle` exit 2, not a silent slow number.
- **One-clip decode.** `decode_ms` here is incidental (one short base-lane
  clip); this plan makes no claim about decode latency. S02/Q03 own that.
- **`repeats` within one `idle` process.** The parent is reused across
  repeats, but every child is a fresh spawn-context interpreter
  (`worker.py:273`) and the parent never imports `faster_whisper`
  (`model.py:73`), so repeat 1's cold load and repeat 5's reload are
  structurally identical — which C2's `cold1_ms` comparison also verifies.

**Invariants** (`HARNESS.md` §9, restated and ticked in the PR):

- **No transcript text** anywhere. The rig records `chars_out =
  len(result.text)` and never the text, in `events.jsonl`, `samples.jsonl`,
  `idle.json`, `docs/experiments/results/S03-*.json`, this file, or stdout.
  The run's `stenographer.log` is the shipped one, which carries lengths only
  (`AGENTS.md` hard rule 6). S03 writes **no** `clips.jsonl` — it has no text
  file at all.
- **No network in the ASR path.** `local_files_only=True` (`model.py:87`)
  is untouched; the rig sets `HF_HUB_OFFLINE=1` and
  `[stenographer.feedback] update_check = false`; the rig downloads nothing.
- **No platform imports.** The rig imports core modules only
  (`stenographer.config`, `stenographer.audio`, `stenographer.transcribe.*`,
  `stenographer.utils.logging_setup`) and never `stenographer.platform.linux`,
  `evdev`, `fcntl`, or any name in `tests/platform/test_core_isolation.py`'s
  `BLOCKED` tuple (`tests/platform/test_core_isolation.py:48-57`). Add
  `scripts/asr_cold_start.py` to that test's script grep alongside the three
  `HARNESS.md` scripts. `/proc` and `nvidia-smi` are Linux/NVIDIA-only and are
  confined to the rig's sampler, which is dev tooling under `scripts/`, not
  shipped code — no host code enters `src/`.
- **Nothing under `src/` changes for this plan.** No `DecodeOptions` field is
  used; the anti-hallucination stack and the 23-key config schema
  (`AGENTS.md` hard rule 9) are untouched. Fork A's edit, if it happens, is a
  value change to an existing key — still 23 keys, still 4 sections.
- **Test policy** (`AGENTS.md` hard rule 4): the pure helpers in §3.1 have
  seen-to-fail tests; no mocking of `subprocess`, `Worker`, the model,
  `nvidia-smi` or `soundfile`; the I/O half is proven by running it for real
  on the reference machine.
- **Venv only**, SPDX header on the new script and its test, ruff clean, line
  length 100, py312 syntax.

## 9 Deliverables & follow-through

**Always** (exit 0 or 1 from `check`):

1. `docs/experiments/results/S03-<run-id>.json` — numbers only: the per-variant
   summaries, every check with both values, `noisy`, and the recommendation
   string.
2. An **Outcome** section appended to this file, Status set to `accepted`
   (exit 0) or `denied` (exit 1), containing:
   - the run ids;
   - a table with one row per variant: `cold1_ms`, `reload_total_ms`,
     `weight_load_ms`, `spawn_overhead_ms`, `spread_rel`, `unload_latency_s`,
     `gpu_pid_mib` resident/unloaded, `rss_kib` resident/unloaded;
   - the V3 row: `felt_ms(2)`, `felt_ms(4)`, `felt_ms(6)`;
   - the check list with pass/fail;
   - one recommendation line, verbatim from `recommend()`.
   Numbers only, no transcript text.
3. `scripts/asr_cold_start.py` + `tests/test_asr_cold_start.py` +
   `docs/experiments/variants/S03/{s03-*.json,checks.json}` committed
   (`chore:` or `feat:` per `AGENTS.md` hard rule 10, on `dev`).

**Fork A — the config default changes.** Only if the recommendation is
`LOWER`, `RAISE` or `RAISE-OR-DISABLE`, and only as a separate commit the
owner reviews. The complete ripple, verified by grep at planning time:

- `src/stenographer/config.py:315` — `idle_unload_seconds=900` in
  `Config.defaults()`.
- `src/stenographer/config.py:260` — the annotated template line
  `idle_unload_seconds = 900      # kill the idle worker child; 0 disables`.
- `src/stenographer/config.py:203` — the `0..86400` range needs **no** change
  for any recommended value.
- `tests/test_config.py:38` — `assert d.asr.idle_unload_seconds == 900`.
- `tests/cli/test_setup.py:274` — the setup banner line
  `"  idle_unload_seconds = 900"`.
- `src/stenographer/cli/setup.py:461-470` takes its prompt default from the
  loaded config — **no change**.
- `README.md` — does not mention `idle_unload_seconds` or `900` — **no
  change**.
- `AGENTS.md:355` names `asr.idle_unload_seconds` without a value — **no
  change**; hard rule 9's "exactly 23 keys in 4 sections" is unaffected.
- **No re-baseline** (`HARNESS.md` §7.3): the key cannot move a baseline
  number, since the subprocess engine loads a cold `Model` per clip and never
  constructs a `Worker`. Say so in the commit message.
- **Acceptance gate before dev → main** (`AGENTS.md`): the integration suite
  green — `tests/transcribe/test_worker_smoke.py::test_idle_kill_then_restart`
  (`tests/transcribe/test_worker_smoke.py:127-158`) already covers unload and
  transparent respawn — plus real dictation in `hold`, `toggle` and `hybrid`,
  and step 4 of the manual procedure in `tests/test_daemon_smoke.py:17-19`
  (short `idle_unload_seconds`, one dictation, wait for the unload, repeat the
  immediate-speech check) run against the new default's neighbourhood.

**Fork B — a cheaper unload mechanism.** Only if the recommendation is
`FORK-B` or `RAISE-OR-DISABLE`: release the `Model` object inside a living
child (keeping the interpreter, the imports and the CUDA context) instead of
terminating the process, so a reload costs `weight_load_ms` rather than
`reload_total_ms`. That is a change to fixed lifecycle behaviour and to the
crash-isolation story (`worker.py:544-590`), with its own risks — a leaked
CUDA context, a child that no longer proves its own health by dying, an
`AGENTS.md` `transcribe/` row edit. **It is a new plan (`S04`), not an
addendum here.** This plan's job is to hand it the measured gap `R − W`.

**If the recommendation is `KEEP 900`:** no code change at all. Commit the
rig additions, the variants and the Outcome, and record in the Outcome that the
default was measured and confirmed rather than assumed.

## 10 Out of scope

- **Changing the unload mechanism.** Measured here, changed in Fork B / S04.
- **Cold-start decomposition in general** — S01 owns import versus load versus
  CUDA init, and owns the shared rig. S03 reads only the one number the idle
  path re-pays.
- **Decode latency and any text metric.** No WER, no leading-word recall, no
  trailing junk; `asr_metrics.py` is not imported. Q03/S02 own decode speed;
  the Q-series owns quality.
- **`compute_type` selection.** Q04 decides it; S03 measures both and reads
  its recommendation from Q04's winner.
- **Suspend/resume behaviour of the idle timer**, and any wall-clock versus
  monotonic question about a laptop that sleeps for hours. Flagged in §8,
  measurable only with a real suspend, which is not hands-off.
- **Windows.** The sampler's `/proc` and `nvidia-smi` sampler is Linux/NVIDIA
  only. The worker child is core code and behaves the same way there, but no
  Windows figure is produced or claimed.
- **The overlay's or the daemon's own footprint.** Only the ASR child's
  per-pid figures are attributed.
