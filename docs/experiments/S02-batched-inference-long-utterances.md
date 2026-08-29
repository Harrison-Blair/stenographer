# S02 — `BatchedInferencePipeline` for long utterances

Status: planned (2026-08-29)

Baseline for every `file:line` citation: `dev` @ `a1b9807` (v0.11.6),
faster-whisper 1.2.1, CTranslate2 4.8.1, in the repo venv
(`.venv/lib/python3.14/site-packages/faster_whisper/`). Read
`docs/experiments/HARNESS.md` first; this plan is written against its §1–§10
and names every place it extends them.

---

## 1 Hypothesis

Routing utterances longer than one 30 s Whisper window through
`faster_whisper.transcribe.BatchedInferencePipeline`
(`faster_whisper/transcribe.py:111`) reduces `decode_ms_p50` on the `longform`
lane by ≥ 30 % relative **and** ≥ 400 ms absolute, without moving `wer_mean`
by more than +0.002, without raising `trailing_junk_rate` or
`large_deletion_run_rate`, without lowering `leading_word_recall_mean`, and
without `rtf_p95` rising at all (ratio ≤ 1.00), on the `longform` lane; and it
changes none of those on the `base` lane, where it must not be selected.

The hypothesis is falsifiable in both directions: the batched path is a
different code path with a *documented* set of options it silently ignores
(§2.3), so it can plausibly be both faster and worse.

---

## 2 Symptom & mechanism

### 2.1 Symptom

`docs/experiments/README.md` symptom (4): "the first utterance after a cold
start waits ≈4 s (`lock_wait_ms=4048` in the log) and decode latency is
noticeable." S01 owns the cold-start half. S02 owns the *decode* half, and
only for the long tail of utterance lengths — `audio.max_recording_seconds`
defaults to `600` (`src/stenographer/config.py:250`), so a dictation may be up
to ten minutes long, and in hybrid mode a latched tap makes multi-minute
utterances easy to produce by accident as well as on purpose.

Verified numbers from the owner's `stenographer.log` (sequential path, this
machine, `beam_size = 1`, `compute_type = "int8"`):

| audio | decode | notes |
|---|---|---|
| 25 s | 1.1 s | 1 window |
| 69 s | — | 12 segments |
| 109 s | 3.4 s | ≈32× realtime |

### 2.2 Mechanism — why more windows cost more, and what batching can save

`Model.transcribe` calls `WhisperModel.transcribe`
(`src/stenographer/transcribe/model.py:110-125`). With `vad_filter = true`
(the default, `config.py:258`) the sequential path collects the VAD speech
regions, **concatenates** them into one waveform
(`faster_whisper/transcribe.py:884-897`), and `generate_segments` walks that
concatenation in 30 s windows, encoding and decoding each window strictly one
after another (`transcribe.py:1103-1390`). Decode wall time is therefore
approximately affine in the window count `W = ceil(vad_seconds / 30)`.

Fitting `T(W) = f + c·W` to the two measured points above — 25 s → `W = 1`,
1.1 s; 109 s → `W ≈ 4`, 3.4 s — gives

```
c ≈ 0.767 s   per additional 30 s window (encode + decode)
f ≈ 0.333 s   fixed: Silero VAD, log-mel features, Python overhead
```

**The ceiling.** `BatchedInferencePipeline` encodes and decodes `batch_size`
windows in one `ctranslate2` call (`transcribe.py:222-236` inside
`generate_segment_batched`, driven by `_batched_segments_generator`,
`transcribe.py:580-618`). Perfect parallelism across a batch that covers every
window is the absolute floor:

```
T_batched_floor = f + c  ≈ 1.1 s     for any W ≤ batch_size
```

so for the 109 s / `W = 4` case the ceiling is a **68 % reduction** (3.4 s →
1.1 s). Batching is never free on a GPU — with a realistic marginal batch cost
`ε ≈ 0.25` (`T = f + c·(1 + ε(W−1))`) the modelled figure is 1.67 s, a **51 %
reduction**. The 30 % accept margin sits comfortably below the modelled value
and far above the run-to-run noise this machine shows on `decode_ms_p50`.
Absolute stakes: 30 % of a 3.4 s decode is ≈1.0 s of felt latency per long
dictation; the 400 ms absolute floor in §1 exists so that a 30 % win on an
already-tiny number cannot justify carrying a second decode path.

Two facts bound how much of that ceiling is reachable:

- The batched path pads **every** chunk to 30 s (`pad_or_trim`,
  `transcribe.py:515`), so `K` chunks cost `K` windows-worth of encoder work
  regardless of how short they are. If VAD chunking produced one chunk per
  pause, `K ≫ W` and batching could be *slower*.
- It does not. `collect_chunks(audio, clip_timestamps, max_duration=30)`
  (`faster_whisper/vad.py:186-243`, called at `transcribe.py:421-423`) greedily
  **merges** adjacent speech regions up to 30 s, so `K ≈ W` — the batched path
  sees essentially the same concatenated speech, cut at VAD-region boundaries
  instead of at exact 30 s offsets. The plan still measures `K` (it equals the
  segment count on the batched path, §2.4) rather than assuming it, and the
  `longform` lane carries two gap settings (§3.3) precisely to exercise both
  boundary regimes.

### 2.3 What the batched path silently changes — from the library source

This is the quality risk, and it is not a matter of degree: `transcribe.py`
builds its own `TranscriptionOptions` at `transcribe.py:519-553` and hard-codes
several fields regardless of what the caller passed. `transcribe.py:351-369`
documents a block titled **"Unused Arguments"**. Every kwarg
`model.py:110-125` passes today, checked against that source:

| kwarg at `model.py` | batched behaviour | verdict |
|---|---|---|
| `language="en"` (`:112`) | honoured; model is English-only anyway | same |
| `beam_size=cfg.beam_size` (`:113`) | passed to `model.generate` (`transcribe.py:225`) | same |
| `temperature=0.0` (`:114`) | `temperatures = temperature[:1]` (`transcribe.py:528-532`); there is **no** `generate_with_fallback` on this path, so a ladder would be silently truncated to its first value | same *today* (scalar 0.0); **breaks Q01** if a ladder is adopted |
| `no_repeat_ngram_size=3` (`:115`) | passed to `model.generate` (`transcribe.py:235`) | same |
| `vad_filter=cfg.vad_filter` (`:116`) | VAD is used to **chunk**, not to concatenate; and with `vad_filter=False` on audio ≥ 30 s the call raises `RuntimeError("No clip timestamps found. …")` (`transcribe.py:414-418`) | **changed + can crash** |
| `vad_parameters=_VAD_PARAMETERS` (`:117`, `:32-37`) | wrapped as `VadOptions(**params, max_speech_duration_s=30)` and any caller-supplied `max_speech_duration_s` is popped (`transcribe.py:403-409`); sequential uses `VadOptions(**params)` with `max_speech_duration_s = inf` (`transcribe.py:886-888`) | **changed**: speech regions > 30 s are split |
| `no_speech_threshold=cfg.silence_threshold` (`:118`) | listed under "Unused Arguments" (`transcribe.py:356-358`); stored in options but never consulted — the sequential skip at `transcribe.py:1211-1235` has no batched counterpart. The repo's own gate in `_assemble` (`model.py:215`) still runs, but the batched path copies one `no_speech_prob` onto every subsegment of a chunk (`transcribe.py:147`), so the gate becomes **chunk-granular** instead of decoder-segment-granular | **dropped (library) / coarsened (ours)** |
| `hallucination_silence_threshold=2.0` (`:119`, `:27`) | **hard-coded to `None`** at `transcribe.py:546`; the word-anomaly and silence-skip machinery at `transcribe.py:1242-1330` never runs | **DROPPED — primary quality risk** |
| `max_new_tokens=_token_budget(128, audio_seconds)` (`:120`, `:173-175`) | honoured, but applied **per chunk** (`transcribe.py:193-196`) while the repo computes the budget from *total* audio seconds. For audio ≥ 14 s the budget is already the 128 ceiling, so long-lane behaviour matches; for shorter multi-chunk audio the batched path allows strictly more total tokens | **changed semantics** |
| `condition_on_previous_text=False` (`:121`) | hard-coded `False` (`transcribe.py:547`) | same |
| `hotwords=…` (`:122`) | honoured via `get_prompt` (`transcribe.py:182-191`), per chunk | same |
| `initial_prompt=…` (`:123`) | applied to **every** chunk (`transcribe.py:184-188`). Sequential seeds `all_tokens` once and then, with `condition_on_previous_text=False`, sets `prompt_reset_since = len(all_tokens)` after the first window (`transcribe.py:1372-1383`), so only window 0 sees it | **changed**; inert today (default `""`), **interacts with Q08** |
| `word_timestamps=True` (`:124`) | honoured; `add_word_timestamps` runs inside `forward` (`transcribe.py:160-168`) | same |

Two options the repo does **not** pass also differ by default:

- `without_timestamps`: batched default `True` (`transcribe.py:283`),
  sequential default `False` (`transcribe.py:776`). With it `True` the model
  emits no timestamp tokens, `_split_segments_by_timestamps` always takes its
  else-branch (`transcribe.py:1081-1099`), and **one segment is produced per
  chunk**, bounded by VAD rather than by the decoder. It also frees the whole
  128-token budget for text instead of spending 2–4 tokens on timestamps.
- `max_initial_timestamp`: hard-coded `0.0` (`transcribe.py:552`) vs `1.0`.

### 2.4 The token-ceiling / deletion interaction the plan must measure

`_token_budget` caps generation at 128 new tokens per window
(`model.py:26,173-175`). Ordinary English dictation runs ≈2.5 words/s, so a
full 30 s window is ≈75 words ≈ 100 tokens plus timestamps — the ceiling is
*close to binding* on dense speech, which is exactly the long-lane regime.

On the **sequential** path, if generation stops at the ceiling before it has
emitted a pair of consecutive timestamps, `_split_segments_by_timestamps`
falls into its else-branch and advances `seek += segment_size`
(`transcribe.py:1081-1099`, the advance at `:1099`) — a full 30 s window step.
Everything after the truncation point in that window is never decoded. The
user sees a long run of missing words in the middle of a long dictation.

On the **batched** path the chunk list is fixed up front and `seek` is not
used to drive iteration (`transcribe.py:580-618`), so a token-ceiling hit
truncates that chunk's text but cannot skip past unread audio. Prediction:
`large_deletion_run_rate` should be **lower** on the batched path, not higher.
That prediction is a guard in §6, not an assumption.

`segments` on the batched path with `without_timestamps=True` equals the chunk
count `K`, which is what §2.2 wants measured.

---

## 3 Prerequisites

Everything below must be implemented, unit-tested (pure parts, seen to fail
first — `AGENTS.md` hard rule 4), lint-clean, and **committed** before the
first run: `asr_experiment.py preflight` records `git_dirty`, and
`HARNESS.md` §8.2 item 6 refuses to write a baseline from a dirty tree, which
S02's control run (§5) is.

### 3.1 Harness foundation (`HARNESS.md` §1–§8)

`scripts/asr_corpus.py`, `scripts/asr_metrics.py`, `scripts/asr_experiment.py`
and their pure tests exist; the corpus is fetched; the `DecodeOptions` seam
(`HARNESS.md` §3.2) exists in `src/stenographer/transcribe/model.py`.
`docs/experiments/baseline.json` need not exist for S02 — S02 compares against
its own control run (§5.2), because the programme baseline covers neither the
`longform` lane nor the in-process engine.

### 3.2 New `DecodeOptions` fields

Added to the frozen dataclass in `model.py`, defaults byte-for-byte today's
behaviour:

```python
    # BatchedInferencePipeline, faster_whisper/transcribe.py:111
    batched: bool = False
    batch_size: int = 8               # inert while batched is False
    without_timestamps: bool = False  # library default on the sequential path
```

`Model.transcribe` gains one branch: when `self._options.batched`, call
`BatchedInferencePipeline(self._impl).transcribe(...)` with the same kwargs,
plus `batch_size=` and `without_timestamps=`, instead of
`self._impl.transcribe(...)`. Requirements on that branch:

- The pipeline object is constructed **per call** (or cached on the `Model`
  and only ever used with a fully exhausted generator): it carries mutable
  `last_speech_timestamp` state that is reset only when
  `_batched_segments_generator` runs to completion (`transcribe.py:117`,
  `:617`). `model.py:126-138` already materialises the generator into a list,
  so exhaustion holds — the pinning test must assert it keeps doing so.
- `hallucination_silence_threshold` is still *passed*; the library discards it
  (`transcribe.py:546`). Do not pre-emptively pass `None`: the control and the
  batched variants must differ in exactly one thing, and §4 has a separate
  cell that isolates the discard.
- `validate_variant` (`scripts/asr_experiment.py`) rejects, as harness errors
  (exit 2): `batch_size` outside `1..32`; `batched: true` with
  `word_timestamps: false` (the repo's density check counts word timestamps,
  `model.py:200-204`, and would become vacuous); `batched: true` with a
  variant `config.asr.vad_filter = false` (`transcribe.py:414-418` raises on
  audio ≥ 30 s).
- `DecodeOptions()`'s pinning test (`tests/transcribe/test_model.py`,
  `HARNESS.md` §3.2) gains the three new keys with the defaults above.

### 3.3 The corpus lane `longform` (`HARNESS.md` §2.4)

`HARNESS.md` §2.2 caps selected `base` utterances at 35 s — a window-count
bound, not a fidelity one. S02 needs 60–130 s material, so it runs on the
`longform` lane, which `HARNESS.md` §2.4 names and which the foundation commit
builds and the baseline covers, before this plan runs. Its construction is
specified here and summarised there; the manifest schema does not change.

**Construction (deterministic, pure numpy, no network).**

- Four cells: `band ∈ {"60": [60.0, 90.0] s, "120": [100.0, 130.0] s}` ×
  `gap_ms ∈ {300, 900}`. **15 clips per cell → 60 clips.**
- Cell order is fixed: `("60",300), ("60",900), ("120",300), ("120",900)`,
  index `ci ∈ 0..3`. For clip `j ∈ 0..14`:
  `rng = random.Random(LONGFORM_SEED + 1000*ci + j)` with `LONGFORM_SEED = 20260829`.
- Members are drawn from the **`base` lane only** (the 100 selected clips,
  ids sorted lexicographically): `order = rng.sample(ids, len(ids))`. Walk
  `order`, appending a member if the running total (speech + gaps) stays ≤ the
  band's upper bound, and stop as soon as it reaches the lower bound. If the
  walk exhausts `order` without reaching the lower bound, exit 2 (cannot
  happen: the base lane is ≈12 min of audio).
- Between consecutive members, insert `gap_ms` of Gaussian noise at −60 dBFS
  RMS using `HARNESS.md` §2.4's generator and dtype, seeded
  `zlib.crc32(longform_id.encode()) ^ (gap_ms * 7919 + member_index)`. No gap
  before the first member or after the last.
- `id = f"longform-{band}s-g{gap_ms}-{j:02d}"`; written 16 kHz mono 16-bit PCM to
  `build/asr-corpus/wav/longform/<id>.wav`.
- `reference` = the member references joined by a single space (LibriSpeech is
  uppercase with no punctuation, so concatenation is lossless).
- `lane = "longform"`; `tags = ["longform", f"band={band}s", f"gap={gap_ms}ms"]`;
  `derived_from = null` (a long clip has many parents);
  `augmentation = {"kind": "concatenation", "members": [<ids in order>],
  "gap_ms": <gap_ms>, "rms_dbfs": -60.0}`.

  **Tag collision, deliberately avoided.** `HARNESS.md` §2.2 step 5 makes the
  duration stratum a *tag*, and one of those strata is called `long`
  (15–35 s base clips) — `Q05-repetition-penalty.md`'s selector literally tests
  for that stratum name in a clip's tags. This lane is therefore named
  `longform`, and its clips carry the tag `longform`, never the stratum tag: no
  `lanes` list and no `tags_any` filter can confuse a 20 s base clip with a 110 s
  concatenation. Lane and tag share the one name deliberately — there is nothing
  the two could disagree about, and a reader who sees either knows which clips
  are meant.

**Why two gap settings.** `_VAD_PARAMETERS` uses
`min_silence_duration_ms = 500` and `speech_pad_ms = 250`
(`model.py:32-37`). A **300 ms** gap is below the silence minimum: members
merge into one long speech region, which the batched path must split at
`max_speech_duration_s = 30` and the sequential path windows at exact 30 s
offsets — near-identical boundaries. A **900 ms** gap exceeds it: each member
becomes its own VAD region, and the two paths' boundaries diverge (batched
merges greedily via `collect_chunks`, sequential concatenates then cuts at
30 s). Chunk-boundary alignment is what determines whether a word straddles a
cut, so it is the variable that most plausibly separates the paths on WER and
deletions.

**Caveat to record in §8:** 60 long clips are built by reusing 100 base clips
≈8× each, so long-lane WER is not an independent estimate of model accuracy.
It is only ever compared *across variants on the same lane*, which is all §6
does with it.

**Manifest digests — settled.** Adding a lane moves `manifest_sha256`, but
`HARNESS.md` §2.5 records a `lane_sha256` per lane and §6.4 refuses only on the
digests of the lanes a comparison actually scores, so a lane addition costs no
one a re-baseline (§7.3 case 2 now reads "the compared lanes changed"). The
`longform` lane also lands in the foundation commit and is inside the baseline
from the start (§3.3). S02 is doubly unaffected: it compares against its own
control run on the same manifest. See §9.3 item 2.

### 3.4 New pure metrics in `scripts/asr_metrics.py`

Added beside the existing ones, each with worked examples turned into
seen-to-fail tests (`HARNESS.md` §5 convention):

```python
def deletion_runs(ops) -> list[int]:
    """Lengths of maximal consecutive runs of 'del' ops, in reading order."""

def max_deletion_run(ops) -> int:
    """max(deletion_runs(ops)), or 0."""
```

Worked examples (`ops` from `align`, `HARNESS.md` §5.2):

- ref `a b c d e`, hyp `a e` → ops `match del del del match` →
  `deletion_runs = [3]`, `max_deletion_run = 3`.
- ref `a b c`, hyp `a b c` → `[]`, `0`.
- ref `a b c d`, hyp `a c` → `match del match del` → `[1, 1]`, `1`.

Per-clip record (`HARNESS.md` §4.1) gains `max_deletion_run: int`.
`clip_scores` (§4.3) gains the same key, so `decide` can use it.
`aggregate` (§4.2) gains:

- `large_deletion_run_rate` — fraction of scored clips with
  `max_deletion_run >= LARGE_DELETION_RUN = 25`.
- `max_deletion_run_p95` — nearest-rank p95 of the per-clip values.
- `error_kinds` — `{exception class name: count}` over clips with `error` set.
  Costs nothing (`error` is already a class name, §4.1) and is how §6 reports
  the `PathologicalOutputError` count.
- `segments_p50` — nearest-rank p50 of the per-clip `segments`, so §2.2's `K`
  vs `W` question is answerable from `result.json`.

**Why 25.** A normal alignment deletion run is 1–3 words. A skipped 30 s
window is ≈75 reference words; a half-window ≈35. 25 sits an order of
magnitude above alignment noise and safely below one lost window, so the
metric counts real drops and nothing else.

### 3.5 Threshold guards and repeat pooling

`HARNESS.md` §6.1 carries the `guards` array, and this plan uses it as it
stands — nothing here extends the schema. S02 declares four one-sided
non-inferiority guards beside its target (the fifth, the absolute decode floor,
is §6.1's `min_improvement` and appears in §6.2):

```json
"guards": [
  {"metric": "trailing_junk_rate",       "direction": "lower",  "max_regression": 0.0, "margin_kind": "absolute"},
  {"metric": "leading_word_recall_mean", "direction": "higher", "max_regression": 0.0, "margin_kind": "absolute"},
  {"metric": "large_deletion_run_rate",  "direction": "lower",  "max_regression": 0.0, "margin_kind": "absolute"},
  {"metric": "errors",                   "direction": "lower",  "max_regression": 0.0, "margin_kind": "absolute"}
]
```

`direction` names the *improving* direction, matching `target.direction`. A
guard passes iff the run value is no worse than the baseline value by more than
`max_regression` in that direction (`absolute`: `baseline ± max_regression`;
`relative`: `baseline × (1 ± max_regression)`). Pure, and each guard is one
seen-to-fail test.

`S01-cold-start-latency.md` §6.2 keeps an *object* of per-metric ratio keys, but
that file is read by S01's own rig and never by `decide` (S01 §6.2), so the two
spellings never meet. The array here is the canonical one.

**Repeat pooling.** `HARNESS.md` §3 (`repeats`) states the rule this plan needs
and the runner implements it: `aggregate` pools every `(clip_id, repeat)` row as
one observation for the speed percentiles; text metrics are identical across
repeats at temperature 0 and the runner **asserts** it — any clip whose
`hypothesis_norm` differs between repeats is reported in `report.md` and exits 2
as a determinism violation; `min_clips` counts distinct clip ids; and `decide`'s
intersection is over `clip_id`, with all of that clip's repeats on both sides.
S02 runs `repeats: 3` at temperature 0 purely for latency stability.

### 3.6 Engine

`HARNESS.md` §3.1 requires `subprocess` only of an experiment whose target is
`load_ms_*` or `first_response_ms_*`; one targeting `decode_ms_*` or `rtf_*`
through a `DecodeOptions` field runs `inprocess` with both sides on the same
engine. `batched` is a `DecodeOptions` field and the target is `decode_ms_p50`,
so S02 runs **`engine: "inprocess"` on both sides of every comparison**, which
§3.1 blesses for this metric ("Cross-engine comparisons are valid for text
metrics and `decode_ms`") and which satisfies §6.4's same-engine refusal. `load_ms` and
`first_response_ms` are `null` for S02 (fewer than 10 cold clips per run,
§4.2) and are not its target — S01 owns them.

---

## 4 Variant matrix

Every variant is checked in under `docs/experiments/variants/S02/`. Every one
uses `"engine": "inprocess"`, `"repeats": 3`, `"plan": "S02"`, and an empty
`config` block (shipped defaults: `beam_size = 1`, `compute_type = "int8"`,
`vad_filter = true`, `silence_threshold = 0.6`, `hotwords = ""`,
`initial_prompt = ""`).

| # | name / file | lanes | `decode` | role |
|---|---|---|---|---|
| C0 | `s02-control.json` | `["longform"]` | `{}` | **control**; run through the `baseline` subcommand so it carries a `noise` block (§5.2) |
| V1 | `s02-batched-b4.json` | `["longform"]` | `{"batched": true, "batch_size": 4, "without_timestamps": true}` | primary |
| V2 | `s02-batched-b8.json` | `["longform"]` | `{"batched": true, "batch_size": 8, "without_timestamps": true}` | primary |
| V3 | `s02-batched-b16.json` | `["longform"]` | `{"batched": true, "batch_size": 16, "without_timestamps": true}` | primary; VRAM probe (§8.1) |
| D1 | `s02-seq-no-halluc.json` | `["longform"]` | `{"hallucination_silence_seconds": null}` | diagnostic: isolates the option the batched path discards (`transcribe.py:546`) from the chunking change |
| D2 | `s02-batched-b8-ts.json` | `["longform"]` | `{"batched": true, "batch_size": 8, "without_timestamps": false}` | diagnostic: isolates the segmentation change; decoder timestamps inside chunks, timestamp tokens back on the budget |
| R0 | `s02-control-base.json` | `["base"]` | `{}` | regression control (in-process, so it is comparable to R1; `docs/experiments/baseline.json` is subprocess and §6.4 would refuse) |
| R1 | `s02-batched-b8-base.json` | `["base"]` | `{"batched": true, "batch_size": 8, "without_timestamps": true}` | regression guard: what happens if batching is (wrongly) applied below 30 s |

Example (`docs/experiments/variants/S02/s02-batched-b8.json`):

```json
{
  "schema": 1,
  "name": "s02-batched-b8",
  "plan": "S02",
  "lanes": ["longform"],
  "tags_any": [],
  "tags_all": [],
  "engine": "inprocess",
  "repeats": 3,
  "config": {},
  "decode": {"batched": true, "batch_size": 8, "without_timestamps": true}
}
```

`without_timestamps: true` on V1–V3 is the library's own batched default
(`transcribe.py:283`) and is what a shipped batched path would use; D2 tests
the alternative. C0/D1/R0 leave it at `false`, the sequential default.

---

## 5 Procedure

Every command runs from the repo root with the repo venv. No step requires a
human. Flag spellings for `asr_experiment.py` / `asr_corpus.py` subcommands
follow `HARNESS.md` §1 and §7.1; if the implemented CLI differs, take the
spelling from `--help` — the *sequence* below is the contract.

### 5.0 Land the prerequisites

```sh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration"
git status --porcelain          # MUST be empty before 5.2
```

A non-empty tree at 5.2 is a stop: `preflight` records `git_dirty` and the
`baseline` subcommand refuses to write from a dirty tree (`HARNESS.md` §8.2).

### 5.1 Confirm the `longform` lane and preflight

The foundation commit already built it (§3.3); `build` is idempotent and
re-running it costs minutes.

```sh
.venv/bin/python scripts/asr_corpus.py build --lanes longform
.venv/bin/python scripts/asr_experiment.py preflight --lanes longform,base
```

`preflight` exit `2` → stop and report; the likely causes are the model not
being cached (`stenographer model download`), no CUDA device, or a WAV whose
SHA-256 does not match the manifest.

### 5.2 Control run (writes the comparison basis, with noise)

```sh
.venv/bin/python scripts/asr_experiment.py baseline \
  --variant docs/experiments/variants/S02/s02-control.json \
  --lanes longform --engine inprocess --repeats 3 \
  --out build/asr-experiments/s02-control.json
```

and the `base`-lane control:

```sh
.venv/bin/python scripts/asr_experiment.py baseline \
  --variant docs/experiments/variants/S02/s02-control-base.json \
  --lanes base --engine inprocess --repeats 3 \
  --out build/asr-experiments/s02-control-base.json
```

Both land under `build/`, not `docs/`: they are lane- and engine-specific
controls, not the programme baseline. Exit `2` → stop. Record from
`s02-control.json`, for §6's ceiling check: `decode_ms_p50`, `segments_p50`,
and the `noise` spread of `decode_ms_p50`.

### 5.3 VRAM sampling (wraps 5.4; no harness change)

```sh
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits -l 1 \
  > build/asr-experiments/s02-vram.log &
VRAM_PID=$!
```

…run 5.4…

```sh
kill "$VRAM_PID"
sort -n -t, -k1 build/asr-experiments/s02-vram.log | tail -1   # peak MiB used
```

### 5.4 The runs

In this order, so a VRAM failure at b16 lands last:

```sh
for V in s02-batched-b4 s02-batched-b8 s02-batched-b16 s02-seq-no-halluc s02-batched-b8-ts; do
  .venv/bin/python scripts/asr_experiment.py run \
    --variant "docs/experiments/variants/S02/$V.json" \
    --baseline build/asr-experiments/s02-control.json \
    --thresholds docs/experiments/variants/S02/thresholds.json
  echo "$V -> exit $?"
done

.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/S02/s02-batched-b8-base.json \
  --baseline build/asr-experiments/s02-control-base.json \
  --thresholds docs/experiments/variants/S02/thresholds-base.json
echo "base guard -> exit $?"
```

Exit-code handling, per run:

- `0` — accepted against the control. Keep going; §6.3 picks the winner.
- `1` — denied. Not a stop: record the verdict line and continue. D1/D2 are
  diagnostics and are *expected* to be denied on some guard; their value is
  the numbers, not the verdict.
- `2` — harness error. Stop, and report the message verbatim (it carries no
  transcript text). A CUDA OOM at b16 surfaces here or as a per-clip `error`;
  either way see §8.1.

### 5.5 Write the outcome

Regardless of the verdicts:

```sh
mkdir -p docs/experiments/results
for f in build/asr-experiments/*s02-*/verdict.json; do
  cp "$f" "docs/experiments/results/S02-$(basename "$(dirname "$f")").json"
done
```

Then append the unnumbered `## Outcome` section to this file (`HARNESS.md` §10):
every variant's verdict line,
its run id, the measured `decode_ms_p50` / `segments_p50` / `rtf_p50` /
`wer_mean` / `trailing_junk_rate` / `leading_word_recall_mean` /
`large_deletion_run_rate` / `error_kinds`, the peak VRAM from 5.3, and the
§2.2 ceiling recomputed from the control's own `decode_ms_p50` and
`segments_p50`. **Numbers only.** Set `Status:` to `accepted` or `denied`.

---

## 6 Metrics & accept/deny

### 6.1 Target

`decode_ms_p50`, direction `lower`, margin `0.30`, `margin_kind: relative` —
justified against the §2.2 ceiling (68 % floor-model, 51 % with a realistic
marginal batch cost), so 30 % is demanding but well inside what the mechanism
can deliver, and far outside this machine's repeat noise.

The **absolute floor** (`decode_ms_p50` must also fall by ≥ 400 ms) is not
expressible in `thresholds.json`'s target schema. Encode it as one more entry
in the §3.5 `guards` array, `{"metric": "decode_ms_p50", "direction":
"lower", "min_improvement": 400.0, "margin_kind": "absolute"}`.
`min_improvement` is `HARNESS.md` §6.1's third bound and means exactly this: the
run must beat the baseline by at least that much. No negative number is
involved, and none should be — a negative `max_regression` would be the same
arithmetic spelled so that nobody could read it back.

### 6.2 `docs/experiments/variants/S02/thresholds.json`

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.00,
  "forbid_empty_regressions": true,
  "target": {
    "metric": "decode_ms_p50",
    "direction": "lower",
    "margin": 0.30,
    "margin_kind": "relative"
  },
  "guards": [
    {"metric": "decode_ms_p50",            "direction": "lower",  "min_improvement": 400.0, "margin_kind": "absolute"},
    {"metric": "trailing_junk_rate",       "direction": "lower",  "max_regression": 0.0,    "margin_kind": "absolute"},
    {"metric": "leading_word_recall_mean", "direction": "higher", "max_regression": 0.0,    "margin_kind": "absolute"},
    {"metric": "large_deletion_run_rate",  "direction": "lower",  "max_regression": 0.0,    "margin_kind": "absolute"},
    {"metric": "errors",                   "direction": "lower",  "max_regression": 0.0,    "margin_kind": "absolute"}
  ],
  "lanes": ["longform"],
  "min_clips": 60
}
```

`rtf_p95_max_ratio: 1.00` rather than `HARNESS.md`'s usual `1.25`: this is a
speed plan, so the tail must not get worse at all.

`docs/experiments/variants/S02/thresholds-base.json` is the regression guard —
same guards, `"lanes": ["base"]`, `"min_clips": 100`, and **no target at all**
(`"target": null`, `HARNESS.md` §6.1) so the base lane can only ever deny, never
carry the decision:

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.25,
  "forbid_empty_regressions": true,
  "target": null,
  "guards": [
    {"metric": "trailing_junk_rate",       "direction": "lower",  "max_regression": 0.0, "margin_kind": "absolute"},
    {"metric": "leading_word_recall_mean", "direction": "higher", "max_regression": 0.0, "margin_kind": "absolute"},
    {"metric": "large_deletion_run_rate",  "direction": "lower",  "max_regression": 0.0, "margin_kind": "absolute"},
    {"metric": "errors",                   "direction": "lower",  "max_regression": 0.0, "margin_kind": "absolute"}
  ],
  "lanes": ["base"],
  "min_clips": 100
}
```

The `errors` guard is how the `PathologicalOutputError` count enters the
decision: `HARNESS.md` §6.2 rule 5 already denies a clip that errors in the
run but succeeded in the baseline, and `error_kinds` (§3.4) makes the class
breakdown reportable without adding a rule.

### 6.3 Deciding the matrix

**Best accepted by target metric**, not first-in-order: among V1/V2/V3 that
exit `0`, the winner is the one with the lowest `decode_ms_p50`; ties break to
the **smallest** `batch_size` (less VRAM, less variance). D1 and D2 never win —
they are diagnostics. If no V accepts, S02 is **denied**, whatever D1/D2 show.

The base-lane guard (R1) is a veto, not a vote: if it exits `1`, the accepted
long-lane variant may still ship, but **only** behind the `audio_seconds > 30`
selection predicate (§9.1) — which is the design anyway. R1 denying is the
evidence that the predicate is load-bearing; R1 accepting means the predicate
is merely an optimisation and can be defended on cost alone.

### 6.4 What the numbers must be read for even on accept

- `segments_p50` on the batched runs vs `ceil(vad_seconds/30)` on the control:
  confirms §2.2's `K ≈ W` claim on real audio, and explains any shortfall
  against the ceiling.
- The `gap=300ms` vs `gap=900ms` `per_lane`-style split (use `tags_all` to
  re-run, or read the per-clip rows): if the two gap regimes disagree by more
  than the target margin, the win depends on pause structure and the §9.1
  predicate needs re-thinking.
- D1 vs C0 on `trailing_junk_rate`: how much of any batched junk regression is
  the discarded `hallucination_silence_threshold` alone.
- D2 vs V2: how much is the segmentation / timestamp-token change.

---

## 7 Cost estimate

Per `HARNESS.md` §8.4's method (`clips × repeats × per-clip time`), with
in-process per-clip time = read + resample + gate + decode, and long-lane
decode modelled from §2.2 (`f + c·W`; band 60 ≈ 2.6 s, band 120 ≈ 3.4 s, mean
≈ 3.0 s; batched assumed ≈1.8 s).

| Step | clips × repeats | per clip | wall |
|---|---|---|---|
| Build the `longform` lane (numpy + WAV writes, no GPU) | 60 | — | ≈5 min |
| `preflight` (one cold load) | — | — | ≈1 min |
| C0 control, `longform` | 60 × 3 | ≈3.2 s | ≈10 min |
| V1/V2/V3 batched, `longform` | 3 × 60 × 3 | ≈2.0 s | ≈18 min |
| D1 seq no-halluc, `longform` | 60 × 3 | ≈3.2 s | ≈10 min |
| D2 batched b8 timestamps, `longform` | 60 × 3 | ≈2.2 s | ≈7 min |
| R0 control, base | 100 × 3 | ≈0.75 s | ≈4 min |
| R1 batched b8, base | 100 × 3 | ≈0.75 s | ≈4 min |
| **Total GPU wall** | | | **≈55 min**, budget **1 h 30 m** with loads and slack |

Disk: `longform` lane WAVs ≈ 60 × 95 s × 32 kB/s ≈ **185 MB** under
`build/asr-corpus/wav/longform/`, on top of `HARNESS.md` §8.4's existing budget;
eight run directories a few MB each; `s02-vram.log` < 1 MB. Total still inside
the 1 GiB `build/` budget, but re-check `preflight`'s free-space assertion
after the lane is built.

Implementation effort (not GPU time): the `DecodeOptions` fields and the
`Model.transcribe` branch are small; the `longform` generator and the four new
pure metrics plus their seen-to-fail tests are the bulk.

---

## 8 Risks, confounds, invariants

### 8.1 VRAM at `batch_size = 16`

The reference machine is an RTX 3080 Laptop (8 GiB). `medium.en` at
`int8_float16` is ≈800 MB of weights; a batch of 16 × 30 s encoder activations
(1500 frames × 1024 dims) plus the decoder KV cache is the variable part. At
the shipped `beam_size = 1` this should fit with room; **at `beam_size = 5`
the effective decoder batch is 80 sequences** and it may not. S02 runs at
`beam_size = 1` (shipped default), so a b16 OOM is unlikely but is the
first thing to check if V3 exits `2` or produces per-clip `error` rows. §5.3's
`nvidia-smi` sampling exists to answer it with a number.

Consequence for the future: if Q03 later raises `beam_size`, the accepted
`batch_size` must be re-validated for VRAM. Record that in the §9 follow-up
so it is not discovered by a user's OOM.

### 8.2 Different segmentation moves the density check

`_validate_output` raises `PathologicalOutputError` when the word count
exceeds `max(12, ceil(8 × vad_seconds))` (`model.py:28-29`, `:200-204`). The
denominator, `vad_seconds`, comes from `info.duration_after_vad`, which both
paths compute as the total kept speech duration
(`transcribe.py:453-456` batched, `transcribe.py:893` sequential) — so the
*limit* is unchanged. What changes is the numerator's provenance: the batched
path's chunk-granular `no_speech_prob` (§2.3) means `_assemble`'s gate keeps
or drops whole chunks, so a chunk that the sequential path would have
partially gated now contributes all of its words. Watch `error_kinds` for
`PathologicalOutputError` on every batched run; a rise is a deny via the
`errors` guard and a design signal, not a flake.

Second, narrower risk in the same family: `_validate_output` also rejects
`end > audio_seconds + 1.0`. The batched path reconstructs original-timeline
timestamps through `restore_speech_timestamps`
(`transcribe.py:1844-1870`) using `chunks_metadata` offsets built by
`collect_chunks`, whose post-flush branch (`vad.py:223-226`) does not append
the flushed-into chunk to `current_segments`. That field is unused on this
path, so the arithmetic should hold — but "invalid decoder timestamp" is a
plausible batched-only failure and is exactly what `error_kinds` will name.

### 8.3 Confounds

- **Long-lane WER is not an accuracy estimate.** 60 long clips reuse 100 base
  clips ≈8× (§3.3). Valid across variants on the same lane; meaningless
  against published LibriSpeech numbers or against the `base` lane.
- **Two changes in one variant.** V1–V3 change *both* the execution path and
  `without_timestamps`. D2 separates them; if V2 and D2 disagree materially,
  the shipped choice must be re-derived rather than assumed.
- **Option drops are not degrees.** §2.3's table is the confound list. The one
  that will actually move numbers today is
  `hallucination_silence_threshold` → `None`; `temperature` ladders and
  `initial_prompt` are inert at the shipped defaults but would become live
  confounds if Q01 or Q08 is merged first. **Re-run S02 after any accepted
  Q01/Q08 change**, and say so in the outcome section.
- **`vad_filter = false` is untested and unsafe on the batched path**
  (`transcribe.py:414-418`). S02 never sets it; §9.1's shipped predicate must
  refuse the batched path when it is false.
- **Thermals / clocks.** `repeats: 3` pooled (§3.5) is the mitigation; the
  control's `noise` block is the measurement of what is left.

### 8.4 `HARNESS.md` §9 invariant checklist, restated

- **No transcript text.** The in-process engine installs no logging, so no
  `stenographer.log` is written at all. Text exists only in
  `build/asr-experiments/<run-id>/clips.jsonl`. Nothing in
  `result.json`, `report.md`, `verdict.json`, stdout, this file's Outcome
  section, `docs/experiments/results/`, or `docs/experiments/variants/S02/`
  carries a hypothesis, a reference, or a normalized token list. The `longform`
  lane's `reference` fields live in the manifest under `build/`, same as every
  other lane.
- **No network in the ASR path.** `Model` keeps `local_files_only=True`
  (`model.py:87`). The `longform` lane is generated from already-fetched audio and
  opens no socket; S02 adds no new download.
- **No platform imports.** S02 touches `scripts/` and
  `src/stenographer/transcribe/model.py` only; neither imports
  `stenographer.platform.linux`, `evdev`, `fcntl`, or anything in
  `tests/platform/test_core_isolation.py`'s `BLOCKED` tuple.
- **Test policy** (`AGENTS.md` hard rule 4). Every new test is a pure
  function's — `deletion_runs`, `max_deletion_run`, the guard loop in
  `decide`, the `longform`-lane member-selection arithmetic on synthetic arrays,
  `validate_variant`'s three new rejections, the `DecodeOptions()` pinning
  dict, and the shipped selection predicate of §9.1. Each is written, watched
  to fail against the unmodified code, then implemented. Nothing mocks
  `WhisperModel`, `BatchedInferencePipeline`, `soundfile`, or `subprocess`.
- **Fixed behaviour stays fixed.** `DecodeOptions()`'s defaults still describe
  today's shipped decode; nothing under `src/` constructs a non-default
  instance *unless S02 is accepted*, at which point §9.1's change makes the
  batched selection a property of `Model`, not of `DecodeOptions` — user
  config keeps exactly 23 keys in 4 sections either way (`AGENTS.md` hard
  rule 9).
- **Venv only**, SPDX header on every new `.py`, ruff clean at line length
  100, py312 syntax.

---

## 9 Deliverables & follow-through

### 9.1 On accept — the code change

1. **`src/stenographer/transcribe/model.py`**
   - New module constant beside `_MAX_NEW_TOKENS` (`model.py:26`):
     `_BATCHED_MIN_SECONDS = 30.0` — one Whisper window; below it there is a
     single window and batching can only add overhead (R1 is the evidence).
   - New **pure** predicate, unit-tested and seen to fail:
     ```python
     def use_batched(audio_seconds: float, *, vad_filter: bool, enabled: bool) -> bool:
         """Batched decoding needs VAD chunking and more than one window."""
         return enabled and vad_filter and audio_seconds > _BATCHED_MIN_SECONDS
     ```
     The `vad_filter` term is not optional: `transcribe.py:414-418` raises on
     audio ≥ 30 s with VAD off.
   - `Model.transcribe` (`model.py:110-125`) branches on it, calling
     `BatchedInferencePipeline(self._impl).transcribe(..., batch_size=<the
     accepted value>, without_timestamps=<the accepted value>)`. Keep
     materialising the generator into a list (`model.py:126-138`) so
     `last_speech_timestamp` is reset (`transcribe.py:617`).
   - `DecodeOptions.batched` flips to `True` and `batch_size` to the accepted
     value; **update the pinning test in the same commit** (`HARNESS.md`
     §3.2). `enabled` above is `self._options.batched`, so the harness can
     still force it off for a control.
   - Add a `decode_path=sequential|batched` key to the existing
     `asr: decode_complete` log line (`model.py:146-155`) — a bare enum, no
     transcript content, and the only way a user's report distinguishes the
     two paths (`AGENTS.md` hard rule 6).
2. **`src/stenographer/transcribe/worker.py:43-45` — verify, do not change.**
   `decode_timeout_seconds` is `max(60.0, 4.0 × audio_seconds)`
   (`worker.py:128-137`, used at `worker.py:356-362`). At the measured
   long-lane `rtf` (≈0.03 sequential, lower batched) the deadline holds with
   two orders of magnitude of headroom, and the batched path only shortens
   decodes. Confirm from the accepted run's `rtf_p95` that
   `rtf_p95 × 4 < 4.0` — i.e. that no clip approached the deadline — and
   record the number. `_MODEL_LOAD_TIMEOUT_SECONDS` is untouched: the batched
   pipeline wraps an already-loaded `WhisperModel` and loads nothing.
3. **`AGENTS.md`** — two edits, in the same commit as the code:
   - Hard rule 5, the sentence "The anti-hallucination decode stack (VAD
     pre-filter, no-speech gate, silence trimming, short-audio token ceiling,
     output validation) is fixed behavior, not configuration." Add: utterances
     longer than one 30 s window decode through faster-whisper's batched
     pipeline, which applies the VAD pre-filter as chunking and **does not
     apply the hallucination-silence skip** (`transcribe.py:546`); the choice
     is `audio_seconds`-driven, not configurable, and S02's numbers are the
     record that it costs no measured quality.
   - The architecture map's `transcribe/` row, `model.py` clause: name the
     dual decode path and the `> 30 s` selection.
4. **Tests.** The `use_batched` predicate test; the updated `DecodeOptions()`
   pinning dict; a test that `_token_budget` is unchanged (the batched path
   consumes it per chunk, so its value must not be retuned in the same
   commit).

### 9.2 On accept — re-baseline and acceptance gates

- **Re-baseline** per `HARNESS.md` §7.3 case 1 (shipped defaults moved) once
  the change is merged to `dev`. Case 2 does not apply: the `longform` lane is
  in the baseline from the start (§3.3) and its `lane_sha256` does not move. The
  re-baseline commit touches `docs/experiments/baseline.json` only.
- **`AGENTS.md` acceptance gates, on a real machine before dev → main**, in
  addition to the standing list:
  - `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest` green.
  - Real dictation end-to-end in `hold`, `toggle` and `hybrid`.
  - **New for S02:** one real dictation longer than 60 s (easiest in hybrid:
    tap to latch, speak, press to stop), whose `pipeline: utterance` line
    shows `decode_ms` materially below the pre-change figure for comparable
    `audio_frames`, and whose `asr: decode_complete` line reports
    `decode_path=batched`; and one dictation under 30 s reporting
    `decode_path=sequential`. Inspect `stenographer.log` and the journal for
    metrics only — no transcript, no audio.
  - A latched hybrid recording that runs to `audio.max_recording_seconds`
    still ends at the cap and still decodes within the worker deadline.

### 9.3 Forks to settle before running (recommendations)

1. **S-series engine rule — settled.** `HARNESS.md` §3.1 now keys the engine to
   the target metric, not to the plan's letter: `subprocess` when the target is
   `load_ms_*` or `first_response_ms_*`, `inprocess` when it is `decode_ms_*` or
   `rtf_*` behind a `DecodeOptions` field, both sides on the same engine either
   way. §3.6 is written against that rule.
2. **Manifest digest granularity — settled.** `HARNESS.md` §2.5 now records
   `corpus.lane_sha256` (a digest per lane over that lane's manifest rows)
   alongside `manifest_sha256`, and §6.4 refuses on the digests of the
   *compared* lanes only, which decouples a lane addition from every other
   plan's comparisons. The `longform` lane also lands in the foundation commit
   (§3.3), so it is inside the baseline rather than added after it.
3. **How batched is selected in the harness.** Recommendation as written: a
   `DecodeOptions.batched` field, **not** a harness-level flag. It keeps
   `HARNESS.md` §3.2's property that everything affecting the decode is in the
   variant's `decode` block and is copied verbatim into `result.json`, and it
   makes the experiment's seam and the shipped seam the same object.
4. **`thresholds.json` guards spelling — settled.** The **array** form is the
   one mechanism (`HARNESS.md` §6.1), with `max_regression`, `max_absolute` and
   `min_improvement` as its three bounds. S01 §6.2's per-metric ratio object
   stays, but only because S01's own rig reads it and `decide` never does.
5. **Repeats at temperature 0 — settled.** `HARNESS.md` §3 (`repeats`) now
   states the pooling and determinism-assertion rule for any `repeats > 1`,
   whatever the temperature; §3.5 restates it. The alternative — three separate
   `repeats: 1` runs and a hand-picked median — needs a human, which
   `docs/experiments/README.md` forbids.

### 9.4 On deny

Append the unnumbered `## Outcome` section described in §5.5 (`HARNESS.md` §10),
copy each `verdict.json` to `docs/experiments/results/S02-<run-id>.json`, and set
`Status: denied`.
Numbers only. Also state, from D1 and D2, *why*: a WER or junk regression
traceable to the discarded `hallucination_silence_threshold` (D1 shows it too)
is a different finding from one traceable to chunk-boundary segmentation (D2
shows it too), and the second would justify a follow-up plan that passes
`clip_timestamps` explicitly to control the chunking. Revert the
`DecodeOptions` fields only if no follow-up is planned; leaving them at their
`False` defaults costs nothing and keeps the seam.

---

## 10 Out of scope

- **Cold-start latency** — model load, imports, `lock_wait_ms`: **S01**.
- **`asr.idle_unload_seconds` and the reload penalty**: **S03**.
- **`beam_size`** as a speed/quality knob: **Q03**. S02 runs at the shipped
  `beam_size = 1` throughout and only *notes* the VRAM interaction (§8.1).
- **`compute_type`**: **Q04**, which must settle before S02's numbers are
  taken as final; if Q04 changes the default, re-run S02's control.
- **Temperature ladders** (**Q01**) and **`initial_prompt`** (**Q08**): both
  behave differently on the batched path (§2.3) and both are inert at today's
  defaults. S02 does not test them; it records that they are S02's tripwires.
- **Tuning the VAD chunking itself** — `vad_threshold`,
  `min_silence_duration_ms`, `speech_pad_ms`: **Q02**. S02 holds
  `_VAD_PARAMETERS` at the shipped values on both paths.
- **`hallucination_silence_threshold` as a tunable**: **Q07**. S02's D1 cell
  measures only the on/off case it needs to attribute a batched regression,
  on the `longform` lane; Q07 owns the `tail`-lane grid.
- **Post-decode tail filtering** as an alternative junk remedy: **Q11**.
- **Streaming or incremental decoding** — a cut feature (`AGENTS.md`), not a
  variant.
- **Windows**: the harness is Linux-and-GPU-only by `HARNESS.md` §8.1; the
  `model.py` change is core and platform-neutral, and adds no host import.
