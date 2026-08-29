# ASR experiment harness — specification

Status: **specification** (2026-08-29). Nothing here is implemented yet. This
document is written so that an autonomous agent can implement the harness,
run it, and interpret its exit code without asking a human. Every decision an
implementer would otherwise have to make is made here; a section marked
*provisional* is a decision the owner can flip by editing that section alone.

Baseline for all `file:line` citations: `dev` @ `a1b9807` (v0.11.6),
faster-whisper 1.2.1, CTranslate2 4.8.1, in the repo venv.

The harness is development tooling under `scripts/`, on the model of
`scripts/cue_audition.py` + `docs/cue-audition.md`: it is never shipped, never
imported by `src/stenographer/`, writes only under the gitignored `build/`,
and is invoked as `.venv/bin/python scripts/<tool>.py`. `bench` is on the
`AGENTS.md` cut-features list; this harness is not `bench` and must not become
a `stenographer` subcommand.

---

## 1. Layout

| Path | Role | Tests |
|---|---|---|
| `scripts/asr_corpus.py` | Fetch LibriSpeech `test-clean` once, select the seeded subset, convert to 16 kHz mono WAV, generate the augmentation lanes, write `manifest.json`. The only harness piece that opens a network connection. Subcommands: `fetch [--prune-source] [--pin-sha256-on-first-fetch]`, `build --lanes <a,b,…>` (generates the named lanes; Q10's `augment` and `verify` are options of `build`, not subcommands of their own), `control` (Q11's separate control manifest). | `tests/test_asr_corpus.py` — pure parts only: subset selection, augmentation arithmetic on synthetic arrays, manifest rendering. |
| `scripts/asr_metrics.py` | Pure scoring: `normalize`, `align`, `wer`, `leading_word_recall`, `trailing_junk`, `aggregate`, `decide`. No I/O, no numpy needed, stdlib only. | `tests/test_asr_metrics.py` — every worked example in §5 and §6 becomes a test that was seen to fail first. |
| `scripts/asr_experiment.py` | Runner + CLI: `preflight [--variant PATH] [--lanes …]`, `baseline [--variant PATH] --lanes … --engine … --repeats N --out PATH [--manifest PATH]`, `run --variant PATH [--baseline PATH --thresholds PATH] [--manifest PATH] [--lanes …] [--no-compare]`, `compare`, `compare-paired` (Q10 §6.4), `tailprobe` (Q11 §3.5). A `--lanes` override on `run` is what the thresholds' `lanes` list is compared against. Owns subprocess calls, temp config rendering, in-process decode, result files. | `tests/test_asr_experiment.py` — the pure helpers only: `parse_summary_line`, `render_variant_config`, `validate_variant`, run-id formatting. |
| `docs/experiments/baseline.json` | The checked-in baseline (§7). Numbers only, never text. | `tests/test_asr_baseline_file.py` — globs `docs/experiments/*baseline*.json` (so a plan-local baseline is covered too) and asserts each file parses, has `schema == 1`, and that no clip row carries a text-valued field. |
| `build/asr-corpus/` | Corpus root (gitignored). | — |
| `build/asr-experiments/<run-id>/` | One directory per run (gitignored). | — |

Why the tests sit at `tests/test_asr_*.py` and not `tests/scripts/`: the
existing precedent for a `scripts/` module is `tests/test_cue_audition.py`,
which inserts `scripts/` on `sys.path` at module scope and imports the tool
directly (`tests/test_cue_audition.py:18-29`). There is no `tests/scripts/`
package and `conftest.py` collects by filename suffix only
(`tests/conftest.py:17-20`); a new subdirectory would be a second convention
for no gain. Do the same `sys.path.insert` in each new test module.

Why `asr_metrics.py` is its own module: `AGENTS.md` hard rule 4 wants pure
logic tested without mocks and the test:src ratio near 1:1. Splitting the
pure scorer from the runner means the scorer is tested exhaustively and the
runner's I/O is tested only through its handful of pure helpers — the same
split `cue_audition.py` makes between `render_cue` and `audition`.

`.gitignore` additions: **none**. `build/` is already ignored (`.gitignore`,
the `build/` entry under *Distribution / packaging*, repeated under
*PyInstaller*). The corpus, every run directory, the temp configs and the
per-run `stenographer.log` all live under `build/`.

Output directory contents for one run:

```
build/asr-experiments/<run-id>/
  variant.json        the validated variant exactly as run (§3)
  config.toml         the temp config handed to STENOGRAPHER_CONFIG (config lane)
  state/              XDG_STATE_HOME for subprocess runs: stenographer.log lands here
  clips.jsonl         one per-clip record per line (§4) — the only file with text
  result.json         environment + aggregates (§4); no text
  report.md           the Markdown table printed to stdout; no text
  verdict.json        present only when --baseline was given (§6)
```

`<run-id>` is `YYYYMMDDTHHMMSSZ-<variant name>` in UTC; the variant name is
`[a-z0-9-]{1,40}`.

---

## 2. Corpus (*provisional*)

### 2.1 Source

LibriSpeech `test-clean` (CC BY 4.0, `https://www.openslr.org/resources/12/test-clean.tar.gz`,
≈346 MB, 2620 utterances from 40 speakers, FLAC at 16 kHz, references in
`<speaker>-<chapter>.trans.txt` as `ID TEXT`, uppercase, no punctuation).
`scripts/asr_corpus.py fetch` downloads it into
`build/asr-corpus/source/test-clean.tar.gz`, verifies SHA-256 against the
constant `SOURCE_SHA256` in the script, and extracts it. The constant is
filled in from the first verified download and checked in with the script;
until then the script refuses `fetch` unless `--pin-sha256-on-first-fetch` is
given, and prints the digest to pin. Only this subcommand may open a network
connection; the ASR path stays offline (`AGENTS.md` hard rule 5).

### 2.2 Subset selection (seeded)

Deterministic and re-runnable: the same tarball must yield the same 100 ids.

1. Enumerate every utterance id in the archive, sorted lexicographically.
2. Read each utterance's duration from the FLAC header (`soundfile.info`).
3. Stratify by duration: `short` = `[2.0, 8.0)` s, `medium` = `[8.0, 15.0)` s,
   `long` = `[15.0, 35.0]` s. Utterances outside `[2.0, 35.0]` are excluded.
4. Draw `50` short, `30` medium, `20` long with
   `random.Random(CORPUS_SEED).sample(sorted_ids_in_stratum, k)` in that
   order, where `CORPUS_SEED = 20260829`.
5. The stratum name becomes a tag on the clip.

`audio.max_recording_seconds` is `600` (`src/stenographer/config.py:250`), so the
daemon would happily capture far longer than 35 s and the cap is not a fidelity
bound. It is a **window-count** bound: Whisper decodes in 30 s windows, so a clip
at or under 35 s is one window plus a short remainder and its per-clip `wer`,
`decode_ms` and `rtf` are dominated by a single window — comparable across clips
and across variants. Material that needs several windows is a separate lane with
its own metrics (`longform`, §2.4), never part of the `base` subset.

### 2.3 Conversion

Each selected FLAC is read with `soundfile.read(dtype="float32",
always_2d=True)`, reduced with `stenographer.transcribe.pipeline.downmix`
(channel 0, `src/stenographer/transcribe/pipeline.py:136-145`), resampled
with `stenographer.audio._resample_poly` if not already 16 kHz
(`src/stenographer/audio.py:104`), and written as 16 kHz mono 16-bit PCM WAV
to `build/asr-corpus/wav/base/<id>.wav`. Both helpers are core modules, so the
corpus tool sees exactly the samples the daemon would.

### 2.4 Augmentation lanes (pure numpy)

Every derived clip keeps the base clip's `reference`, records `derived_from`
and `augmentation`, and is written under `build/asr-corpus/wav/<lane>/`.

Every generator draws from `numpy.random.default_rng(seed)`, works in `float32`
throughout, and writes 16 kHz mono 16-bit PCM. Every seed is
`zlib.crc32(clip_id.encode())` combined with that lane's own parameters, so a lane
is reproducible from the manifest alone.

**`tail` lane — trailing room tone.** Append `seconds ∈ {1.0, 3.0, 5.0}` of
Gaussian noise at −60 dBFS RMS, seeded with `zlib.crc32(clip_id.encode()) ^
int(seconds * 1000)`, so the noise is deterministic per clip and duration. Tag `tail=<s>s`.
File name `<id>+tail<s>s.wav`. 300 clips.

**`cue` lane — leading start cue plus gap.** Prepend the bundled
`minimal-ui/record_start.wav` (48 kHz mono, 72 ms; located via
`stenographer.delivery.feedback.bundled_sound_root()`,
`src/stenographer/delivery/feedback.py:61`) resampled to 16 kHz with
`_resample_poly`, scaled by `0.25` (−12 dB, the speaker-to-mic bleed level
this lane assumes; a real measurement can replace it by editing this
sentence), followed by `gap_ms ∈ {0, 100, 300}` of the same −60 dBFS noise,
then the speech. Tag `cue=minimal-ui` and `gap=<ms>ms`. File name
`<id>+cue<ms>ms.wav`. 300 clips. The `record_start` cue is the one the daemon
plays *after* capture has started (`AGENTS.md` hard rule 5, cue ordering), so
it is genuinely inside the captured audio.

**`quiet` lane — low-gain microphone (Q02 §3.1).** For each base clip and each
`target_peak_rms ∈ {0.030, 0.020}`, scale by `gain = target_peak_rms /
speech_gate_stats(...).peak_rms` (skip the clip when `gain > 1.0`; the lane never
amplifies), then add a seeded Gaussian floor at −60 dBFS so the SNR falls the way a
low-gain microphone's does instead of scaling with the speech. Tag
`quiet=<0.0NN>`, ids `<id>+quiet<mmm>`. 200 clips.

**`silence` lane — pure room tone (Q06 §F1a).** 20 clips of Gaussian noise at
−60 dBFS, durations `{3.0, 5.0, 8.0}` s, seeded `zlib.crc32(f"silence-{i}".encode())`,
`reference: ""`, `derived_from: null`, tag `silence`. Any text at all is
fabrication, which is what makes the lane a control.

**`onset` lane — leading non-speech and soft onsets (Q10 §3).** Two modes, 100
clips each. `leading_noise` prepends 300 ms of the same −60 dBFS noise and **no
cue** (tag `onset=tone300ms`, ids `<base>+tone300ms`). `soft_onset` prepends
nothing and instead ramps the clip's first 200 ms linearly from `0.25` to `1.0`
(tag `onset=soft`, ids `<base>+soft`). They are the controls that separate "the
cue" from "any weak onset".

**`longform` lane — multi-window utterances (S02 §3.3).** 60 clips of 60–130 s,
each a seeded concatenation of `base` clips separated by `gap_ms ∈ {300, 900}` of
−60 dBFS gap noise, references joined by one space, `derived_from: null`, tag
`longform` — never the duration stratum tag `long`, which means a 15–35 s base
clip (§2.2 step 5).

**Q09 probe lanes — `tail-n50`, `tail-n40`, `tail-room`.** The `tail` lane rebuilt
at −50 and −40 dBFS RMS, and once more from a recorded room-tone file when one is
present (skipped, with the fact recorded, when it is not). They exist so a `tail`
result can be read as a function of noise level rather than of one arbitrary level.

**`control` lane (Q11 §3.5)** is built by `asr_corpus.py control` into its **own**
manifest under `build/`, not into the corpus manifest, and is run with
`run --manifest <path>`; it therefore never moves `manifest_sha256`.

Every generator above lands in the foundation commit, **before** the baseline is
established (§7.1). A lane added afterwards changes `manifest_sha256` and forces a
re-baseline (§7.3 case 2), so there is no cheap way to defer one.

Further lanes are dropped in by writing clips under `wav/<lane>/` and
appending to the manifest with `lane` set: `user` (owner-recorded clips with a
typed reference) and `pseudo-gold` (the deleted `bench.py`'s strategy: decode
with `Systran/faster-whisper-large-v3` at beam 5 and treat that as the
reference — `git show 6149d83^:src/stenographer/bench.py`, `_GOLD_MODEL`).
The harness treats every lane identically; only plans decide which lanes they
run on.

### 2.5 Manifest schema

`build/asr-corpus/manifest.json`, schema 1:

```json
{
  "schema": 1,
  "sample_rate_hz": 16000,
  "source": {
    "name": "librispeech-test-clean",
    "url": "https://www.openslr.org/resources/12/test-clean.tar.gz",
    "license": "CC BY 4.0",
    "sha256": "<tarball digest>"
  },
  "subset": {"seed": 20260829, "size": 100, "strata": {"short": 50, "medium": 30, "long": 20}},
  "clips": [
    {
      "id": "1089-134686-0001",
      "wav": "wav/base/1089-134686-0001.wav",
      "sha256": "<wav digest>",
      "reference": "STUFF IT INTO YOU HIS BELLY COUNSELLED HIM",
      "duration_s": 4.215,
      "lane": "base",
      "tags": ["short"],
      "derived_from": null,
      "augmentation": null
    },
    {
      "id": "1089-134686-0001+tail3s",
      "wav": "wav/tail/1089-134686-0001+tail3s.wav",
      "sha256": "<wav digest>",
      "reference": "STUFF IT INTO YOU HIS BELLY COUNSELLED HIM",
      "duration_s": 7.215,
      "lane": "tail",
      "tags": ["short", "tail=3s"],
      "derived_from": "1089-134686-0001",
      "augmentation": {"kind": "trailing_noise", "seconds": 3.0, "rms_dbfs": -60.0}
    }
  ]
}
```

Field rules:

- `id`: unique across lanes; derived ids are `<base id>+<suffix>`.
- `wav`: relative to the manifest's directory, forward slashes.
- `sha256`: of the WAV file bytes; `preflight` verifies every clip it will run.
- `reference`: the source text **verbatim** (uppercase for LibriSpeech). The
  harness normalizes at scoring time (§5.1) so a normalization fix never
  requires regenerating the corpus.
- `duration_s`: samples / 16000, three decimals.
- `lane`: one of `base`, `tail`, `cue`, `quiet`, `silence`, `onset`, `longform`,
  `tail-n50`, `tail-n40`, `tail-room`, `user`, `pseudo-gold` (§2.4); new lanes are
  a documentation change here, not a schema change.
- `tags`: free strings; variants filter with `tags_any` / `tags_all`.
- `derived_from`: base id or `null` (`null` also for a clip with many parents,
  such as a `longform` concatenation). `augmentation`: object or `null`. The
  `kind` values are:
  - `trailing_noise` — `{"seconds", "rms_dbfs"}`, plus `source:
    "synthetic"|"recorded"` and, when recorded, an optional `tone_sha256` of the
    room-tone file the lane was built from;
  - `leading_cue` — `{"pack": "minimal-ui", "cue": "record_start", "gain": 0.25,
    "gap_ms": 100, "rms_dbfs": -60.0}`;
  - `attenuated` — `{"target_peak_rms", "gain", "rms_dbfs"}`;
  - `pure_noise` — `{"seconds", "rms_dbfs"}`;
  - `leading_noise` — `{"seconds", "rms_dbfs"}`;
  - `soft_onset` — `{"onset_gain", "ramp_ms"}`;
  - `concatenation` — `{"members": [<ids in order>], "gap_ms", "rms_dbfs"}`.

The manifest's own SHA-256 is recorded in every result so a baseline and a
run are only ever compared on the same corpus (§6.4), and beside it a **per-lane**
digest: `lane_sha256` maps each lane name to the SHA-256 of that lane's manifest
rows, serialized as compact JSON with sorted keys in manifest order. `compare`
refuses on the digests of the *compared* lanes only (§6.4), so adding a lane the
comparison does not touch no longer invalidates it — only `manifest_sha256`
moves, and that field is then recorded rather than enforced.

---

## 3. Variants

A variant is one JSON file, validated by the pure `validate_variant` before
anything runs. Plans check their variants in under
`docs/experiments/variants/<plan>/<name>.json` (numbers and option names only,
no text beyond `initial_prompt` / `hotwords` values, which are configuration
not transcripts).

```json
{
  "schema": 1,
  "name": "q03-beam-1",
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

- `lanes`: non-empty subset of manifest lanes. `tags_any` / `tags_all`:
  optional filters applied after the lane filter.
- `config`: a two-level object `{section: {key: value}}` restricted to the
  sections `asr` and `audio` and to keys that exist in `stenographer.config`.
  It is rendered as `[stenographer.<section>]` tables into `config.toml` and
  passed via `STENOGRAPHER_CONFIG` (`src/stenographer/config.py:372-374`);
  the loader merges over defaults (`config.py:351`), so only overrides are
  written. The runner also writes `[stenographer.feedback] update_check =
  false` unconditionally. The rendered file is validated by `Config.load`
  before the first clip; a `ConfigError` is a harness error (exit 2).
- `decode`: fields of `DecodeOptions` (§3.2). Unknown fields are a harness
  error.
- `engine`: `auto` (the default), `subprocess`, or `inprocess`. `auto` resolves
  to `inprocess` when `decode` is non-empty and to `subprocess` otherwise. A
  non-empty `decode` with `engine: "subprocess"` is a harness error: the
  shipped CLI has no way to receive decode overrides, by design.
- `repeats`: `1` unless a temperature above zero is in play (§8.3), in which
  case `3`. `repeats > 1` is **always legal**, whatever the temperature. At
  temperature 0 the runner asserts that every clip's `hypothesis_norm` is
  identical across repeats (a mismatch is exit 2 and is listed in `report.md`),
  which turns a repeated run into a determinism check for free. `aggregate` pools
  every `(clip_id, repeat)` row for the speed percentiles; `min_clips` counts
  **distinct clip ids**, not rows; and `decide`'s intersection is over `clip_id`,
  with all of that id's repeats taken from both sides.

### 3.1 The two engines

**Subprocess engine** — the faithful one. Per clip, the runner spawns

```
.venv/bin/stenographer transcribe <wav>
```

with env `STENOGRAPHER_CONFIG=<run>/config.toml`,
`STENOGRAPHER_LOG_LEVEL=INFO`, `XDG_STATE_HOME=<run>/state`,
`HF_HUB_OFFLINE=1`, and the venv's `PATH`. stdout is the formatted transcript
(`src/stenographer/cli/commands/transcribe.py:107-108`); stderr carries the
`pipeline: utterance ... utt=0 source=file` line whose fields come from
`summary_fields` (`src/stenographer/transcribe/pipeline.py:77-112`) rendered
by `fmt_event` (`src/stenographer/utils/logging_setup.py:81-88`). The pure
`parse_summary_line(text) -> dict[str, str] | None` finds the *last* line
containing `pipeline: utterance ` and splits `key=value` tokens, honouring
double-quoted values with `\"` and `\\` escapes (`logging_setup.py:380-404`);
every key is optional because `None` fields are dropped. Exit codes: `0` ok;
`2` file problem; `78` model not cached or `ConfigError`
(`transcribe.py:44-50`, `cli/_fatal`). A non-zero exit is recorded on the clip
(`exit_code`, `error`) and the run continues; `78` on the first clip aborts
the run as a harness error, because every later clip would fail the same way.

Each invocation loads the model cold (`transcribe.py:74-77`, `record.cold =
True`), so the subprocess engine's `load_ms` is a genuine cold number and its
per-clip wall time includes interpreter start-up. `XDG_STATE_HOME` keeps the
CLI's `stenographer.log` (`with_config` → `apply_stderr_level`, and the file
sink installed by `cli.main`) inside the run directory instead of the user's
real state directory.

**In-process engine** — the fast one, and the only one that can vary
`DecodeOptions`. The runner imports `stenographer.transcribe.model`,
`stenographer.transcribe.pipeline` (`downmix`, `transcript_text`),
`stenographer.audio` (`speech_gate_stats`, `_resample_poly`) and
`stenographer.config`, builds `Config.load(config.toml)` for the config lane,
constructs `Model(cfg.asr, options=DecodeOptions(**decode))` **once per
variant**, and for each clip repeats exactly what `cmd_transcribe` does
(`cli/commands/transcribe.py:54-91`): read with `soundfile`, `downmix`, `_resample_poly`,
`speech_gate_stats`, `m.transcribe(samples)`, `transcript_text(result,
raw=False)`, measuring `decode_ms` around `m.transcribe` alone. The first clip
of the variant records `cold = true` and the `Model.__init__` wall time as
`load_ms`; every later clip records `cold = false, load_ms = null`. The runner
never calls `setup_logging`, so nothing is written to any `stenographer.log`;
the `stenographer` logger has no handlers and its records are discarded.

Both engines fill the same per-clip record (§4.1). Cross-engine comparisons
are valid for text metrics and `decode_ms`; `load_ms` and `total_ms` are only
comparable within one engine, and `result.json` records the engine so
`compare` can refuse a mixed speed comparison.

**An experiment whose target is `load_ms_*` or `first_response_ms_*` must use
`subprocess`** so every clip's `load_ms` is a cold load and the p50/p95 mean what
the user feels on the first utterance. One whose target is `decode_ms_*` or
`rtf_*` **and** which needs a `DecodeOptions` field runs `inprocess`, with both
sides of the comparison on the same engine (§6.4 enforces it). Otherwise `auto` is
right. The S-series and the Q-series are not divided by engine; the target metric
and the injection seam decide.

### 3.2 `DecodeOptions` (*provisional*)

A frozen dataclass added to `src/stenographer/transcribe/model.py`, whose
defaults are byte-for-byte today's literals. It is the injection seam for the
harness and is **not** reachable from user config: `AGENTS.md` hard rule 5
calls the anti-hallucination stack "fixed behavior, not configuration", and a
constructor-only override with fixed defaults keeps that true. The
implementation commit must add one sentence to `AGENTS.md` (hard rule 5 or
the `transcribe/` row) naming `DecodeOptions` as the dev-only seam that only
`scripts/` may construct with non-default values.

```python
@dataclass(frozen=True)
class DecodeOptions:
    # transcribe() call literals, model.py:110-125
    temperature: tuple[float, ...] = (0.0,)
    no_repeat_ngram_size: int = 3
    repetition_penalty: float = 1.0            # library default
    # library default; inert while len(temperature) == 1
    compression_ratio_threshold: float | None = 2.4
    log_prob_threshold: float | None = -1.0    # library default
    condition_on_previous_text: bool = False
    hallucination_silence_seconds: float | None = 2.0  # _HALLUCINATION_SILENCE_SECONDS, model.py:27
    word_timestamps: bool = True
    # token budget, model.py:26,28,29,173-175,200
    max_new_tokens: int = 128
    words_per_vad_second: int = 8
    min_word_limit: int = 12
    # _VAD_PARAMETERS, model.py:32-37
    vad_threshold: float = 0.5
    vad_min_speech_duration_ms: int = 100
    vad_min_silence_duration_ms: int = 500
    vad_speech_pad_ms: int = 250
    # _assemble, model.py:215
    assemble_no_speech_gate: bool = True
    # WhisperModel(...), model.py:82-88
    device: str = "auto"
    # post-decode tail filter (Q11 §3.2); both rules off by default
    tail_filter_min_prob: float | None = None   # None → probability rule off
    tail_filter_max_words: int = 6              # cap on words the rule may drop
    tail_filter_min_words: int = 2              # shorter tails are never dropped
    tail_filter_blocklist: bool = False         # whole-final-segment rule off
    # BatchedInferencePipeline (S02 §3.2); faster_whisper/transcribe.py:111
    batched: bool = False
    batch_size: int = 8               # inert while batched is False
    without_timestamps: bool = False  # library default on the sequential path
```

Every field above defaults to today's shipped behaviour, so adding one changes
nothing until a variant sets it. The last two blocks are **off by default** and
exist only so Q11 and S02 have a seam; `validate_variant` rules for them:
`tail_filter_min_prob` is `null` or in `(0.0, 1.0)`; `tail_filter_max_words` and
`tail_filter_min_words` are integers ≥ 1 with `max_words >= min_words`;
`batch_size` is an integer ≥ 1 and is rejected together with a variant
`config.asr.vad_filter = false`, which the batched path refuses on audio ≥ 30 s.

JSON has no tuples, so `validate_variant` and `DecodeOptions(**decode)` **coerce
JSON arrays to tuples** for the sequence-valued fields (today only `temperature`);
a variant writes `"temperature": [0.0, 0.2]` and the dataclass stays hashable.

`best_of`, `patience` and `length_penalty` are deliberately **absent**: the shipped
call passes none of them, so exposing them would widen the seam past what any plan
needs. Adding one is an amendment to this section.

`assemble_no_speech_gate` is the one field with a scheduled death: if Q06 is
accepted, the gate it switches is deleted from `_assemble` and the field is removed
from this dataclass and from its pinning test in the same commit.

Threading: `Model.__init__(self, cfg: AsrConfig, options: DecodeOptions =
DecodeOptions())`; `transcribe()` reads every literal from `self._options`;
`_token_budget` and `_validate_output` take the three budget values as
arguments; `_assemble` takes `gate: bool` and, when `False`, keeps every
segment (the `_validate_output` call still runs). `temperature=(0.0,)` is
equivalent to today's scalar because faster-whisper wraps a scalar into a
one-element list (`faster_whisper/transcribe.py:982-986`); the implementer
must confirm at that line and keep `tuple` in the dataclass so it stays
hashable. `hallucination_silence_seconds` requires `word_timestamps=True`
(faster-whisper uses word starts to detect anomalies,
`faster_whisper/transcribe.py:1294-1320`); `validate_variant` rejects the
combination `word_timestamps=false` with a non-null threshold. The worker
child (`transcribe/worker.py`) and `cmd_transcribe` keep calling
`Model(cfg.asr)`, so the shipped stack is unchanged.

Pinning test: `tests/transcribe/test_model.py` gains one test asserting
`dataclasses.asdict(DecodeOptions())` equals a literal dict copied into the
test. Changing a default after an accepted experiment means editing both,
which is the point.

Rejected alternative — monkeypatching `model._VAD_PARAMETERS` and friends from
the harness: it cannot reach call-site literals (`temperature`,
`no_repeat_ngram_size`, the library defaults), couples the harness to private
names, and leaves no record of what ran in `result.json`.

---

## 4. Records

### 4.1 Per-clip record (`clips.jsonl`, one JSON object per line)

```json
{
  "clip_id": "1089-134686-0001+tail3s", "lane": "tail", "tags": ["short", "tail=3s"],
  "repeat": 0, "engine": "subprocess", "exit_code": 0, "error": null,
  "audio_s": 7.215,
  "hypothesis_raw": "<formatted stdout, verbatim>",
  "hypothesis_norm": "<normalized tokens joined by one space>",
  "reference_norm": "<normalized tokens joined by one space>",
  "ref_words": 8, "hyp_words": 10,
  "substitutions": 0, "deletions": 0, "insertions": 2, "errors": 2, "wer": 0.25,
  "leading_word_recall": 1.0,
  "trailing_junk": true, "trailing_junk_words": 2,
  "empty": false,
  "gate": "pass", "peak_rms": 0.081, "vad_frames": 68800, "segments": 1, "words": 10,
  "chars_out": 55,
  "cold": true, "load_ms": 2140.3, "decode_ms": 612.7, "total_ms": 2801.9,
  "rtf": 0.0849
}
```

`gate`, `peak_rms`, `vad_frames`, `segments`, `words`, `chars_out`, `load_ms`,
`decode_ms`, `total_ms` come from the summary line (subprocess) or from the
same measurements taken in-process. A clip with `exit_code != 0` or `error`
set has every text and metric field `null` — **`empty` included** — and counts
in `errors` but in no WER aggregate. `empty` is `true` only for a clip that
decoded successfully and produced no words, so §6.2's rule 4 (empty regressions)
and rule 5 (new errors) can never charge the same clip twice; the `empty`
aggregate's denominator is the clips with a hypothesis. `error` is an exception
class name or the CLI's exit code meaning, never a message.

**Optional, in-process-only per-clip keys.** Several plans add numeric fields to
this record. The subprocess engine cannot see any of them and writes `null`;
`decide` treats a metric missing on a side it must compare as exit 2, never as a
pass (§6.2). Adding one is a documentation change here, not a schema change.

| key | type | plan |
|---|---|---|
| `assemble_segments_total` | int | Q06 — `len(result.segments)` |
| `assemble_gated_segments` | int | Q06 — segments at or above `asr.silence_threshold` |
| `segment_no_speech_max` | float \| null | Q06 — max over the segments, `null` when empty |
| `segment_no_speech_min` | float \| null | Q06 — min over the segments, `null` when empty |
| `prompt_leak` | bool | Q08 §6.1 |
| `prompt_leak_ngrams` | int | Q08 §6.1 — count only; the n-grams stay in `clips.jsonl` |
| `punct_terminal_runs` | int | Q08 §6.2 |
| `punct_commas` | int | Q08 §6.2 |
| `punct_words` | int | Q08 §6.2 |
| `tail_word_recall` | float | Q11 §3.3 |
| `tail_dropped_words` | int | Q11 — words the tail filter removed |
| `tail_dropped_segments` | int | Q11 — final segments the blocklist rule removed |
| `max_deletion_run` | int | S02 §3.4 |

All thirteen are numbers or booleans, so they are also carried into `clip_scores`
(§4.3) and the no-text rule in §1 is untouched.

**The three text fields exist only in `clips.jsonl` under `build/`.** No other
file the harness writes, and nothing it prints, contains them.

### 4.2 Aggregates

Computed by the pure `aggregate(records) -> dict`, once over the whole run and
once per lane (`per_lane`). Percentiles use nearest rank on ascending values:
`p = sorted[ceil(q * n) - 1]`, so `p50` of `[1, 2, 3, 4]` is `2` and `p95` of
100 values is the 95th smallest. Speed fields are computed over clips with
`exit_code == 0`; text fields over clips with a hypothesis (`error == null`).

```json
{
  "clips": 100, "errors": 0, "empty": 2,
  "wer_mean": 0.061, "wer_median": 0.040,
  "wer_corpus": 0.058,
  "substitution_rate": 0.031, "deletion_rate": 0.015, "insertion_rate": 0.012,
  "leading_word_recall_mean": 0.973, "leading_miss_rate": 0.05,
  "trailing_junk_rate": 0.03,
  "decode_ms_p50": 540.0, "decode_ms_p95": 1310.0,
  "load_ms_p50": 2050.0, "load_ms_p95": 2790.0,
  "first_response_ms_p50": 2600.0, "first_response_ms_p95": 4020.0,
  "rtf_p50": 0.081, "rtf_p95": 0.140
}
```

- `wer_corpus` = Σ errors / Σ ref_words (the conventional corpus WER);
  `wer_mean` is the mean of per-clip `wer` (weights short clips more, which
  matches dictation). The accept rule uses `wer_mean`.
- `*_rate` for S/D/I = Σ count / Σ ref_words.
- `leading_miss_rate` = fraction of clips with `leading_word_recall < 1.0`.
- `trailing_junk_rate` = fraction of clips with `trailing_junk == true`.
- `load_ms_*` and `first_response_ms_*` (= `load_ms + decode_ms`) are computed
  over `cold == true` clips only and are `null` when there are fewer than 10
  of them, so an in-process run never reports a one-sample cold number.

**Optional aggregates**, present only when the corresponding per-clip keys are
(so, in-process runs only). Each is computed run-wide and per lane:

| key | definition | plan |
|---|---|---|
| `assemble_gate_fire_rate` | fraction of scored clips with `assemble_gated_segments >= 1` | Q06 |
| `assemble_gated_segment_total` | Σ `assemble_gated_segments` | Q06 |
| `prompt_leak_rate` | fraction of clips with a hypothesis whose `prompt_leak` is true | Q08 |
| `terminal_runs_per_100w` | `100 × Σ punct_terminal_runs / Σ punct_words`; `null` when the denominator is 0 | Q08 |
| `commas_per_100w` | `100 × Σ punct_commas / Σ punct_words`; `null` when the denominator is 0 | Q08 |
| `tail_word_recall_mean` | mean of the per-clip `tail_word_recall` | Q11 |
| `tail_drop_rate` | fraction of scored clips with `tail_dropped_words + tail_dropped_segments > 0` | Q11 |
| `tail_dropped_words_mean` | mean of the per-clip `tail_dropped_words` | Q11 |
| `max_deletion_run_p95` | nearest-rank p95 of the per-clip `max_deletion_run` | S02 |
| `large_deletion_run_rate` | fraction of scored clips with `max_deletion_run >= 25` | S02 |
| `segments_p50` | nearest-rank p50 of the per-clip `segments` | S02 |
| `error_kinds` | `{exception class name: count}` over clips with `error` set | S02 |

`error_kinds` is the one non-scalar aggregate; `decide` may not target it, and it
is rendered in `report.md` as one row per key. Its values are class names, never
messages (§4.1), so the no-text rule holds.

### 4.3 `result.json`

```json
{
  "schema": 1,
  "run_id": "20260829T141500Z-q03-beam-1",
  "created_utc": "2026-08-29T14:15:00Z",
  "plan": "Q03",
  "variant": { "...the validated variant, all fields present..." },
  "engine": "subprocess",
  "environment": {
    "stenographer_version": "0.11.6", "git_commit": "a1b9807", "git_dirty": false,
    "python": "3.14.0", "faster_whisper": "1.2.1", "ctranslate2": "4.8.1",
    "cuda_device_count": 1, "device": "cuda",
    "compute_type_requested": "int8", "compute_type_resolved": "int8_float16",
    "cpu_threads": 8, "model": "Systran/faster-whisper-medium.en"
  },
  "corpus": {"manifest_sha256": "…", "lane_sha256": {"base": "…"},
             "lanes": ["base"], "clip_count": 100, "repeats": 1},
  "aggregates": { "…§4.2…", "per_lane": {"base": { "…" }} },
  "clip_scores": [
    {"clip_id": "1089-134686-0001", "lane": "base", "repeat": 0, "wer": 0.0,
     "substitutions": 0, "deletions": 0, "insertions": 0, "leading_word_recall": 1.0,
     "trailing_junk": false, "empty": false, "decode_ms": 512.0, "rtf": 0.121}
  ]
}
```

`clip_scores` is the numeric projection of `clips.jsonl` (no text fields)
so that `compare` can detect per-clip regressions from a checked-in baseline.
`corpus.lane_sha256` carries one digest per lane the run touched (§2.5);
`manifest_sha256` is still recorded, but `compare` enforces only the digests of
the lanes it is actually comparing (§6.4).
`compute_type_resolved` is read from the loaded CTranslate2 model
(`WhisperModel.model.compute_type`; the `ctranslate2.models.Whisper` class
exposes `compute_type` and `device`) during preflight (§8.2), which is also
why `"int8"` on this GPU is recorded as `int8_float16` rather than treated as
a distinct variant.

`docs/experiments/baseline.json` is exactly a `result.json` (§7). The test in
§1 enforces that no `clip_scores` row and no other field carries the keys
`hypothesis_raw`, `hypothesis_norm`, or `reference_norm`.

---

## 5. Metrics — pure functions in `scripts/asr_metrics.py`

Each definition is followed by a worked example. The implementer writes the
example as a test, watches it fail against a stub, then implements.

### 5.1 `normalize(text: str) -> list[str]`

1. `unicodedata.normalize("NFKC", text)`, then `casefold()`.
2. Map `’ ‘ ‛ ′` to `'`; map `- – — ‐` to a space (hyphenated compounds split:
   LibriSpeech writes them as separate words).
3. Delete every character not in `[a-z0-9' ]`; collapse whitespace; split.
4. Strip `'` from token edges; drop tokens that become empty.
5. Abbreviation table applied per token: `mr → mister`, `mrs → missus`,
   `dr → doctor`. Fixed and deliberately tiny; extending it is a normalization
   change that requires a re-baseline (§7.3).
6. Spoken-number folding, both sides: maximal runs of number words are
   replaced by their digit string using the deleted `bench.py`'s grammar
   (`_UNITS`, `_TENS`, `_SCALES`, `point`, the year and digit-sequence
   heuristics in `_chunks_to_str`; `git show 6149d83^:src/stenographer/bench.py`).
   Copy it, do not import it. Digit tokens in the hypothesis are left as
   digits, so `nineteen eighty four` and `1984` meet in the middle.

Example: `"Mr. Holmes said—“Don’t!”  1984"` → `["mister", "holmes", "said",
"don't", "1984"]`; `"NINETEEN EIGHTY FOUR"` → `["1984"]`.

Normalization errors bias every variant equally, so within-programme deltas
are sound; absolute numbers are not comparable to published LibriSpeech WERs.

### 5.2 `align(ref: list[str], hyp: list[str]) -> list[tuple[str, int | None, int | None]]`

Word-level Levenshtein with unit costs, full DP table, backtrace from
`(len(ref), len(hyp))`. Tie-breaking at each backtrace step, in this order:
diagonal (`match` if the words are equal, else `sub`), then up (`del`, a
reference word with no hypothesis word), then left (`ins`). Returns ops in
reading order as `(op, ref_index, hyp_index)` with `None` for the absent side.

### 5.3 `wer(ref, hyp) -> EditCounts`

`EditCounts(substitutions, deletions, insertions, ref_len, hyp_len)` with
properties `errors = S + D + I` and `wer = errors / max(ref_len, 1)`. An empty
reference with a non-empty hypothesis gives `insertions = hyp_len` and `wer =
hyp_len`; both empty gives `0.0`.

Example: ref `the cat sat on the mat`, hyp `cat sat on the mat mat` → ops
`del(the) match×5 ins(mat)` → `S=0 D=1 I=1`, `errors=2`, `wer=2/6=0.3333`.

### 5.4 `leading_word_recall(ref, hyp, k=3) -> float`

Over the first `min(k, len(ref))` reference words, the fraction whose op in
`align` is `match`. `1.0` when the reference is empty.

Example: ref `please open the door`, hyp `open the door` → `please` is `del`,
`open` and `the` match → `2/3 = 0.6667`. Ref `please open the door`, hyp
`lease open the door` → `sub`, match, match → `0.6667` as well: a mangled
first word counts as missed, because that is what the user sees.

### 5.5 `trailing_junk(ref, hyp) -> tuple[bool, int]`

Returns `(flag, tail_words)`. `flag` is true if either condition holds:

(a) **Tail insertions.** Let `last` be the largest `hyp_index` among ops that
are `match` or `sub`. `tail = hyp[last + 1:]` (`tail = hyp` when no such op
exists). Condition: `len(tail) >= 2`. `tail_words = len(tail)`.

(b) **Terminal repetition.** For `n in (1, 2, 3)`: if `len(hyp) >= 3n` and
`hyp[-n:] == hyp[-2n:-n] == hyp[-3n:-2n]`, and the reference does *not* end
with that same n-gram repeated three times, the condition holds and
`tail_words = max(tail_words, 3n)`.

Examples (ref `see you tomorrow` in all):
- hyp `see you tomorrow thank you` → tail `[thank, you]` → `(True, 2)`.
- hyp `see you tomorrow thanks` → tail 1 → `(False, 1)`.
- hyp `see you tomorrow and more and more and more` → (a) tail 6, (b) `n=2`
  → `(True, 6)`.
- hyp `see you tomorrow tomorrow` → the second `tomorrow` is `ins`, tail 1 →
  `(False, 1)`.
- hyp `see you` → no tail → `(False, 0)`.
- ref `no no no`, hyp `no no no` → (b) suppressed by the reference guard →
  `(False, 0)`.

### 5.6 Rates and `rtf`

- Per clip: `rtf = (decode_ms / 1000) / audio_s`; `audio_s` from the
  manifest. Decode only — load is reported separately as `load_ms`.
- Corpus: `insertion_rate = Σ insertions / Σ ref_words` (likewise S and D).
- `empty = hyp_words == 0`, and only for a clip that decoded (§4.1).

Example: `decode_ms = 1100`, `audio_s = 25.0` → `rtf = 0.044`.

### 5.7 Paired comparison (`pair_by_base`, `paired_delta`)

A lane-validation plan compares an augmented clip against *its own* un-augmented
source, not against a corpus mean, so the between-clip variance cancels. Both
functions are pure and stdlib-only.

```python
def pair_by_base(control: list[dict], condition: list[dict], key: str
                 ) -> list[tuple[str, float, float]]:
    """Pair clip_scores rows by base id (clip_id up to the first '+').
    Rows with repeat != 0, a null *key*, or no partner are dropped.
    Returns (base_id, control_value, condition_value), base_id ascending."""

@dataclass(frozen=True)
class PairedResult:
    n: int; worse: int; better: int; tied: int
    mean_control: float; mean_condition: float; mean_delta: float
    p_value: float

def paired_delta(pairs: list[tuple[str, float, float]]) -> PairedResult:
    """mean_delta = mean(control - condition); p_value is the exact two-sided
    binomial sign test over the discordant pairs (1.0 when there are none)."""
```

Worked examples (each a seen-to-fail test):

- `pair_by_base` with control ids `a, b` and condition ids `a+cue0ms, c+cue0ms` →
  one pair, `("a", …)`; the unmatched `b` and `c` are dropped.
- `paired_delta` on ten pairs, condition `2/3` and control `1.0` on each →
  `n=10, worse=10, better=0, mean_delta=0.3333, p_value = 2**-9 ≈ 0.001953`.
- `paired_delta` on pairs that are all equal → `worse = better = 0`,
  `mean_delta = 0.0`, `p_value = 1.0`.
- `paired_delta` on `worse=6, better=4, tied=90` → `p_value = 0.7539` (the exact
  two-sided test at m=10, w=6; assert that literal).

`compare-paired` (§1) is the thin I/O shell over these: load the JSON, run the
refusals, call the two functions, render, exit. Its only testable pure helper is
the refusal predicate. Q10 §6.4 is the plan that motivates them.

### 5.8 Plan-contributed scorers

These land with the plan that needs them and stay afterwards. Each keeps its
worked examples in the plan as well as here; this section is the canonical
signature, the plan is the canonical rationale.

**`tail_word_recall(ref, hyp, k=3) -> float`** (Q11 §3.3) — the mirror of §5.4:
over the **last** `min(k, len(ref))` reference words, the fraction whose op in
`align` is `match`; `1.0` when the reference is empty. Aggregate key
`tail_word_recall_mean`. Examples: ref `see you tomorrow` against hyp
`see you tomorrow` → `1.0`; against `see you` → `0.6667`; against
`see you tomorrer` → `0.6667` (a substitution is not a match); against
`see you tomorrow thank you` → `1.0`, because a tail *insertion* does not reduce
recall — that is what §5.5 is for.

**`deletion_runs(ops) -> list[int]`** and **`max_deletion_run(ops) -> int`**
(S02 §3.4) — lengths of maximal consecutive runs of `del` ops from `align`, in
reading order, and their maximum (`0` when there are none). Examples: ref
`a b c d e` / hyp `a e` → `[3]`, `3`; ref `a b c` / hyp `a b c` → `[]`, `0`; ref
`a b c d` / hyp `a c` → `[1, 1]`, `1`. `LARGE_DELETION_RUN = 25` is the constant
behind `large_deletion_run_rate` (§4.2): alignment noise is 1–3 words and a lost
30 s window is ≈75, so 25 separates them.

**`ngrams`, `corpus_ngrams`, `effective_prompt_ngrams`, `prompt_leak`**
(Q08 §6.1) — all over `normalize` output, `n = 3`:

```python
def ngrams(tokens: list[str], n: int = 3) -> set[tuple[str, ...]]: ...
def corpus_ngrams(references_norm: list[list[str]], n: int = 3) -> set[tuple[str, ...]]: ...
def effective_prompt_ngrams(prompt_norm, corpus, n: int = 3) -> set[tuple[str, ...]]:
    return ngrams(prompt_norm, n) - corpus
def prompt_leak(effective, ref_norm, hyp_norm, n: int = 3) -> tuple[bool, int]:
    leaked = (effective & ngrams(hyp_norm, n)) - ngrams(ref_norm, n)
    return bool(leaked), len(leaked)
```

`corpus` and `effective` are computed once per run over the references the run
will score; `prompt_leak` runs once per clip. Example: prompt
`please add commas and periods` against corpus references `he opened the door`
and `and periods of rain`, for a clip whose hypothesis appends
`please add commas` → `(True, 1)`. Same prompt, a clip whose reference *is* the
prompt phrase → `(False, 0)`, because the reference's own n-grams are subtracted.
An empty prompt gives `(False, 0)` for every clip, which is why a control's leak
number is evidence of nothing. Subtracting the corpus pool makes the metric
conservative; §8.2 step 8 is the bound on how conservative it may get.

**`punctuation_stats(raw: str) -> PunctuationStats`** (Q08 §6.2) — density only,
computed on `hypothesis_raw`, never gated. `PunctuationStats(words, terminal_runs,
commas)`: `words = len(normalize(raw))`, `terminal_runs` counts *maximal* runs of
characters drawn from `.?!` (so `...` and `?!` count once each), `commas` counts
`,`. Example: `Mr. Holmes said, "Don't!" Really... yes` →
`PunctuationStats(words=6, terminal_runs=3, commas=1)`. LibriSpeech references
carry no punctuation, so there is no ground truth to score against and no
threshold may ever be put on these; they answer only "did the prompt's
punctuation mechanism engage at all?".

---

## 6. Accept / deny contract

### 6.1 `thresholds.json`

Every plan ships one under `docs/experiments/variants/<plan>/thresholds.json`:

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
  "guards": [
    {"metric": "leading_word_recall_mean", "direction": "higher",
     "margin_kind": "absolute", "max_regression": 0.01},
    {"metric": "tail_word_recall_mean", "direction": "higher", "lane": "tail",
     "margin_kind": "absolute", "max_absolute": 0.95}
  ],
  "allow_model_change": false,
  "lanes": ["base", "tail"],
  "min_clips": 100
}
```

- `metric`: any aggregate key from §4.2. `direction`: `lower` or `higher`.
- `margin_kind`: `absolute` (run must beat baseline by `margin`) or `relative`
  (by `margin × |baseline value|`).
- `lanes`: the lanes the verdict is computed over; must equal the variant's, or
  the `run --lanes` override when one is given.
- `min_clips`: fewer scored **distinct clip ids** than this is a harness error
  (§3, `repeats`).
- `allow_model_change`: boolean, default `false`. Honoured only when the
  variant's `plan` is `"Q12"`; `validate_variant` rejects `true` on any other
  plan, so no plan can quietly compare across models.

**`target` may be `null`.** A plan whose whole claim is "nothing gets worse" —
Q06's no-harm arm, Q11's control-corpus run — writes `"target": null` and rule 2
is skipped. Such a run is decided by its guards alone, and `report.md` says so
instead of naming a target that does not exist.

**`guards`** is an optional array; every entry is

```json
{"metric": "<aggregate key>", "direction": "lower"|"higher",
 "lane": "<optional per_lane key>", "margin_kind": "absolute"|"relative",
 "max_regression": <float ≥ 0> | "max_absolute": <float> | "min_improvement": <float>}
```

with **exactly one** of the three bounds. `lane` is optional; when it is absent
the guard reads the run-wide aggregate, when it is present it reads
`aggregates.per_lane[lane]`. The three bounds are:

- **`max_regression`** — the run must be no worse than the baseline by more than
  this in the stated direction (`absolute`: baseline ± the value; `relative`:
  baseline × (1 ± the value)). This is the non-inferiority form and the common one.
- **`max_absolute`** — the **run value alone** must satisfy the bound; the baseline
  is not consulted at all. This is what lets a metric that does not exist in the
  checked-in baseline still gate a run — a new scorer's first use, a control-corpus
  run with no comparable history.
- **`min_improvement`** — the run must beat the baseline by at least this much. It
  is `target` without the ceremony, for a plan with more than one thing to prove.

A metric missing on a side the guard must read, or a `null` run value, is **exit 2
with a named reason** — never a pass and never a deny. `validate_variant` requires
each `max_regression` to be **≥ the recorded noise** for that metric (§7.1); a bound
below the noise floor would fire on run-to-run jitter, and is a harness error.

Rules 1 (WER) and 3 (RTF) are themselves built-in guards, expressed in exactly
this vocabulary; `wer_mean_max_delta` and `rtf_p95_max_ratio` stay as sugar for the
two guards every plan wants. **Every guard row — built-in and declared — appears in the verdict line
and in `report.md`**, with both values and its pass/fail, whatever the outcome.

A plan may also ship a small check script of its own, but the array above is the
canonical mechanism: a script is the fallback for a plan that has to run before the
foundation commit lands `guards`.

### 6.2 The rule (pure `decide(baseline, run, thresholds) -> Verdict`)

Aggregates for both sides are recomputed over the intersection of clip ids
present in both `clip_scores` sets and in the thresholds' lanes, so a
partial run never compares against a fuller baseline. Then **accept iff all
of**:

1. `run.wer_mean <= baseline.wer_mean + wer_mean_max_delta` (the built-in WER
   guard);
2. the target metric improves by at least its margin in its direction —
   **skipped when `target` is `null`**;
3. `run.rtf_p95 <= rtf_p95_max_ratio × baseline.rtf_p95`;
4. no clip that was non-empty in the baseline is empty in the run (when
   `forbid_empty_regressions`);
5. no clip errored in the run that succeeded in the baseline;
6. every entry of `guards` passes.

The intersection is over `clip_id`, with all of an id's repeats taken from both
sides (§3, `repeats`). Rules 4 and 5 are disjoint by construction, because an
errored clip's `empty` is `null` (§4.1).

`Verdict` carries `accepted: bool`, the evaluated guards with both values,
the target delta (or `null`), and `empty_regressions: list[str]` of clip ids.

### 6.3 Exit codes and output

- `0` accept, `1` deny, `2` harness error (preflight failure, manifest
  mismatch, invalid variant, `min_clips` unmet, engine mismatch for a speed
  comparison, an exception in the runner).

stdout, in this order: one verdict line —

```
ACCEPT q03-beam-1: trailing_junk_rate 0.030 -> 0.000 (margin 0.030 absolute); wer_mean 0.061 -> 0.062 (+0.001 <= +0.002); rtf_p95 0.140 -> 0.098 (x0.70 <= x1.25); guard leading_word_recall_mean 0.973 -> 0.971 (-0.002 <= 0.010) PASS; empty regressions 0
```

— with `target null` in place of the target clause when there is no target, and
one clause per declared guard whatever the outcome — then a Markdown table with
one row per aggregate key in §4.2 (baseline, run, delta, guard status), then one
row per lane for the target metric, then the list of empty-regression clip ids if
any. A denied run prints the **same
full table**; it is written to `report.md` and `verdict.json` regardless of
outcome. Text never appears in any of it.

### 6.4 Refusals (exit 2, not deny)

`compare` refuses when any **compared lane's** `corpus.lane_sha256` digest differs
(a lane neither side is scored on may differ freely; `manifest_sha256` is recorded
for the record, not enforced), when `environment.device` differs, when
`environment.model` differs unless the plan is Q12 and the thresholds file carries
`"allow_model_change": true`, or when the run is a speed comparison
(`target.metric`, or any **declared** guard's metric, starts with `load_ms`,
`first_response_ms`, `decode_ms`, or `rtf`) and the engines differ. The built-in
WER and RTF guards never trigger this refusal: `rtf_p95_max_ratio` is on every
thresholds file, so counting it here would refuse every in-process run against
the subprocess baseline — which §3.1 explicitly permits, `decode_ms` and `rtf`
being cross-engine comparable. Only a guard a plan *wrote* declares that speed is
what the run is about.

`compare` does **not** check `environment.git_commit`: a run against a dirty or
moved tree is recorded, not refused, and refusing on the commit alone would block
every legitimate rerun after an unrelated edit. The plan-level question — "does the
baseline still describe the shipped defaults?" — is a **content** check, not a HEAD
equality check: `git diff --quiet <baseline_commit> HEAD -- src/ pyproject.toml`,
which passes whenever the shipped stack is unchanged however far HEAD has moved.

---

## 7. Baseline

### 7.1 Establishing it

After the corpus exists and the harness passes its unit tests:

```sh
.venv/bin/python scripts/asr_corpus.py fetch --prune-source
.venv/bin/python scripts/asr_corpus.py build \
  --lanes base,tail,cue,quiet,silence,onset,longform
.venv/bin/python scripts/asr_experiment.py preflight
.venv/bin/python scripts/asr_experiment.py baseline \
  --lanes base,tail,cue,quiet,silence,onset,longform \
  --engine subprocess --repeats 3 \
  --out docs/experiments/baseline.json
```

Every lane generator §2.4 names lands in the foundation commit, so the baseline
covers all seven at once. Q09's `tail-n50` / `tail-n40` / `tail-room` probe lanes
and Q11's `control` manifest are deliberately **not** in it: they are self-
controlled and never compared against `docs/experiments/baseline.json`.

`baseline` runs the variant `{"name": "baseline", "config": {}, "decode": {}}`
— the shipped defaults, today's literals — over the named lanes with the
subprocess engine (so `load_ms` is cold on every clip), three times, and
writes the result of repeat 0 as the baseline plus a `noise` block. The `noise`
block records the max absolute spread across the three repeats of **every**
aggregate key of §4.2 the run produced, run-wide and per lane — not a hand-picked
five. A plan's declared `target` margin must be at least twice the recorded noise
for its metric, and every `max_regression` at least the recorded noise (§6.1);
`validate_variant` enforces both when a baseline is present, and treats a target
metric **absent from `noise`** as exit 2 with a named reason rather than silently
skipping the check.

Time: ≈1180 clips × 3 repeats at ≈5 s each ≈ 5 h wall, plus ≈30 min because the 60
`longform` clips are minutes of audio each rather than seconds. Run it once,
overnight, and do not shortcut it: every later verdict rests on it.

### 7.2 What it contains

Exactly `result.json` (§4.3) plus `noise`. Numbers only. The §1 test guards
the text rule on every CI run.

### 7.3 Re-baselining

Re-run `baseline` only when one of these is true, and say which in the commit
message:

1. an accepted experiment's change has been merged to `dev` (the shipped
   defaults moved, so the old baseline no longer describes them);
2. the compared lanes changed — a lane's rows were regenerated, or the subset
   moved, so that lane's `lane_sha256` no longer matches. Adding a *new* lane
   moves `manifest_sha256` alone and needs no re-baseline until a comparison is
   actually scored on it;
3. `normalize` or any metric definition changed;
4. faster-whisper, CTranslate2, the CUDA stack, or the GPU changed.

Never re-baseline to make a denied run pass. A re-baseline commit touches
`docs/experiments/baseline.json` and nothing under `src/`.

---

## 8. Execution environment

### 8.1 Local machine only

The harness cannot run in CI: it needs the 1.5 GB cached model that
`AGENTS.md` forbids downloading anywhere but `stenographer model download`, a
346 MB corpus download, a CUDA GPU for numbers that mean anything, and tens
of minutes of wall time per variant. Only the pure tests
(`tests/test_asr_metrics.py`, `tests/test_asr_experiment.py`,
`tests/test_asr_corpus.py`, `tests/test_asr_baseline_file.py`) run in CI, on
both `ubuntu-latest` and `windows-latest`; they must not touch `build/`.
The reference machine is the RTX 3080 Laptop (8 GiB) on which the figures in
this document were measured.

### 8.2 Preflight (runs before every `baseline` / `run`; also `preflight` alone)

1. Venv: `sys.executable` is under `.venv/`; `stenographer` imports and its
   `__version__` is recorded.
2. Model: `stenographer.transcribe.model.is_model_cached(cfg.asr.model)` for
   the variant's effective model (`model.py:230-239`); false → exit 2 with the
   `stenographer model download` hint. The harness never downloads a model.
   `preflight --variant PATH` is what names the model to probe — without it the
   shipped default is probed, which is the wrong answer for Q12.
3. Corpus: manifest present, `schema == 1`, every clip in the requested lanes
   exists and its SHA-256 matches.
4. GPU: `ctranslate2.get_cuda_device_count()` is recorded; `0` → exit 2 unless
   `--allow-cpu`, which records `device: "cpu"` (never comparable to a CUDA
   baseline, §6.4).
5. Resolved compute type: construct `Model(cfg.asr)` once in-process, read
   `WhisperModel.model.compute_type` and `.device`, record both, close it.
   This costs one cold load and doubles as the "model actually loads" check.
6. Git: `git rev-parse --short HEAD` and `git status --porcelain` → `git_dirty`.
   A dirty tree is recorded, not refused; a baseline written from a dirty
   tree is refused.
7. Disk: at least 2 GiB free under `build/`.
8. Prompt (Q08): when the variant sets a non-empty `asr.initial_prompt`, compute
   `effective_prompt_ngrams` over the references the run will score (§5.8) and
   **exit 2** when `prompt_ngrams_effective / prompt_ngrams_total < 0.5`. A prompt
   more than half of whose 3-grams the corpus already utters cannot serve as a
   leak probe, and a leak bound measured through it would be meaningless.

### 8.3 Determinism

Greedy/beam decoding at temperature 0 on CTranslate2 is deterministic for a
fixed model, compute type and GPU in practice; the baseline's `noise` block is
the measured proof for this machine. For any variant whose `temperature`
tuple contains a value above zero, faster-whisper samples
(`faster_whisper/transcribe.py:1432-1440`): the in-process engine calls
`ctranslate2.set_random_seed(20260829 + repeat)` before each clip, the variant
must set `repeats: 3`, and `result.json` reports per-repeat aggregates plus
their spread; `decide` uses the mean over repeats and additionally denies when
the target metric's spread exceeds its margin. The subprocess engine cannot
seed the child, which is one more reason decode-lane variants are in-process.

### 8.4 Budget

Per clip on the reference machine: subprocess ≈ 1 s interpreter and imports +
0.7–2.8 s load + decode (≈1.1 s per 25 s of audio; ≈0.6 s for a 7 s clip) ≈
**4–5 s**; in-process ≈ **0.7 s** after the one load. So:

| Scope | Subprocess | In-process |
|---|---|---|
| `base` (100 clips, ≈12 min audio) | ≈8 min | ≈1.5 min + load |
| `base + tail` (400) | ≈32 min | ≈5 min |
| `base + tail + cue` (700) | ≈55 min | ≈9 min |
| `quiet` (200) | ≈17 min | ≈2.5 min |
| `silence` (20) | ≈2 min | ≈20 s |
| `onset` (200) | ≈17 min | ≈2.5 min |
| `longform` (60, ≈1.7 h audio) | ≈25 min | ≈15 min |
| all seven lanes (1180) | ≈1 h 55 min | ≈30 min |
| baseline (1180 × 3, subprocess) | ≈5.5 h | — |

Disk: tarball 346 MB + extracted FLAC ≈350 MB (deleted after conversion with
`asr_corpus.py fetch --prune-source`), base WAV ≈24 MB, tail ≈100 MB, cue
≈75 MB, quiet ≈48 MB, silence ≈3 MB, onset ≈50 MB, longform ≈200 MB; a run
directory is a few MB. Budget 2 GiB. Q09's three probe lanes add ≈300 MB while
that plan runs.

A plan's cost estimate (template §7) is `clips × repeats × per-clip time`
from this table, rounded up.

---

## 9. Invariant checklist

Every plan restates these in its §8, and the implementer's PR description
ticks them:

- **No transcript text** in `stenographer.log` (the in-process engine
  installs no logging; the subprocess engine's log is the shipped one, which
  already carries lengths only — `AGENTS.md` hard rule 6), in `result.json`,
  `report.md`, `verdict.json`, stdout, `docs/experiments/baseline.json`, or
  any file under `docs/experiments/variants/`. Text lives in `clips.jsonl`
  under `build/` only.
- **No network in the ASR path.** `Model` keeps `local_files_only=True`
  (`model.py:87`); the subprocess env sets `HF_HUB_OFFLINE=1`; only
  `asr_corpus.py fetch` opens a socket, and it is a `scripts/` dev tool, not a
  `stenographer` command. The implementation commit adds the corpus fetch to
  the `AGENTS.md` sentence that names the only permitted downloads.
- **No platform imports.** The harness imports core modules only
  (`stenographer.audio`, `stenographer.config`, `stenographer.transcribe.*`,
  `stenographer.delivery.feedback` for `bundled_sound_root`) and never
  `stenographer.platform.linux`, `evdev`, `fcntl`, or any name in
  `tests/platform/test_core_isolation.py`'s `BLOCKED` tuple. Add
  `scripts/asr_*.py` (the corpus, metrics and experiment modules),
  `scripts/asr_cold_start.py`, `scripts/q10_vad_probe.py` and
  `scripts/x01_record.py` to that test's grep so a violation fails on Linux.
- **Test policy** (`AGENTS.md` hard rule 4): pure functions with seen-to-fail
  tests; no mocking of `subprocess`, the model, or `soundfile`; the runner's
  I/O is exercised only by running it for real on the reference machine.
- **Fixed behaviour stays fixed.** `DecodeOptions()` defaults are pinned by a
  test; nothing under `src/` constructs a non-default instance; user config
  still has exactly 23 keys.
- **Venv only**, SPDX header on every new `.py`, ruff clean, line length 100.

---

## 10. Plan template

Every per-experiment document under `docs/experiments/` uses exactly these
ten numbered sections, in this order, with these headings. A section that
does not apply says "None." rather than being omitted.

A finished run appends **one unnumbered `## Outcome` heading after §10** — never
an eleventh numbered section, so the ten-section shape survives — and the file's
`Status:` line is updated to `accepted` / `denied` / `abandoned` in the **same
commit**. Numbers only, per §9.

```markdown
# Qnn — <title>

Status: planned | running | accepted | denied | abandoned (<date>)

## 1 Hypothesis
One falsifiable sentence: "<change> reduces <target metric> by ≥ <margin> on
<lanes> without moving wer_mean by more than +0.002 or rtf_p95 by more than
×1.25."

## 2 Symptom & mechanism
The user-visible symptom (from README.md's list), the code path that produces
it with `file:line` citations into `src/stenographer/` and, where relevant,
`.venv/lib/python3.14/site-packages/faster_whisper/`, and why the proposed
change should act on it.

## 3 Prerequisites
- Harness pieces: which of §1's modules and subcommands must exist.
- Injection fields: the `DecodeOptions` fields or config keys used.
- Corpus lanes/tags: which lanes; which plan produces them if not `base`.
- Baseline: `docs/experiments/baseline.json` present with `noise` for the
  target metric.

## 4 Variant matrix
A table of every variant with exact values, and the checked-in path of each
variant JSON under `docs/experiments/variants/<plan>/`. State the engine and
`repeats` for each.

## 5 Procedure
The exact commands the executing agent runs, in order, each prefixed with
`.venv/bin/python`. Include `preflight`, one `run --variant <path> --baseline
docs/experiments/baseline.json --thresholds <path>` per variant (§1 fixes the
CLI surface, `--variant` included — no plan needs to hedge about a positional
form), and what to do with each exit code. No step may require a human.

## 6 Metrics & accept/deny
The target metric, direction, margin and margin kind; the full contents of
`thresholds.json`; how a multi-variant matrix is decided (first accepted in
matrix order wins, or the best accepted by target metric — say which).

## 7 Cost estimate
clips × repeats × per-clip time from HARNESS.md §8.4, plus disk.

## 8 Risks, confounds, invariants
What else the change could move, why the guards catch it or do not, and the
§9 checklist restated.

## 9 Deliverables & follow-through
On accept: the exact default or literal to change (`file:line`), the
`DecodeOptions` default and its pinning test to update, the `AGENTS.md`
sentence to edit, the re-baseline (HARNESS.md §7.3), and the acceptance gate
in `AGENTS.md` that must be re-run on a real machine before dev → main.
On deny: append the unnumbered `## Outcome` section to this file with the verdict
line and the run id, copy `verdict.json` to
`docs/experiments/results/<plan>-<run-id>.json`, and set `Status:` to denied in
the same commit. Numbers only in both.

## 10 Out of scope
What this plan deliberately does not test, and which plan does.
```
