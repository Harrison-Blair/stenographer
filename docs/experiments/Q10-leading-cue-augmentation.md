# Q10 — leading-cue augmentation lane validation

Status: planned (2026-08-29)

This is a **corpus-validation** plan, not a change plan. Nothing under `src/`
changes as a result of it. It asks one question: *does the shipped
`record_start` cue, bleeding from the speakers into the microphone at the head
of the capture, measurably destroy the first words of an utterance under
shipped decode defaults?* ACCEPT means the symptom reproduces offline and the
`cue` lane is a valid test bed for `Q02` and the onset-clipping hypothesis.
DENY means it does not, and the diagnosis has to move to the owner's own
audio (§9).

Because the question is "does the symptom reproduce" rather than "does this
change help", the accept rule is **not** `HARNESS.md` §6.2's `decide` — a
condition must be measurably *worse* than its control, which `decide` cannot
express. Q10 therefore runs its own paired comparison (§6) over harness
`result.json` files. Every other harness rule applies unchanged.

Baseline for all `file:line` citations: `dev` @ `a1b9807` (v0.11.6),
faster-whisper 1.2.1, CTranslate2 4.8.1, in the repo venv.

---

## 1 Hypothesis

Prepending the bundled `record_start` cue at speaker-to-mic bleed level plus a
0–300 ms gap reduces `leading_word_recall_mean` (k = 3) by ≥ 0.033 absolute
against the same clips' un-augmented control, on at least one of the five
lane conditions, with a paired sign test at p ≤ 0.01 — and the run therefore
reproduces the owner's "first words go missing although the overlay showed
input" symptom under shipped defaults.

The falsifier is the whole matrix: if no condition clears both bars, the cue
lane does not reproduce the symptom and this plan is denied.

---

## 2 Symptom & mechanism

**Symptom** (`docs/experiments/README.md`, owner report 1): the first words of
an utterance go missing although the overlay showed input.

**What is already ruled out.** The overlay's spectrum is fed from the same
block the recorder appends to its buffer, inside the PortAudio callback
(`src/stenographer/audio.py:326-331` — `self._blocks.append(block)` then the
optional `self._on_block` sink on that same object). So "I saw bars" proves
the audio reached the buffer; the loss is downstream of capture. Nine logged
utterances add that `activate_ms ≤ 0.4` with no mid-session stream
re-negotiation, so capture is not late either.

**Why the cue is inside the recording at all.** By design. `on_key_down`
starts the recorder (`src/stenographer/daemon.py:482`), publishes the overlay
state, and only *then* fires the cue (`daemon.py:498-499`); the Linux cue
player spawns detached and non-blocking
(`src/stenographer/platform/linux/cues.py`, `LinuxCuePlayer.play` →
`spawn_detached`), so the tone reaches the speakers tens of milliseconds after
capture has already begun. `AGENTS.md` hard rule 5 fixes that ordering:
"Capture starts before the `record_start` cue". Whatever the microphone hears
of that tone is therefore at the head of every recording, ahead of the user's
first word, and the gap between tone and speech is the user's own reaction
time.

**The candidate mechanism — VAD onset clipping.** The shipped decode calls
`vad_filter=cfg.vad_filter` (default `true`) with
`_VAD_PARAMETERS = {threshold: 0.5, min_speech_duration_ms: 100,
min_silence_duration_ms: 500, speech_pad_ms: 250}`
(`src/stenographer/transcribe/model.py:32-37`, used at `model.py:116-117`).
faster-whisper's Silero wrapper walks 512-sample (32 ms) windows
(`.venv/lib/python3.14/site-packages/faster_whisper/vad.py:70`); a chunk opens
at the first window whose probability reaches `threshold`
(`vad.py:108-110`), and only the **first** chunk gets an unconditional
leading pad of `speech_pad_samples` (`vad.py:162-163`); every later chunk's
start is widened only through the inter-chunk branch, by half the intervening
silence or by a full pad when that silence is at least `2 × pad`
(`vad.py:164-180`). `collect_chunks` then concatenates only what survived, so
audio outside every chunk never reaches the encoder.

Two sub-mechanisms follow, and the matrix is built to tell them apart:

- **(a) The tone spends the single leading pad.** If the cue's own energy
  reaches probability 0.5, the first chunk opens *on the tone*. The 250 ms pad
  is then spent ahead of the tone, where there is nothing. If the tone-to-speech
  gap is under `min_silence_duration_ms` (500 ms — and every gap this plan
  tests is), the chunk never closes, so tone and speech arrive at the encoder
  as one span with a tone glued to its front: the leading acoustic context
  Whisper conditions on is a click, not silence.
- **(b) The tone does not trigger, and the pad reaches back over it.** If the
  cue is below threshold, the first chunk opens on the speech and the 250 ms
  pad reaches backwards — at a 0 ms gap that pad lands squarely on the cue and
  drags it in anyway; at 300 ms it lands on room tone and the cue is excluded.
  Either way the speech onset itself is preserved, and any first-word loss
  under this branch must come from the *encoder*, not the chunker.

Both sub-mechanisms predict measurable damage; they predict different *shapes*
(a is worst at small gaps, b is worst where the pad still overlaps the cue),
and §5 step 2's probe measures which one actually fires before a single token
is decoded.

**Why "cue" may be the wrong noun.** The cue is only one candidate aggravator
of a more general onset problem: any soft or slow speech onset can fail to
reach probability 0.5 for a window or two, and the chunk then opens late —
inside the first word. Log evidence for the owner's own case is thin (the one
short utterance in the record kept 100 % of its frames), so this plan carries
two **cue-free controls** — 300 ms of leading room tone alone, and a soft
speech onset — precisely so that an ACCEPT can be attributed to the cue rather
than to onsets in general. Without them a positive result is uninterpretable.

**Why the pack matters.** The bundled `record_start` cues are not
interchangeable. Measured from the assets:

| pack | rate | duration | peak | RMS | RMS dBFS | spectral centroid |
|---|---|---|---|---|---|---|
| `legacy` | 44 100 Hz | 80.0 ms | 0.2512 | 0.17007 | −15.4 | 891 Hz |
| `minimal-ui` (default) | 48 000 Hz | 72.0 ms | 0.1412 | 0.02907 | −30.7 | 8153 Hz |
| `soft-electronic` | 48 000 Hz | 72.0 ms | 0.1412 | 0.05931 | −24.5 | 669 Hz |
| `warm-desk` | 48 000 Hz | 72.0 ms | 0.1412 | 0.03256 | −29.7 | 4990 Hz |

At `HARNESS.md` §2.4's fixed bleed gain of 0.25 the cue's in-recording level
therefore spans **15.3 dB** across packs, and `legacy` is both the loudest and
the most tonal (a low-frequency 875 Hz tone, the profile most likely to look
like voiced speech to Silero) while the default `minimal-ui` is the quietest
and the most click-like. A single-pack result would not generalise, which is
why §4 covers both extremes.

---

## 3 Prerequisites

**Harness pieces that must exist and pass their unit tests**
(`HARNESS.md` §1): `scripts/asr_corpus.py`, `scripts/asr_metrics.py`,
`scripts/asr_experiment.py` with the `preflight` and `run` subcommands, and
the `base` and `cue` lanes generated into `build/asr-corpus/`.

**Injection fields**: none. Every condition runs the shipped decode defaults
— empty `config`, empty `decode`. `DecodeOptions` (`HARNESS.md` §3.2) must
exist because `validate_variant` requires the field, but Q10 never sets a
non-default value. This is deliberate: a plan that validates a corpus must not
also change the decoder.

**Corpus lanes and tags**

| lane | source | this plan |
|---|---|---|
| `base` | `HARNESS.md` §2.3, 100 clips | control, consumed as-is |
| `cue` | `HARNESS.md` §2.4, 300 clips, tags `cue=minimal-ui` + `gap={0,100,300}ms` | consumed as-is |
| `cue` (`legacy`) | **produced by this plan**, 100 clips, tags `cue=legacy` + `gap=0ms` | Fork D |
| `onset` | **produced by this plan**, 200 clips, tags `onset=tone300ms` / `onset=soft` | Fork B |

The three lanes Q10 produces are generated by `asr_corpus.py build` in step 1
of §5. Their generators land in the foundation commit and Q10 runs **before**
the baseline (`README.md` execution order, step 2), so the lanes are inside the
baseline from the start and no re-baseline is owed. Should this plan ever be
re-run after the baseline exists, only the lanes it regenerates move their
`lane_sha256`, and `compare` refuses on compared lanes alone (`HARNESS.md` §2.5,
§6.4, §7.3 case 2).

**Baseline**: **none**. Q10 runs before the baseline exists (`README.md`
execution order, step 2) and never compares against
`docs/experiments/baseline.json`: every condition is scored against the same
clips' own C0 control inside this plan. The run-to-run spread its margin must
clear is therefore measured *here*, by running C0 a second time as a separate
`run` invocation and comparing the two — the pattern `Q09` §4 uses for its own
cell 1 (§6.3).

**Environment** (`HARNESS.md` §8.2 preflight, plus): `onnxruntime` importable
(verified present, 1.28.0 — faster-whisper's bundled Silero model needs it and
nothing downloads), `soundfile` (0.14.0), `numpy` (2.5.2). No `scipy`: the
resampling is `stenographer.audio._resample_poly` (`src/stenographer/audio.py:104`),
numpy-only. The 44.1 kHz → 16 kHz path for `legacy` runs at `up=160, down=441`
through that same helper.

---

## 4 Variant matrix

Seven runs. All at shipped defaults, all `engine: "inprocess"`, all
`repeats: 1`.

**Why in-process.** Q10 measures text metrics only; `load_ms` and `total_ms`
are irrelevant to it. `HARNESS.md` §3.1 permits either engine for Q-series
plans and makes text metrics cross-engine comparable, and §8.4 puts in-process
at ≈0.7 s per clip against ≈4–5 s for subprocess — 8 minutes of decode instead
of 55. Every Q10 comparison is against **this plan's own C0 control run**, in
the same engine, in the same process configuration, so no cross-engine claim
is made at all. `engine: "inprocess"` with an empty `decode` is explicitly
legal (`HARNESS.md` §3: only *non-empty* `decode` with `engine: "subprocess"`
is an error).

**Why `repeats: 1`.** Every variant decodes at `temperature=0.0`
(`src/stenographer/transcribe/model.py:114`), which `HARNESS.md` §8.3 declares
deterministic on a fixed model, compute type and GPU; §3 requires `repeats: 3`
only when a temperature above zero is in play.

| id | condition | lane | `tags_all` | clips | variant file |
|---|---|---|---|---|---|
| C0 | control, un-augmented | `base` | — | 100 | `variants/Q10/q10-c0-base.json` |
| C1 | `minimal-ui` cue + 0 ms gap | `cue` | `["cue=minimal-ui", "gap=0ms"]` | 100 | `variants/Q10/q10-c1-cue-minimal-0ms.json` |
| C2 | `minimal-ui` cue + 100 ms gap | `cue` | `["cue=minimal-ui", "gap=100ms"]` | 100 | `variants/Q10/q10-c2-cue-minimal-100ms.json` |
| C3 | `minimal-ui` cue + 300 ms gap | `cue` | `["cue=minimal-ui", "gap=300ms"]` | 100 | `variants/Q10/q10-c3-cue-minimal-300ms.json` |
| C4 | control: 300 ms leading room tone, **no cue** | `onset` | `["onset=tone300ms"]` | 100 | `variants/Q10/q10-c4-tone300ms.json` |
| C5 | control: soft speech onset, **no prepend** | `onset` | `["onset=soft"]` | 100 | `variants/Q10/q10-c5-soft-onset.json` |
| P1 | `legacy` cue + 0 ms gap (loudest pack) | `cue` | `["cue=legacy", "gap=0ms"]` | 100 | `variants/Q10/q10-p1-cue-legacy-0ms.json` |

Every variant file is the same shape; only `name`, `lanes` and `tags_all`
differ:

```json
{
  "schema": 1,
  "name": "q10-c1-cue-minimal-0ms",
  "plan": "Q10",
  "lanes": ["cue"],
  "tags_any": [],
  "tags_all": ["cue=minimal-ui", "gap=0ms"],
  "engine": "inprocess",
  "repeats": 1,
  "config": {},
  "decode": {}
}
```

**Pack coverage and its justification.** The full gap sweep runs on
`minimal-ui` because that is `DEFAULT_SOUND_PACK` and what an un-configured
user hears (`src/stenographer/config.py:269`, `feedback.sound_pack`). `legacy`
is added at the single worst gap (0 ms) as P1 because it sits 15.3 dB louder
and 7 kHz lower in centroid than the default — the two extremes of the bundled
spread bracket the other two packs, whose measured RMS (−24.5 and −29.7 dBFS)
falls between them. `warm-desk` and `soft-electronic` are run **only if** P1
and C1 disagree on the accept decision, since that is the only outcome in
which the pack is load-bearing (§5 step 6). This buys the coverage of a
four-pack sweep for a third of the clips.

**Augmentation definitions for the lanes Q10 produces.** Deterministic, pure
numpy, seeded exactly as `HARNESS.md` §2.4 seeds the `tail` lane
(`zlib.crc32(clip_id.encode())` XOR a per-condition integer, so the same clip
and condition always yield the same noise, and no two conditions collide):

- **P1, `cue=legacy`, `gap=0ms`** — `HARNESS.md` §2.4's `leading_cue`
  augmentation verbatim, with `pack: "legacy"`. Resample the 44.1 kHz asset to
  16 kHz with `_resample_poly`, scale by `0.25`, prepend, no gap. Ids
  `<base>+cuelegacy0ms`. Seed XOR `0x6C650000 | 0`.
- **C4, `onset=tone300ms`** — prepend 300 ms of Gaussian noise at −60 dBFS
  RMS, no cue at all. `augmentation = {"kind": "leading_noise", "seconds":
  0.3, "rms_dbfs": -60.0}`. Ids `<base>+tone300ms`. Seed XOR `300`. This is
  the control that separates "the cue causes it" from "any leading
  non-speech causes it": it has the same 300 ms of pre-speech material as C3
  and none of the tone.
- **C5, `onset=soft`** — no prepend. Multiply the first 200 ms of the clip by
  a linear amplitude ramp from `0.25` (−12 dB) at sample 0 to `1.0` at
  sample `3200`, leaving the rest untouched. `augmentation = {"kind":
  "soft_onset", "onset_gain": 0.25, "ramp_ms": 200}`. Ids `<base>+soft`. No
  noise, so no seed. A *ramp* rather than a −12 dB step because a step
  introduces a discontinuity at 200 ms that is itself an acoustic event; the
  load-bearing number is the gain at the onset, which is −12 dB either way.
  This is the control that tests onset clipping with the cue removed entirely.

Additionally, `asr_corpus.py` records `leading_silence_ms` on every **base**
clip as a tag (the offset of the first 32 ms frame whose RMS exceeds the
clip's own peak RMS minus 30 dB, rounded to 10 ms). LibriSpeech clips are
trimmed to clean onsets, so this number is expected to be small; it is
recorded because a base lane whose clips already start at sample 0 is a
different experiment from one with 80 ms of runway, and §8 needs it to
interpret C0's own recall.

---

## 5 Procedure

Every command is run from the repository root with the repo venv. No step
requires a human. An unexpected exit code at any step aborts the plan and is
reported as a harness error, not as a verdict.

### Step 0 — preflight

```sh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration" -q
.venv/bin/python scripts/asr_experiment.py preflight
```

Exit 0 on all three, or stop. `preflight` exit 2 means the model is not
cached, the GPU is absent, or the corpus manifest is missing/mismatched; its
message names which. Never work around it — in particular, never download the
model from here (`AGENTS.md` hard rule 5).

### Step 1 — generate the three lanes this plan adds

```sh
.venv/bin/python scripts/asr_corpus.py build --lanes cue \
  --pack legacy --gain 0.25 --gaps 0
.venv/bin/python scripts/asr_corpus.py build --lanes onset \
  --leading-noise-ms 300
.venv/bin/python scripts/asr_corpus.py build --lanes onset \
  --soft-onset-gain 0.25 --soft-onset-ramp-ms 200
.venv/bin/python scripts/asr_corpus.py build --verify
```

`build` is the one lane generator subcommand (`HARNESS.md` §1): the old
`augment` and `verify` spellings are options of it, not subcommands of their
own. `--verify` re-hashes every clip against the manifest and prints the new
manifest SHA-256. Record it; it goes in §9's re-baseline note. Expect +400 clips
(100 P1 + 200 onset + the 100 `leading_silence_ms` tags rewritten on `base`)
and ≈120 MB.

### Step 2 — the VAD probe (mechanism, before any decoding)

```sh
.venv/bin/python scripts/q10_vad_probe.py \
  --manifest build/asr-corpus/manifest.json \
  --conditions base,cue-minimal-0ms,cue-minimal-100ms,cue-minimal-300ms,tone300ms,soft,cue-legacy-0ms \
  --out build/asr-experiments/q10-vad-probe.json
```

This runs **only** `faster_whisper.vad.get_speech_timestamps` with
`stenographer.transcribe.model._VAD_PARAMETERS` on each clip. It loads
faster-whisper's bundled Silero ONNX model (`vad.py:84`,
`faster_whisper.utils.get_assets_path`) and **never loads the ASR model**, so
it costs ≈50 ms per clip — under a minute for all 700. It is the cheapest
decisive measurement in the plan, and it runs first because it can answer
*why* before the decoder answers *whether*.

Per clip it records, all numeric:

- `speech_onset_s` — exact, known by construction: `(prepended samples) /
  16000`. Zero for `base` and `soft`.
- `vad_first_chunk_start_s` — `chunks[0]["start"] / 16000`, or `null` if the
  VAD returned no chunk at all.
- `onset_clip_ms` — `max(0, vad_first_chunk_start_s − speech_onset_s) × 1000`.
  Positive means the chunker opened *inside* the first word. This is the
  direct numeric measurement of onset clipping.
- `cue_triggered` — `vad_first_chunk_start_s < cue_end_s`, i.e. the chunk
  opened on the tone (sub-mechanism (a)). `null` where there is no cue.
- `chunk_count`, `vad_seconds` — for context.
- `no_chunks` — `true` when Silero found nothing, which would make the clip
  decode to empty.

Aggregate per condition: `onset_clip_ms` mean / p50 / p95, `cue_triggered`
rate, `no_chunks` rate. The probe writes numbers only, no text, no clip audio.

**The probe cannot decide the plan** — a chunk boundary is not a lost word —
but it constrains the interpretation of every later number, and if it shows
`onset_clip_ms = 0` and `cue_triggered = false` on every condition, the
mechanism section's whole story is wrong and that must be stated in the
outcome regardless of the decode verdict.

### Step 3 — the seven decode runs

```sh
for v in q10-c0-base q10-c1-cue-minimal-0ms q10-c2-cue-minimal-100ms \
         q10-c3-cue-minimal-300ms q10-c4-tone300ms q10-c5-soft-onset \
         q10-p1-cue-legacy-0ms; do
  .venv/bin/python scripts/asr_experiment.py run \
    --variant docs/experiments/variants/Q10/$v.json \
    || echo "RUN FAILED: $v"
done
```

No `--baseline` and no `--thresholds`: `HARNESS.md` §6.2's `decide` is not the
rule here (§6 below), so `run` is invoked in its plain form and exits 0 on a
completed run. An exit 2 on any variant aborts the plan. C0 must run first so
that a failure in the control stops the plan before six pointless runs.

Record the seven run ids. They are `<timestamp>-<variant name>`; the executing
agent resolves each by taking the newest directory under
`build/asr-experiments/` matching `*-<variant name>`.

### Step 4 — the paired comparison

```sh
.venv/bin/python scripts/asr_experiment.py compare-paired \
  --control  build/asr-experiments/<C0 run id>/result.json \
  --conditions build/asr-experiments/<C1 run id>/result.json \
               build/asr-experiments/<C2 run id>/result.json \
               build/asr-experiments/<C3 run id>/result.json \
               build/asr-experiments/<C4 run id>/result.json \
               build/asr-experiments/<C5 run id>/result.json \
               build/asr-experiments/<P1 run id>/result.json \
  --metric leading_word_recall \
  --margin 0.033 \
  --alpha 0.01 \
  --out build/asr-experiments/q10-verdict.json
```

`compare-paired` is Fork A (§6.4). It pairs each condition's `clip_scores`
rows to the control's by base id (`clip_id.split("+", 1)[0]`), refuses if the
`corpus.manifest_sha256`, `environment.device`, `environment.model` or
`engine` differ between control and condition, refuses if fewer than 100 pairs
survive, and prints one line per condition plus a Markdown table. Exit `0` if
**at least one cue condition (C1, C2, C3, P1)** accepts, `1` if none does,
`2` on a refusal.

### Step 5 — read the exit code

- **0 — ACCEPT.** The symptom reproduces. Go to §9's accept branch.
- **1 — DENY.** Before concluding, run the single pre-declared escalation in
  step 6. Only if that also denies is the plan denied.
- **2 — harness error.** Fix and re-run; never reinterpret a refusal as a
  verdict.

### Step 6 — the two pre-declared conditional runs

Both are declared here, in advance, so that neither is a post-hoc search for a
significant result. **No further variants may be added to Q10.**

**(6a) Escalated bleed gain — fires only on a DENY in step 5.** The 0.25 gain
is an assumption, not a measurement (§8). Re-generate the four cue conditions
at gain `0.60` (−4.4 dB) into ids suffixed `@g60`, re-run C1/C2/C3/P1 against
the same C0, and re-run step 4. If step 4 now exits 0, the plan ACCEPTs **with
the gain qualified**: the canonical lane (§9) carries `gain: 0.60` and the
deliverable says plainly that the shipped `record_start` at a realistic bleed
level does *not* reproduce the symptom, and only a loud bleed does.

```sh
.venv/bin/python scripts/asr_corpus.py build --lanes cue --pack minimal-ui \
  --gain 0.60 --gaps 0,100,300 --id-suffix @g60
.venv/bin/python scripts/asr_corpus.py build --lanes cue --pack legacy \
  --gain 0.60 --gaps 0 --id-suffix @g60
# then the four variant files under variants/Q10/ with tags_all gain=g60,
# then step 3 for those four, then step 4 again.
```

**(6b) The remaining two packs — fires only when P1 and C1 reach different
accept decisions** (in either step-5 or step-6a form). Generate
`cue=warm-desk` and `cue=soft-electronic` at `gap=0ms` and the same gain,
run them, and add them to step 4. This resolves whether the effect tracks cue
level, and its answer selects the canonical lane's pack in §9.

If 6a and 6b both fire, run 6a first; 6b then uses 6a's gain.

---

## 6 Metrics & accept/deny

### 6.1 Target metric

`leading_word_recall(ref, hyp, k=3)` (`HARNESS.md` §5.4) — over the first
three reference words, the fraction whose alignment op is `match`. A
substituted first word counts as missed, which is exactly the user's
experience. Direction for this plan: the condition must be **lower** than the
control.

Reported alongside, not gated on: `leading_miss_rate`, `wer_mean`,
`deletion_rate`, `insertion_rate`, `empty` count, and step 2's `onset_clip_ms`
and `cue_triggered` aggregates.

### 6.2 The rule

Let `P` be the set of base ids present in both the control's and the
condition's `clip_scores`. For each `i ∈ P`, `d_i = recall_control(i) −
recall_condition(i)`.

A condition **reproduces the symptom** iff **all three** hold:

1. **Effect size.** `mean(d_i) ≥ 0.033`.
2. **Significance.** Over the `m = |{i : d_i ≠ 0}|` discordant pairs, with
   `w = |{i : d_i > 0}|` (condition worse), the exact two-sided binomial sign
   test at `p = 0.5` gives `p ≤ 0.01`, **and** `w > m − w`. Computed with
   `math.comb`, no SciPy.
3. **Coverage.** `|P| ≥ 100` and the condition's `errors` count is 0.

The **plan** ACCEPTs iff at least one of C1, C2, C3, P1 reproduces the
symptom. C4 and C5 are controls: they never make the plan accept, and their
results only qualify the interpretation (§6.5).

### 6.3 Why 0.033

`k = 3`, so a clip that loses exactly its first word and keeps the next two
drops from `1.0` to `2/3` — a per-clip `d_i` of `0.3333`. A mean of `0.033`
over 100 clips is therefore, to a rounding, **"one clip in ten lost its first
word"**. That is a threshold with a physical meaning rather than a statistical
one, and it is the smallest effect the owner would plausibly notice as a
recurring symptom: a 1-in-10 first-word loss over a working day is dozens of
mangled dictations, while 1-in-50 is folklore.

Two further checks on the number:

- **Against machine noise, measured locally.** This plan has no baseline to read
  a `noise` figure from, so it measures its own: run C0 **twice**, as two
  separate `run` invocations, and take
  `|leading_word_recall_mean(C0a) − leading_word_recall_mean(C0b)|` as the
  machine's run-to-run spread on this metric. **Abort as a harness error if it
  exceeds 0.0165.** At temperature 0 on a fixed GPU it is expected to be 0.000;
  anything near 0.0165 means the machine is not deterministic and no verdict on
  this metric — here or in Q02 — is trustworthy. Record the measured figure in
  the Outcome; it is what Q02 and `HARNESS.md` §7.1's `noise` block will later
  be checked against.
- **Against chance.** Guard 2 is what stops a 0.033 mean produced by three
  clips swinging wildly rather than ten clips each losing a word. With
  `w = 10, m = 10` the sign test gives `p ≈ 0.002`; with `w = 3, m = 3`,
  `p = 0.25` and the condition is correctly refused despite possibly clearing
  guard 1.

### 6.4 Fork A — `compare-paired` and its pure core

This plan needs two things the harness does not have. Both are pure,
stdlib-only, and belong in `scripts/asr_metrics.py` beside the other scorers,
with seen-to-fail tests in `tests/test_asr_metrics.py` (`AGENTS.md` hard rule
4). Proposed as `HARNESS.md` §5.7:

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

Worked examples to write as tests first:

- `pair_by_base` with control ids `a, b` and condition ids `a+cue0ms,
  c+cue0ms` → one pair, `("a", ...)`; the unmatched `b` and `c` are dropped.
- `paired_delta` on ten pairs where the condition is `2/3` and the control
  `1.0` on each → `n=10, worse=10, better=0, mean_delta=0.3333, p_value=2^-9
  ≈ 0.001953`.
- `paired_delta` on pairs that are all equal → `worse=better=0`,
  `mean_delta=0.0`, `p_value=1.0`.
- `paired_delta` on `worse=6, better=4, tied=90` → `mean_delta` from the
  values, `p_value = 0.7539` (the two-sided exact test at m=10, w=6; assert
  that literal).

`compare-paired` in `asr_experiment.py` is the thin I/O shell over these: load
the JSON, run the refusals, call the two functions, render, exit. Its only
testable pure helper is the refusal predicate.

### 6.5 Interpreting the controls

The controls do not gate the verdict; they name what an ACCEPT is *about*, and
the outcome section must state which of these it is.

| C1–C3/P1 | C4 (tone only) | C5 (soft onset) | reading |
|---|---|---|---|
| reproduces | no | no | **The cue is the cause.** The strongest result: the lane is a clean cue test bed and the fix space includes the cue itself. |
| reproduces | reproduces | either | **Leading non-speech is the cause**, cue or not. The lane is still a valid Q02 test bed, but the deliverable must say the cue is an instance, not the mechanism. |
| reproduces | no | reproduces | **Onset weakness is the cause** and the cue aggravates it. Q02's grid should span `vad_threshold` downward as well as `speech_pad_ms` upward. |
| no | reproduces or not | reproduces | Plan DENIES on its own terms; the accepting control still names a real onset problem and §9's deny branch routes it to Q02 directly. |

### 6.6 Output

`build/asr-experiments/q10-verdict.json` (numbers only) and a printed table:
one row per condition with `n`, `mean_control`, `mean_condition`,
`mean_delta`, `worse`, `better`, `tied`, `p_value`, each guard's pass/fail,
plus the ungated `wer_mean` and `leading_miss_rate` deltas and step 2's
`onset_clip_ms` p50 and `cue_triggered` rate.

---

## 7 Cost estimate

`HARNESS.md` §8.4: in-process ≈0.7 s per clip after one model load per
variant; the corpus tools are numpy-only.

| step | work | time | disk |
|---|---|---|---|
| 0 preflight | lint, unit suite, one cold model load | ≈3 min | — |
| 1 lane generation | 400 derived clips, numpy + `_resample_poly` | ≈2 min | ≈120 MB |
| 2 VAD probe | 700 clips × ≈50 ms, Silero only | ≈1 min | < 1 MB |
| 3 decode | 7 variants × 100 clips × 1 repeat × 0.7 s, + 7 loads | ≈9 min | ≈20 MB |
| 4 comparison | pure | < 1 s | < 1 MB |
| **base total** | 700 decoded clips | **≈15 min** | **≈140 MB** |
| 6a escalation (conditional) | 400 clips generated + decoded | +≈7 min | +≈120 MB |
| 6b two packs (conditional) | 200 clips generated + decoded | +≈4 min | +≈60 MB |
| **worst case** | 1300 decoded clips | **≈26 min** | **≈320 MB** |

Well inside `HARNESS.md` §8.2's 1 GiB free-space preflight. The subprocess
engine would have cost ≈55 min for the base matrix alone and bought nothing
this plan measures.

---

## 8 Risks, confounds, invariants

**The bleed gain is an assumption, not a measurement.** `HARNESS.md` §2.4's
`0.25` is stated as "the speaker-to-mic bleed level this lane assumes; a real
measurement can replace it". Real bleed depends on speaker volume, the
laptop's speaker-to-mic geometry, any acoustic echo cancellation in the
capture chain, and `feedback.volume`. It could plausibly be anywhere from
−30 dB (headphones, AEC on) to −3 dB (laptop speakers at full volume). This is
the single largest threat to the plan's validity and it cuts both ways: a
DENY at 0.25 may simply mean the gain is too low, which is exactly why step 6a
is pre-declared; an ACCEPT at 0.25 may overstate a level the owner never
reaches, which is why §9's deliverable records the gain in the canonical lane
name and why measuring it is the first item of follow-up work.

**Speaker-to-mic latency is not modelled.** The augmentation places the cue at
sample 0. In reality the cue reaches the microphone after the player process
spawns (`spawn_detached`), the audio server mixes it, the speaker emits it and
it travels ≈0.3 m — realistically 20–120 ms after `on_key_down`, and jittery.
The 0 ms condition is therefore optimistic about how early the tone lands and
the 100 ms condition is arguably the most realistic *cue placement*, while the
gap parameter models the user's reaction time on top of that. The consequence
for the verdict is small (all three placements sit far inside the 500 ms
`min_silence_duration_ms`, so none of them changes the chunking topology), but
it means the gap axis should be read as "cue-to-speech interval", not as
"reaction time", and §9's HARNESS edit says so.

**LibriSpeech clips begin with clean, trimmed onsets.** Read speech recorded in
a quiet room with a deliberate start is close to the best case for a VAD
trigger; the owner's real utterances start mid-breath, at a conversational
level, often with a soft function word ("um", "so", "the"). The corpus
therefore *understates* onset fragility, and a DENY is weaker evidence than an
ACCEPT is. C5 exists specifically to push against this, and step 1's
`leading_silence_ms` tag records how much runway the base clips actually have
so the outcome can say whether C0's own recall was already at ceiling. If C0's
`leading_word_recall_mean` is 1.000, every `d_i` is one-sided and the sign
test is conservative in the right direction; if C0 is below ≈0.95 the base
lane has its own onset problem and the outcome must say so.

**Cross-condition confounds inside the augmentation.** Prepending material
lengthens the clip, which raises `_token_budget(128, audio_seconds)`
(`src/stenographer/transcribe/model.py:172-175`) and `_validate_output`'s word
limit (`model.py:200`). Both move *upward* by at most ~3 tokens for 300 ms, so
neither can cause a first-word loss; they are noted so a reader does not
mistake them for one. Prepending also cannot change the RMS gate verdict:
`speech_gate_stats` needs two consecutive loud 50 ms frames anywhere
(`src/stenographer/audio.py:72-100`), and −60 dBFS noise adds none.

**The new lanes and the manifest — settled, no longer a fork.** Adding 400 clips
moves `manifest_sha256`, but `HARNESS.md` §2.5 records a `lane_sha256` per lane
and §6.4 refuses only on the digests of the lanes a comparison actually scores.
Adding a lane therefore invalidates nobody's comparison. Q10 is doubly
unaffected: it never calls `compare`, and it runs before the baseline exists
(`README.md` execution order, step 2), so its lanes are inside the baseline from
the start and §9 item 4 carries no re-baseline obligation. The alternative — a
second manifest — stays rejected: it would fork the corpus, and two corpora is
exactly the state §6.4 exists to prevent.

**Statistical caveat.** Guard 2's sign test treats each clip as independent.
LibriSpeech clips share 40 speakers, so per-speaker correlation makes the true
p slightly larger than the reported one. `α = 0.01` rather than the
conventional 0.05 absorbs this with room to spare; a result that sits between
0.01 and 0.05 is refused, which is the conservative direction for a plan whose
ACCEPT authorises downstream work.

### Invariant checklist (`HARNESS.md` §9)

- **No transcript text** anywhere outside `build/*/clips.jsonl`. This file, the
  variant files, `q10-vad-probe.json`, `q10-verdict.json`, every printed table
  and any `docs/experiments/results/` artefact carry numbers only. The
  in-process engine installs no logging, so no `stenographer.log` is written
  by steps 2–4 at all.
- **No network in the ASR path.** `Model` keeps `local_files_only=True`
  (`src/stenographer/transcribe/model.py:87`). Q10 downloads nothing: the
  corpus tarball is already fetched, the ASR model is already cached
  (preflight refuses otherwise), and the Silero VAD model step 2 uses is
  bundled inside the installed faster-whisper wheel
  (`faster_whisper.utils.get_assets_path`).
- **No platform imports.** Step 2's `scripts/q10_vad_probe.py` imports
  `stenographer.audio`, `stenographer.transcribe.model` (for
  `_VAD_PARAMETERS`), `stenographer.delivery.feedback` (for
  `bundled_sound_root`, `src/stenographer/delivery/feedback.py:61`),
  `faster_whisper.vad`, `soundfile` and `numpy`, and nothing in
  `tests/platform/test_core_isolation.py`'s `BLOCKED` tuple. Add it to that
  test's source grep alongside the three harness scripts.
- **Test policy.** `pair_by_base` and `paired_delta` (§6.4) are pure, get
  seen-to-fail tests from §6.4's four worked examples, and mock nothing. The
  probe's and `compare-paired`'s I/O is exercised only by running them for
  real on the reference machine.
- **Fixed behaviour stays fixed.** Q10 sets no `DecodeOptions` field and no
  config key. `src/stenographer/` is untouched by this plan in both branches;
  the follow-up in §9's deny branch is a separate plan with its own commit.
- **Venv only**, SPDX header on `scripts/q10_vad_probe.py`, ruff clean, line
  length 100, py312 syntax.

---

## 9 Deliverables & follow-through

### On ACCEPT

**1. The canonical `cue` lane — mechanical selection rule.** Among the cue
conditions (C1, C2, C3, P1, and their 6a/6b variants if those fired) that
reproduced the symptom, the canonical lane condition is the one with the
largest `mean_delta`; ties break by (i) smaller `gap_ms`, (ii) the default
pack `minimal-ui` over any other, (iii) lexicographically smallest condition
id. Controls C4 and C5 are **never** eligible: the canonical lane must be what
the daemon actually produces. The rule is mechanical so no judgement enters
the choice.

**2. The proposed `HARNESS.md` edit.** Replace §2.4's `cue` lane paragraph
with the validated parameters, and pin the canonical tag. Concretely, the
sentence "scaled by `0.25` (−12 dB, the speaker-to-mic bleed level this lane
assumes; a real measurement can replace it by editing this sentence)" becomes
the winning gain with `Q10` and its verdict cited, plus three added sentences:
the canonical condition's tag (which downstream plans filter on), the note
that `gap_ms` is the cue-to-speech interval and not reaction time (§8), and
the pack coverage actually validated. Add `leading_noise` and `soft_onset` to
§2.5's `kind` list and `onset` to its `lane` list — both are already there, so
this reduces to confirming the parameters. Fork A's two functions are already
`HARNESS.md` §5.7 with their worked examples, and §7.1's `noise` block already
records every aggregate key including `leading_word_recall_mean` (Fork C).

**3. What Q02 inherits.** The `README.md` execution order already names Q02 as
a cue-lane consumer. Q02's variant files filter on the canonical tag; its
thresholds file targets **`leading_miss_rate`, direction `lower`** (Q02 §6),
and its margin must recover at least half of Q10's measured `mean_delta` —
recorded here as a number so Q02 does not invent one. Q10 measures
`leading_word_recall_mean` per clip because its own comparison is paired
(§6.4); the corpus-level metric both plans state a threshold on is
`leading_miss_rate`.

**4. Re-baseline: none owed.** Q10 runs before the baseline (`README.md`
execution order), and the baseline command already covers `base,tail,cue,onset`
among its seven lanes (`HARNESS.md` §7.1). Record the manifest SHA-256 and the
`cue` and `onset` `lane_sha256` digests in the Outcome so the baseline that
follows can be checked against them. Only a *later* regeneration of those lanes
would owe a re-baseline, and then only for the lanes actually compared
(§7.3 case 2).

**5. No `src/` change and no acceptance gate.** Q10 validates a corpus; it
changes no default and no literal, so `AGENTS.md`'s dev → main acceptance
gates are not triggered by it. Only the commit that adds
`scripts/q10_vad_probe.py`, the three augmentation modes, Fork A's functions
and the `HARNESS.md` edits is reviewed, and it is dev-tooling only.

**6. Status line and outcome.** Set Status to `accepted (<date>)`, append an
`## Outcome` section with the verdict line, the seven run ids, the manifest
SHA-256, the step-2 probe aggregates, and the selected canonical condition.
Numbers only.

### On DENY

Set Status to `denied (<date>)`, append `## Outcome` with the same numeric
content plus which of §6.5's readings applies, copy `q10-verdict.json` and
`q10-vad-probe.json` to `docs/experiments/results/Q10-<run-id>.json`, and
state plainly: **the `cue` lane does not reproduce the symptom at the gains
tested, and it must not be used as Q02's primary evidence.** The lane may
still be kept as a regression guard.

Two follow-up diagnostics, in priority order. Both are *separate plans*, not
part of this one:

**(D1) Instrument the daemon to log the VAD onset offset — a new plan, `Q13`.**
Today nothing in the log says where the chunker opened. faster-whisper does
not expose the chunk list: `TranscriptionInfo` carries `duration_after_vad`
and `vad_options` but no timestamps
(`.venv/lib/python3.14/site-packages/faster_whisper/transcribe.py:101-108`).
It does, however, map segment timestamps back into original-audio time before
returning them (`transcribe.py:1009-1010`, `restore_speech_timestamps`), so
the first kept segment's `start` **already is** the VAD onset in the original
recording's clock and is available for free at
`src/stenographer/transcribe/model.py:215` (`kept`). Q13's change is one
numeric field: `vad_lead_ms = round(min(seg.start for seg in kept) * 1000)`,
carried on `TranscriptionResult`, into `UtteranceRecord`, and out through
`summary_fields` (`src/stenographer/transcribe/pipeline.py:77`) onto the one
`pipeline: utterance` line. It is a number, so `AGENTS.md` hard rule 6 is
satisfied by construction. With it, a week of the owner's real dictation
answers the question this plan could not, on real audio, with no corpus at
all — and it is the cheapest instrument in the whole programme.

**(D2) The `user` lane — a new plan, `X02`, owner-in-the-loop.** The owner
records N ≥ 30 real utterances through the real microphone with the daemon
running at the real `feedback.volume` and the real pack, types the reference
for each, and they enter the manifest as `lane: "user"` (`HARNESS.md` §2.4
already reserves it). This is the only lane that carries the true bleed level,
the true room, the true onset and the true microphone, and it settles both the
gain assumption and the clean-onset confound at once. It needs a human, so it
is filed beside `X01` and marked not hands-off.

D1 comes first: it is hands-off, costs one small numeric field, and its data
accumulates passively while X02 waits on the owner.

---

## 10 Out of scope

- **Any change to the decode stack.** Q10 sets no `DecodeOptions` field and no
  config key. Tuning `vad_threshold`, `speech_pad_ms` or
  `min_silence_duration_ms` against first-word loss is **Q02**, which is this
  plan's principal consumer and which must not start before Q10 resolves.
- **Whether the cue should be moved, delayed, quietened or removed.** The cue
  ordering is a fixed invariant (`AGENTS.md` hard rule 5: capture starts before
  the cue, and cue failures cannot delay capture boundaries); changing it is a
  design decision recorded in `AGENTS.md`, not an experiment outcome. Q10 may
  make the case; it may not make the change.
- **Trailing hallucination and end-of-utterance loops.** That is the `tail`
  lane: **Q09** builds it, **Q01/Q05/Q07/Q11** consume it.
- **Empty transcripts on quiet speech** (`vad_frames=0` at `peak_rms 0.024`).
  Related mechanism, different symptom, different lane filter: **Q02** for the
  VAD half and **Q06** for the `_assemble` no-speech gate.
- **Latency of any kind.** In-process runs make `load_ms` and `total_ms`
  meaningless here by construction; cold-start cost is **S01**.
- **Model choice.** `medium.en` throughout; **Q12** varies it.
- **Measuring the real speaker-to-mic bleed level.** The one number this plan
  most wants and cannot get without a microphone. It belongs to **X02**.
- **Channel order on a real stereo microphone.** **X01**.
