# Q09 — trailing-silence augmentation lane validation

Status: planned (2026-08-29)

This is a **corpus-validation** plan, not a quality plan. It changes nothing
under `src/`. Its question is whether the `tail` lane defined in `HARNESS.md`
§2.4 actually reproduces the owner's trailing-hallucination symptom under the
shipped defaults, so that `Q01`, `Q05`, `Q07` and `Q11` have a test bed with
a measurable symptom to reduce. Its accept criterion is therefore **"the
symptom reproduces measurably"**, never "quality improved".

Baseline for every `file:line` citation: `dev` @ `a1b9807` (v0.11.6),
faster-whisper 1.2.1, CTranslate2 4.8.1, in the repo venv.

---

## 1 Hypothesis

Appending room tone to a clean corpus clip and decoding it under the shipped
defaults raises `trailing_junk_rate` by at least **0.10 absolute** over the
same clips without the tail, for at least one appended duration in
{1 s, 3 s, 5 s}, thereby reproducing the owner's trailing-hallucination
symptom offline.

The template's guard clause ("without moving `wer_mean` by more than +0.002 or
`rtf_p95` by more than ×1.25") **does not apply**: no decode-side or
config-side change is proposed, both sides of the comparison run the shipped
defaults, and `wer_mean` is *expected* to move on the tail cells — that
movement is a diagnostic (§8, R2), not a guard. `HARNESS.md` §6.2's `decide`
is likewise never invoked: it compares two runs over the *intersection of clip
ids*, and base ids (`1089-134686-0001`) and tail ids
(`1089-134686-0001+tail3s`) never intersect. The verdict comes from this
plan's own rule (§6), implemented by the script in §5.4, which is exhaustive
and mechanical.

## 2 Symptom & mechanism

### 2.1 The symptom

`docs/experiments/README.md` records the owner's report (2) verbatim: *some
utterances end in hallucinated loops ("thank you", "and more and more")*.
`HARNESS.md` §5.5 encodes exactly that shape as `trailing_junk`: (a) two or
more hypothesis words past the last aligned reference word, or (b) a terminal
1-, 2- or 3-gram repeated three times that the reference does not itself
repeat. `"see you tomorrow thank you"` trips (a); `"see you tomorrow and more
and more and more"` trips both.

### 2.2 Why real captures carry a tail

Nothing in the daemon trims trailing silence before decode. The recorder
returns everything it captured (`src/stenographer/audio.py`), and
`speech_gate_stats` (`src/stenographer/audio.py:72-101`) *decides* whether the
capture is speech at all — it frames the buffer, takes per-frame RMS, and
returns a verdict plus the numbers behind it — but it never slices the buffer.
Its return value is a `GateStats`, not audio.

The capture therefore runs from the press to the stop, and the stop is a human
action. In `hold` that is the key release; in `toggle` and in a latched
`hybrid` tap (`AGENTS.md`, hotkey modes) the gap between the last spoken word
and the stop press is routinely seconds. Those seconds are room tone at the
owner's mic gain, and they go straight into the decoder.

### 2.3 What the decoder does with it

`Model.transcribe` (`src/stenographer/transcribe/model.py:110-125`) passes the
whole buffer with `vad_filter=cfg.vad_filter` (default `true`,
`src/stenographer/config.py:258`) and `_VAD_PARAMETERS`
(`model.py:32-37`): `threshold 0.5`, `min_speech_duration_ms 100`,
`min_silence_duration_ms 500`, `speech_pad_ms 250`.

1. **VAD removes most of the tail, but keeps 250 ms of it.** With
   `vad_filter` on, faster-whisper replaces the audio with the concatenation
   of the detected speech chunks
   (`.venv/lib/python3.14/site-packages/faster_whisper/transcribe.py:885-893`).
   The final chunk's end is extended by `speech_pad_samples`
   (`faster_whisper/vad.py:178-181`, the `else` arm of the loop at
   `vad.py:161-181`), i.e. 250 ms at 16 kHz = 4000 samples of tail survive.
   `duration_after_vad` (`transcribe.py:893`) is what
   `model.py:139` reports back as `vad_seconds` and what the summary line
   carries as `vad_frames`.
2. **The encoder then zero-pads to 30 s.** Each seek window's mel features are
   passed through `pad_or_trim`
   (`faster_whisper/transcribe.py:1180` → `faster_whisper/audio.py:111-123`),
   which right-pads the feature array to 3000 frames with **zeros**. Whisper
   was trained on 30 s windows and is well known to emit end-of-audio filler
   ("thank you", "thanks for watching", subtitle credits) into that pad.
3. **The shipped stack already fights back.**
   `hallucination_silence_threshold=2.0` (`model.py:27`, passed at
   `model.py:119`, consumed at `faster_whisper/transcribe.py:1294-1320`) skips
   windows whose word timings show a silence gap of ≥2 s, and
   `no_repeat_ngram_size=3` (`model.py:115`) forbids a repeated trigram
   outright. `_token_budget` (`model.py:26,28,173-175`) caps generation at
   `min(128, 16 + ceil(8 × audio_seconds))`, and `_validate_output`
   (`model.py:200-204`) raises `PathologicalOutputError` above the same word
   density. Q07 and Q05 exist to test the first two; Q09 must establish that
   there is a symptom left for them to reduce.

### 2.4 Why this could legitimately fail to reproduce — read before running

`pad_or_trim` pads **every** clip shorter than 30 s, tail or no tail. A 4 s
LibriSpeech base clip is already 26 s of zeros in feature space. So the
classic trigger is present in the `base` cell too, and the *marginal* effect
of the `tail` lane is only:

- 250 ms of **non-zero, non-silent** content immediately after the last word
  (instead of an abrupt cut to zeros), and
- whatever additional audio the VAD wrongly keeps when the tone is loud
  enough to trip `threshold 0.5`.

If −60 dBFS Gaussian noise is far below the Silero VAD's threshold — which is
the expectation — the concatenated audio the encoder sees is identical to the
base clip apart from that 250 ms, the mel features are near-identical, and a
greedy temperature-0 decode returns the **same tokens**. That is a real and
likely deny path, it has a mechanical fingerprint (§8, R1: `vad_frames` barely
moves), and the escalation ladder in §5 exists precisely to walk out of it
before concluding anything.

## 3 Prerequisites

**Harness pieces.** All of `HARNESS.md` §1 must exist and pass its pure tests:
`scripts/asr_corpus.py`, `scripts/asr_metrics.py` (this plan calls its
public `normalize` and `align`), `scripts/asr_experiment.py` with the
`preflight` and `run` subcommands, and the corpus at `build/asr-corpus/` with
`manifest.json` at schema 1.

**Baseline.** **Not required.** `docs/experiments/baseline.json` need not
exist. This plan never calls `compare` or `decide`, and it measures its own
determinism noise (§5.2, §6.3) instead of borrowing the baseline's `noise`
block. It *is* used opportunistically when present (§5.4, `baseline_crosscheck`).

Q09 should in fact run **before** `HARNESS.md` §7.1 establishes the baseline.
Its deliverable can redefine the canonical `tail` lane (§9), and doing that
after a ≈5.5 h baseline exists would force a re-baseline under `HARNESS.md`
§7.3 rule 2. Running Q09 first costs nothing and removes that risk. This
matches `docs/experiments/README.md`'s execution order, which places Q09 at
step 2, before the baseline of step 3.

**Injection fields.** None. Every Q09 variant runs `"config": {}` and
`"decode": {}` — the shipped defaults, today's literals. `DecodeOptions` is
not touched. (The one optional deny-path diagnostic in §5.5 does use it; it is
labelled a fork and is not part of the plan's verdict.)

**Corpus lanes.** Q09 produces them; no other plan supplies them.

- `tail` — the canonical lane exactly as `HARNESS.md` §2.4 defines it: 1 s /
  3 s / 5 s of Gaussian noise at **−60 dBFS RMS**, seeded
  `zlib.crc32(clip_id.encode()) ^ int(seconds * 1000)`, tag `tail=<s>s`, id
  `<base id>+tail<s>s`, 300 clips.
- `tail-n50`, `tail-n40` — **Q09-only probe lanes**, identical in every
  respect except the noise level (−50 dBFS, −40 dBFS). They exist so the
  escalation ladder never has to regenerate the canonical lane and thus never
  invalidates a manifest that downstream plans or a baseline depend on.
  `HARNESS.md` §2.5 already says new lanes are a documentation change, not a
  schema change, and §7.1's baseline lane list — `base,tail,cue,quiet,silence,
  onset,longform` — excludes the probe lanes automatically.
- `tail-room` — the same lane built from a **recorded** room-tone file, used
  only if that file is present (§3.1).

Required generator behaviour, to be implemented in `scripts/asr_corpus.py` if
it is not already there:

- **Identical noise realisation across levels.** `tail`, `tail-n50` and
  `tail-n40` must use the *same* seeded Gaussian sample for a given
  `(clip_id, seconds)`, scaled to the target RMS. Only amplitude differs, so
  the level comparison is perfectly paired.
- **Ids and filenames.** `<base id>+tail<s>s` for `tail` (per HARNESS);
  `<base id>+tail<s>s-n50`, `-n40`, `-room` for the probe lanes; WAV name
  `<id>.wav` under `build/asr-corpus/wav/<lane>/`.
- **Manifest.** Each probe clip keeps its base clip's `reference`, sets
  `derived_from` to the base id, `lane` to the probe lane name, tags
  `["<stratum>", "tail=<s>s", "noise=<source>"]` where `<source>` is one of
  `synthetic-60`, `synthetic-50`, `synthetic-40`, `recorded`, and
  `augmentation` `{"kind": "trailing_noise", "seconds": <s>, "rms_dbfs":
  <level>, "source": "synthetic"|"recorded"}`. For `recorded`, add
  `"tone_sha256": "<sha256 of the room-tone WAV bytes>"` and set `rms_dbfs` to
  the *measured* native level. The two extra keys are a `HARNESS.md` §2.5
  refinement (§9, fork F3), additive and backward-compatible.

### 3.1 Recorded room tone — optional, hands-off either way

If the file **`build/asr-corpus/roomtone/roomtone.wav`** exists, it is the
owner's own mic's room tone and is strictly better evidence than synthetic
noise: digital zeros are trivially VAD-negative, Gaussian noise is a
compromise, and only a real recording has the spectral shape (mains hum, fan,
preamp hiss) the daemon actually sees. Handling, entirely automatic:

1. Read with `soundfile`, reduce with
   `stenographer.transcribe.pipeline.downmix`, resample to 16 kHz with
   `stenographer.audio._resample_poly` — the same two core helpers
   `HARNESS.md` §2.3 uses, so the tone reaches the decoder the way a capture
   would.
2. Require ≥ 6 s of tone after conversion. Shorter, unreadable, or absent →
   **skip the `tail-room` lane entirely**, record `roomtone: "absent"` /
   `"invalid"` in the summary, and continue. A missing or bad file is never an
   error and never blocks the plan.
3. Use it at its **native level** — do not RMS-normalise it. The point of the
   recording is what the owner's mic actually produces between words; the
   synthetic sweep {−60, −50, −40 dBFS} already covers level as a controlled
   variable and brackets any plausible native value. Record the measured
   native RMS dBFS in the manifest.
4. Slice deterministically: for `(clip_id, seconds)` take a contiguous slice
   starting at `zlib.crc32(clip_id.encode()) % max(1, len(tone) - need)`,
   tiling the tone if it is shorter than `need`.

The plan's outcome record states which source produced the accepted cell, so a
`tail-room` accept and a `tail` accept are never confused.

## 4 Variant matrix

**There is no decode-side or config-side variation anywhere in this matrix.**
Every variant is the shipped defaults. The "variants" are the *cells* of the
corpus: appended duration × noise source. All variants use
`"engine": "subprocess"` and `"repeats": 1`.

Why `subprocess` rather than the ~6× cheaper in-process engine: it is the
faithful path (`.venv/bin/stenographer transcribe <wav>`, the shipped CLI,
cold load per clip), and it is the engine `HARNESS.md` §7.1 uses for the
baseline — so the `q09-base` cell can be cross-checked against
`baseline.per_lane.base` if that file ever exists, with no engine caveat
(`HARNESS.md` §3.1, §6.4). See fork F1 for the cheap alternative.

Every variant file is checked in under `docs/experiments/variants/Q09/`; the
exact command that writes all of them is §5.1. Template (only `name`, `lanes`
and `tags_all` differ between them):

```json
{
  "schema": 1,
  "name": "q09-tail-3s",
  "plan": "Q09",
  "lanes": ["tail"],
  "tags_any": [],
  "tags_all": ["tail=3s"],
  "engine": "subprocess",
  "repeats": 1,
  "config": {},
  "decode": {}
}
```

### Stage B — the primary matrix (always run)

| # | Variant file | `lanes` | `tags_all` | Clips | Engine / repeats |
|---|---|---|---|---|---|
| 1 | `q09-base.json` | `["base"]` | `[]` | 100 | subprocess / 1 — **run twice** (§5.2) |
| 2 | `q09-tail-1s.json` | `["tail"]` | `["tail=1s"]` | 100 | subprocess / 1 |
| 3 | `q09-tail-3s.json` | `["tail"]` | `["tail=3s"]` | 100 | subprocess / 1 |
| 4 | `q09-tail-5s.json` | `["tail"]` | `["tail=5s"]` | 100 | subprocess / 1 |

Cell 1 is run twice as two separate `run` invocations, which measures this
plan's own determinism noise (§6.3). Fork F2 is settled in favour of the
alternative: `HARNESS.md` §3 now makes `repeats > 1` legal at any temperature
and asserts hypothesis identity across repeats at temperature 0, so prefer
`repeats: 3` on cell 1 and drop the second invocation. The two-invocation form
is kept here as the fallback if the runner has not yet grown that assertion.

### Stage B' — recorded room tone (run only if `roomtone.wav` was usable)

| # | Variant file | `lanes` | `tags_all` | Clips |
|---|---|---|---|---|
| 5 | `q09-room-1s.json` | `["tail-room"]` | `["tail=1s"]` | 100 |
| 6 | `q09-room-3s.json` | `["tail-room"]` | `["tail=3s"]` | 100 |
| 7 | `q09-room-5s.json` | `["tail-room"]` | `["tail=5s"]` | 100 |

### Stage D — the level sweep (run only if Stages B/B' produced no accept)

| # | Variant file | `lanes` | `tags_all` | Clips |
|---|---|---|---|---|
| 8–10 | `q09-n50-{1s,3s,5s}.json` | `["tail-n50"]` | `["tail=<N>s"]` | 300 |
| 11–13 | `q09-n40-{1s,3s,5s}.json` | `["tail-n40"]` | `["tail=<N>s"]` | 300 |

Maximum matrix: 13 variants, 1400 decoded clips (1500 counting the repeated
base cell).

## 5 Procedure

Every command runs from the repository root with the repo venv
(`AGENTS.md` hard rule 1). No step requires a human.

`HARNESS.md` §1 fixes the CLI surface — `asr_corpus.py build --lanes …` for lane
generation, `asr_experiment.py run --variant <path>` for a run — and the commands
below use exactly those spellings. A sanity check before Stage A costs nothing:

```sh
.venv/bin/python scripts/asr_corpus.py --help
.venv/bin/python scripts/asr_experiment.py --help
.venv/bin/python scripts/asr_experiment.py run --help
```

### 5.1 Stage A — corpus and variant files

```sh
# 1. Corpus source (once; shared with every other plan).
.venv/bin/python scripts/asr_corpus.py fetch --prune-source

# 2. The seven baseline lanes (HARNESS.md 2.4; the foundation commit builds
#    them all, and `build` is idempotent).
.venv/bin/python scripts/asr_corpus.py build \
  --lanes base,tail,cue,quiet,silence,onset,longform

# 3. Q09 probe lanes. tail-room is skipped automatically when
#    build/asr-corpus/roomtone/roomtone.wav is absent or unusable (§3.1).
.venv/bin/python scripts/asr_corpus.py build --lanes tail-n50,tail-n40,tail-room

# 4. Confirm what exists before spending decode time.
.venv/bin/python - <<'PY'
import json, pathlib, collections
m = json.loads(pathlib.Path("build/asr-corpus/manifest.json").read_text())
c = collections.Counter(clip["lane"] for clip in m["clips"])
print(json.dumps(dict(sorted(c.items())), indent=2))
PY

# 5. Preflight (venv, model cached, manifest sha256 of every clip, GPU,
#    resolved compute type, git state, disk).
.venv/bin/python scripts/asr_experiment.py preflight
```

Exit 2 from `preflight` aborts the plan: fix the reported cause (most often
"model not cached" → `.venv/bin/stenographer model download`) and rerun. The
harness never downloads a model (`HARNESS.md` §8.2).

Write the variant files:

```sh
mkdir -p docs/experiments/variants/Q09
.venv/bin/python - <<'PY'
import json, pathlib
out = pathlib.Path("docs/experiments/variants/Q09")
cells = [("q09-base", "base", None)]
for lane, slug in (("tail", "tail"), ("tail-room", "room"),
                   ("tail-n50", "n50"), ("tail-n40", "n40")):
    for s in (1, 3, 5):
        cells.append((f"q09-{slug}-{s}s", lane, f"tail={s}s"))
for name, lane, tag in cells:
    (out / f"{name}.json").write_text(json.dumps({
        "schema": 1, "name": name, "plan": "Q09",
        "lanes": [lane], "tags_any": [], "tags_all": ([tag] if tag else []),
        "engine": "subprocess", "repeats": 1, "config": {}, "decode": {},
    }, indent=2) + "\n")
    print("wrote", out / f"{name}.json")
PY
```

Write the thresholds file (descriptive — see §6.4) and the fixed phrase list:

```sh
.venv/bin/python - <<'PY'
import json, pathlib
out = pathlib.Path("docs/experiments/variants/Q09")
(out / "thresholds.json").write_text(json.dumps({
    "schema": 1,
    "wer_mean_max_delta": 0.002,
    "rtf_p95_max_ratio": 1.25,
    "forbid_empty_regressions": False,
    "target": {"metric": "trailing_junk_rate", "direction": "higher",
               "margin": 0.10, "margin_kind": "absolute"},
    "lanes": ["base", "tail"],
    "min_clips": 100
}, indent=2) + "\n")
# Descriptive only: this file is written for the record and is never loaded.
# `decide` is never called for Q09 — base and tail clip ids do not intersect —
# and the verdict comes from §5.4. The schema carries no free-text field, so the
# explanation lives in this comment rather than in a non-schema "note" key.
(out / "tail_phrases.json").write_text(json.dumps({
    "schema": 1,
    "phrases": ["thank you", "thank you very much", "thanks for watching",
                "thank you for watching", "please subscribe",
                "and more and more", "bye bye", "you"]
}, indent=2) + "\n")
print("wrote thresholds.json and tail_phrases.json")
PY
```

The phrase list is fixed a priori and is *configuration*, in exactly the sense
`HARNESS.md` §3 allows `initial_prompt` and `hotwords` values in a checked-in
variant file: it is a diagnostic vocabulary chosen before any decode, never
text lifted out of a hypothesis. Only **counts** of matches are ever written to
a checked-in file (§6.5).

### 5.2 Stage B — the primary matrix

```sh
V=docs/experiments/variants/Q09
.venv/bin/python scripts/asr_experiment.py run --variant $V/q09-base.json      # 1st
.venv/bin/python scripts/asr_experiment.py run --variant $V/q09-base.json      # 2nd
.venv/bin/python scripts/asr_experiment.py run --variant $V/q09-tail-1s.json
.venv/bin/python scripts/asr_experiment.py run --variant $V/q09-tail-3s.json
.venv/bin/python scripts/asr_experiment.py run --variant $V/q09-tail-5s.json
```

`--baseline` and `--thresholds` are deliberately omitted, so no `verdict.json`
is produced (`HARNESS.md` §1) and the exit code means only "the run
completed": **0** continue; **2** harness error — read the message, fix, rerun
that variant; do not proceed with a partial matrix. A non-zero *clip* exit is
recorded on the clip and the run continues (`HARNESS.md` §3.1); the summary
script (§5.4) fails the stage if any cell scored fewer than 100 clips.

Then, if `build/asr-corpus/wav/tail-room/` exists and is non-empty (Stage B'):

```sh
.venv/bin/python scripts/asr_experiment.py run --variant $V/q09-room-1s.json
.venv/bin/python scripts/asr_experiment.py run --variant $V/q09-room-3s.json
.venv/bin/python scripts/asr_experiment.py run --variant $V/q09-room-5s.json
```

### 5.3 Stage C — score Stage B (and B')

Run the summary script of §5.4. Its exit code is the stage verdict:

- **0** — at least one cell met the margin. **Stop here.** The canonical
  duration is the shortest duration that met it (§6.2); go to §5.6.
- **1** — no cell met the margin. Go to Stage D (§5.5).
- **2** — integrity failure (a cell short of 100 clips, base-cell spread above
  0.05, `trailing_junk_rate` disagreeing between `result.json` and
  `clips.jsonl`, a missing run directory). Fix and rerun the affected cell;
  never proceed past a 2.

### 5.4 The summary script

Write it under `build/` — it is a plan-local one-off, not a fourth harness
module, and nothing under `scripts/` or `src/` is created by this plan.

```sh
mkdir -p build/asr-experiments/q09
cat > build/asr-experiments/q09/summarize.py <<'PY'
# SPDX-License-Identifier: GPL-3.0-or-later
"""Q09 summary: base vs tail trailing_junk_rate by appended duration."""
from __future__ import annotations
import json, pathlib, statistics, sys

sys.path.insert(0, "scripts")
import asr_metrics as M  # noqa: E402

RUNS = pathlib.Path("build/asr-experiments")
MANIFEST = pathlib.Path("build/asr-corpus/manifest.json")
PHRASES_FILE = pathlib.Path("docs/experiments/variants/Q09/tail_phrases.json")
MARGIN = 0.10          # Q09 6.1
MAX_BASE_SPREAD = 0.05 # margin / 2, Q09 6.3
MIN_CLIPS = 100

def latest(name):
    dirs = sorted(p for p in RUNS.glob(f"*-{name}") if (p / "result.json").is_file())
    return dirs[-1] if dirs else None

def all_runs(name):
    return sorted(p for p in RUNS.glob(f"*-{name}") if (p / "result.json").is_file())

def load(run_dir):
    result = json.loads((run_dir / "result.json").read_text())
    clips = [json.loads(line) for line in
             (run_dir / "clips.jsonl").read_text().splitlines() if line.strip()]
    return result, clips

def tail_tokens(ref, hyp):
    """HARNESS.md 5.5(a): hypothesis words past the last aligned reference word."""
    last = -1
    for op, _ri, hi in M.align(ref, hyp):
        if op in ("match", "sub") and hi is not None:
            last = max(last, hi)
    return hyp[last + 1:]

def contains(seq, sub):
    n = len(sub)
    return n > 0 and any(seq[i:i + n] == sub for i in range(len(seq) - n + 1))

def cell(name, manifest_by_id, phrases):
    run_dir = latest(name)
    if run_dir is None:
        return {"variant": name, "status": "missing"}
    result, clips = load(run_dir)
    scored = [c for c in clips if c.get("error") is None and c.get("hypothesis_norm") is not None]
    junk = [c for c in scored if c.get("trailing_junk")]
    phrase_counts = {" ".join(p): 0 for p in phrases}
    matched_any = 0
    for c in scored:
        tail = tail_tokens(c["reference_norm"].split(), c["hypothesis_norm"].split())
        hit = False
        for p in phrases:
            if contains(tail, p):
                phrase_counts[" ".join(p)] += 1
                hit = True
        matched_any += int(hit)
    vad = [c["vad_frames"] for c in scored if c.get("vad_frames") is not None]
    return {
        "variant": name, "status": "ok", "run_id": run_dir.name,
        "lane": result["corpus"]["lanes"][0], "clips": len(clips), "scored": len(scored),
        "trailing_junk_rate": result["aggregates"]["trailing_junk_rate"],
        "trailing_junk_rate_recomputed": (len(junk) / len(scored)) if scored else None,
        "junk_clips": len(junk),
        "wer_mean": result["aggregates"]["wer_mean"],
        "empty": result["aggregates"]["empty"],
        "vad_frames_median": statistics.median(vad) if vad else None,
        "tail_len_mean": (statistics.mean(len(tail_tokens(c["reference_norm"].split(),
                                                          c["hypothesis_norm"].split()))
                                          for c in scored) if scored else None),
        "known_phrase_clips": matched_any,
        "known_phrase_counts": phrase_counts,
        "_ids": {c["clip_id"]: bool(c.get("trailing_junk")) for c in scored},
    }

def main() -> int:
    if not MANIFEST.is_file():
        print("Q09 ERROR: manifest missing", file=sys.stderr); return 2
    manifest = json.loads(MANIFEST.read_text())
    by_id = {c["id"]: c for c in manifest["clips"]}
    phrases = [M.normalize(p) for p in json.loads(PHRASES_FILE.read_text())["phrases"]]

    stage = sys.argv[1] if len(sys.argv) > 1 else "B"
    slugs = {"B": ["tail", "room"], "D": ["tail", "room", "n50", "n40"]}[stage]

    base = cell("q09-base", by_id, phrases)
    if base["status"] != "ok":
        print("Q09 ERROR: base cell missing", file=sys.stderr); return 2

    # Determinism noise: spread of trailing_junk_rate across the base runs.
    base_rates = []
    for d in all_runs("q09-base"):
        base_rates.append(json.loads((d / "result.json").read_text())
                          ["aggregates"]["trailing_junk_rate"])
    spread = (max(base_rates) - min(base_rates)) if len(base_rates) > 1 else None
    if spread is not None and spread > MAX_BASE_SPREAD:
        print(f"Q09 ERROR: base trailing_junk_rate spread {spread:.4f} > "
              f"{MAX_BASE_SPREAD} - decode is not deterministic here", file=sys.stderr)
        return 2

    cells, integrity = [base], []
    for slug in slugs:
        for s in (1, 3, 5):
            c = cell(f"q09-{slug}-{s}s", by_id, phrases)
            if c["status"] == "missing":
                continue
            c["seconds"] = float(s)
            c["source"] = slug
            cells.append(c)

    for c in cells:
        if c["scored"] < MIN_CLIPS:
            integrity.append(f"{c['variant']}: {c['scored']} scored clips < {MIN_CLIPS}")
        r, rr = c["trailing_junk_rate"], c["trailing_junk_rate_recomputed"]
        if rr is not None and abs(r - rr) > 1e-9:
            integrity.append(f"{c['variant']}: junk rate {r} != recomputed {rr}")
    if integrity:
        for line in integrity:
            print("Q09 ERROR:", line, file=sys.stderr)
        return 2

    # Paired flips against the base cell, via manifest derived_from.
    base_junk = base["_ids"]
    for c in cells[1:]:
        b = w = 0
        for cid, junk in c["_ids"].items():
            parent = by_id.get(cid, {}).get("derived_from")
            if parent is None or parent not in base_junk:
                continue
            if junk and not base_junk[parent]:
                b += 1
            elif base_junk[parent] and not junk:
                w += 1
        c["flips_clean_to_junk"] = b
        c["flips_junk_to_clean"] = w
        c["delta"] = round(c["trailing_junk_rate"] - base["trailing_junk_rate"], 6)
        c["vad_frames_delta_median"] = (
            None if c["vad_frames_median"] is None or base["vad_frames_median"] is None
            else c["vad_frames_median"] - base["vad_frames_median"])
        c["wer_delta"] = round(c["wer_mean"] - base["wer_mean"], 6)
        c["meets_margin"] = c["delta"] >= MARGIN

    # Optional cross-check against a checked-in baseline on the same corpus.
    crosscheck = "absent"
    bl = pathlib.Path("docs/experiments/baseline.json")
    if bl.is_file():
        b = json.loads(bl.read_text())
        if b.get("corpus", {}).get("manifest_sha256") == \
           json.loads((latest("q09-base") / "result.json").read_text())["corpus"]["manifest_sha256"]:
            ref = b["aggregates"]["per_lane"]["base"]["trailing_junk_rate"]
            tol = 2 * b.get("noise", {}).get("trailing_junk_rate", MAX_BASE_SPREAD)
            crosscheck = "ok" if abs(base["trailing_junk_rate"] - ref) <= tol else "MISMATCH"
        else:
            crosscheck = "different-corpus"

    winners = [c for c in cells[1:] if c["meets_margin"]]
    winners.sort(key=lambda c: (c["seconds"], c["source"] != "tail"))
    accepted = winners[0] if winners else None

    summary = {
        "schema": 1, "plan": "Q09", "stage": stage,
        "margin_absolute": MARGIN,
        "base_rate": base["trailing_junk_rate"],
        "base_run_spread": spread,
        "baseline_crosscheck": crosscheck,
        "accepted": bool(accepted),
        "canonical": None if not accepted else {
            "lane": accepted["lane"], "seconds": accepted["seconds"],
            "source": accepted["source"], "delta": accepted["delta"],
            "trailing_junk_rate": accepted["trailing_junk_rate"]},
        "cells": [{k: v for k, v in c.items() if k != "_ids"} for c in cells],
    }
    out = RUNS / "q09" / f"summary-{stage}.json"
    out.write_text(json.dumps(summary, indent=2) + "\n")

    print(f"\n| cell | lane | tail s | clips | junk rate | delta | flips +/- | "
          f"vad frames delta | wer delta | known-phrase clips |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    print(f"| q09-base | base | - | {base['scored']} | "
          f"{base['trailing_junk_rate']:.3f} | - | - | - | - | "
          f"{base['known_phrase_clips']} |")
    for c in cells[1:]:
        print(f"| {c['variant']} | {c['lane']} | {c['seconds']:.0f} | {c['scored']} | "
              f"{c['trailing_junk_rate']:.3f} | {c['delta']:+.3f} | "
              f"{c['flips_clean_to_junk']}/{c['flips_junk_to_clean']} | "
              f"{c['vad_frames_delta_median']} | {c['wer_delta']:+.4f} | "
              f"{c['known_phrase_clips']} |")
    print(f"\nbase-run spread: {spread}   baseline cross-check: {crosscheck}")
    print(f"summary written to {out}")

    if accepted:
        print(f"\nACCEPT Q09 stage {stage}: canonical tail cell = "
              f"lane {accepted['lane']}, {accepted['seconds']:.0f}s, "
              f"source {accepted['source']}; trailing_junk_rate "
              f"{base['trailing_junk_rate']:.3f} -> "
              f"{accepted['trailing_junk_rate']:.3f} "
              f"(delta {accepted['delta']:+.3f} >= margin {MARGIN:.2f} absolute)")
        return 0
    if len(cells) < 2:
        print("Q09 ERROR: no tail cell ran for this stage", file=sys.stderr)
        return 2
    best = max(cells[1:], key=lambda c: c["delta"])
    print(f"\nNO-ACCEPT Q09 stage {stage}: best delta "
          f"{best['delta']:+.3f} ({best['variant']}) < margin {MARGIN:.2f}")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
PY
.venv/bin/python build/asr-experiments/q09/summarize.py B; echo "stage B exit: $?"
```

Notes for the executing agent. `M.align` is `HARNESS.md` §5.2 and returns
`(op, ref_index, hyp_index)` with ops `match` / `sub` / `del` / `ins`;
`M.normalize` is §5.1 and returns a token list. If the implemented names or op
spellings differ, adapt the two helpers `tail_tokens` and the `phrases`
line to §5.1–§5.5's contract — do not reimplement alignment. The script reads
`clips.jsonl`, which `HARNESS.md` §4.1 designates as the only file carrying
text; it emits **counts only** and writes them under `build/`.

### 5.5 Stage D — escalation (only after Stage C returned 1)

The primary matrix failed to reproduce the symptom. Before concluding that it
does not reproduce offline, exhaust the two controlled explanations: the noise
level is too low to change anything the VAD passes through, or Gaussian noise
is spectrally wrong. Run the level sweep (the recorded lane, if it existed,
already ran in Stage B'):

```sh
V=docs/experiments/variants/Q09
for n in n50 n40; do for s in 1s 3s 5s; do
  .venv/bin/python scripts/asr_experiment.py run --variant $V/q09-$n-$s.json
done; done
.venv/bin/python build/asr-experiments/q09/summarize.py D; echo "stage D exit: $?"
```

- **0** — accept. The canonical cell now carries a noise level other than
  −60 dBFS (or the recorded source); §9 says what that changes.
- **1** — **DENY.** Go to §5.7.
- **2** — integrity failure; fix and rerun.

Optional deny-path diagnostic (**fork F4**, not part of the verdict, run only
after a Stage D `1`). It answers "is the lane inert, or is the shipped stack
already suppressing the symptom the lane creates?" by disabling the one
shipped guard aimed at exactly this failure
(`hallucination_silence_threshold`, `model.py:27,119`):

```sh
.venv/bin/python - <<'PY'
import json, pathlib
out = pathlib.Path("docs/experiments/variants/Q09")
for name, lane, tag in (("q09-probe-base", "base", None),
                        ("q09-probe-tail-5s", "tail", "tail=5s")):
    (out / f"{name}.json").write_text(json.dumps({
        "schema": 1, "name": name, "plan": "Q09",
        "lanes": [lane], "tags_any": [], "tags_all": ([tag] if tag else []),
        "engine": "inprocess", "repeats": 1, "config": {},
        "decode": {"hallucination_silence_seconds": None},
    }, indent=2) + "\n")
PY
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q09/q09-probe-base.json
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q09/q09-probe-tail-5s.json
```

Report both cells' `trailing_junk_rate` in the outcome as a **finding, never
as an accept**: a large probe delta with a null primary delta means the lane is
sound and the shipped stack already suppresses the symptom on this corpus —
which materially weakens Q07's premise and should be said so in the outcome.

### 5.6 On accept

1. The canonical duration is the **shortest** duration that met the margin
   (§6.2) — mechanical, no judgement.
2. Write the outcome record (§6.5) and append the Outcome section (§9).
3. Propose the `HARNESS.md` §2.4 edit of §9 in the same commit.
4. Downstream tail-lane plans (Q01, Q05, Q07, Q11) are **unchanged**: they keep
   running the whole `tail` lane across all three durations, with their own
   `min_clips`. The canonical duration is recorded as **information** — it says
   which duration carries the strongest signal, which is what a later plan needs
   when it wants to argue about one — not as an instruction to narrow anyone's
   `tags_all`.

### 5.7 On deny

Record the numbers (§6.5), set Status to `denied`, and state the next
diagnostic explicitly in the Outcome section, in this order:

1. **Recorded room tone**, if `tail-room` never ran because the file was
   absent. This is the highest-value remaining move and it is the one thing
   this plan cannot do by itself, because it needs a human: someone must record
   ≥ 10 s of silence at the daemon's own capture settings and drop the WAV at
   `build/asr-corpus/roomtone/roomtone.wav`. That makes it a **follow-up plan**,
   in X01's neighbourhood — not a step of this one. Q09 records the gap in the
   Outcome as a numeric fact (`roomtone: "absent"`) and stops; no step of this
   plan ever waits on a person.
2. **A `user` lane** — the owner's own dictation clips with typed references,
   the `user` lane `HARNESS.md` §2.4 already reserves. LibriSpeech is read
   19th-century prose by trained readers; short first-person dictation is a
   different distribution and may be where the symptom lives. This is X01's
   neighbourhood and is not hands-off.
3. Only then: conclude that the `tail` lane is not a usable test bed, and
   report to Q01 / Q05 / Q07 / Q11 that their target metric has no offline
   signal to reduce — those plans must then either target `base` (where the
   `pad_or_trim` zero-pad trigger still exists, §2.4) or wait for the `user`
   lane.

## 6 Metrics & accept/deny

### 6.1 Target metric and margin

| | |
|---|---|
| Metric | `trailing_junk_rate` (`HARNESS.md` §4.2, from `trailing_junk`, §5.5) |
| Direction | **higher** on the tail cell than on the base cell |
| Margin | **0.10** |
| Margin kind | absolute |
| Compared over | `q09-base` (100 clips) vs one tail cell (100 clips), paired by `derived_from` |

**Why 0.10.** Three independent constraints, and 0.10 is the smallest round
number satisfying all three.

1. *It is not sampling noise.* The 100 tail clips are derived from the same
   100 base clips, so the comparison is paired and McNemar applies. A delta of
   0.10 means at least 10 clips flipped clean→junk; the reverse flip is
   expected to be ~0, since appending tone cannot repair a hallucination that
   the clean clip already produced. Exact McNemar with `b = 10, c = 0` gives
   `p = 2 × 0.5^10 ≈ 0.002`. The script reports both flip counts so this is
   verifiable after the fact rather than assumed.
2. *It leaves the downstream plans room to measure.* `HARNESS.md` §6.1's own
   worked example declares `margin 0.03 absolute` on `trailing_junk_rate` — the
   shape Q07 and Q11 will use. A delta of ≥0.10 forces
   `trailing_junk_rate(tail) ≥ base + 0.10 ≥ 0.10`, so the lane carries at
   least 10 symptomatic clips and a downstream 0.03 margin is at most a third
   of the available signal. (The absolute floor is implied by the delta and
   needs no second criterion.)
3. *It clears this plan's measured noise.* `HARNESS.md` §7.1 requires a
   declared margin to be at least twice the recorded noise for its metric.
   Q09 measures its own (§6.3) and the script aborts unless
   `0.10 ≥ 2 × spread`.

Anything below 0.10 is a deny, including the 0.03–0.10 band: 3–9 flipped clips
is too thin a signal for a downstream experiment to move reliably. The band is
not a special case in the rule; it is a **reported** fact, and the escalation
ladder of §5.5 runs on any no-accept regardless of where in the band the best
cell landed.

### 6.2 Deciding a multi-cell matrix

Not "first accepted in matrix order" and not "best by target metric": the
canonical cell is the **shortest appended duration that meets the margin**,
ties between sources broken in favour of the canonical `tail` lane
(synthetic −60 dBFS) over a probe lane. Rationale: the shortest tail that
reproduces the symptom is the cheapest to decode for every downstream plan and
the closest to the shortest real pause the owner produces; picking the largest
delta instead would systematically select 5 s and make every downstream run
40 % slower for no extra discriminating power. The rule is implemented in
`summarize.py` as `winners.sort(key=lambda c: (c["seconds"], c["source"] !=
"tail"))` and needs no interpretation.

### 6.3 Determinism noise

`q09-base` runs twice (§4, §5.2). `spread = max − min` of its
`trailing_junk_rate` across those runs is Q09's noise figure. Greedy decoding
at `temperature=0.0` (`model.py:114`) on a fixed model, compute type and GPU is
deterministic in practice (`HARNESS.md` §8.3); the expected spread is exactly
`0.0`. `spread > 0.05` is an environment fault, not a result: the script
returns 2 and the plan stops. `spread` is recorded in the outcome either way.

### 6.4 `thresholds.json`

Shipped at `docs/experiments/variants/Q09/thresholds.json` (contents written
by §5.1) for form and to document the margin. **It is never consumed**:
`HARNESS.md` §6.2's `decide` recomputes aggregates over the intersection of
clip ids, which is empty between `base` and `tail`, and Q09's guards
(`wer_mean`, `rtf_p95`, empty regressions) are diagnostics rather than
gates (§1). `compare` is not invoked anywhere in this plan.

### 6.5 What is reported

Per cell, in `build/asr-experiments/q09/summary-<stage>.json` and in the
Markdown table on stdout — all numeric:

- `trailing_junk_rate`, `junk_clips`, `delta` vs base, `meets_margin`;
- `flips_clean_to_junk` / `flips_junk_to_clean` (paired, via `derived_from`);
- `vad_frames_median` and `vad_frames_delta_median` vs base — the direct test
  of §2.4 and risk R1: a delta near 4000 samples (250 ms × 16 kHz) means the
  VAD is discarding the tail exactly as designed and the lane is inert; a
  delta near `seconds × 16000` means the VAD is keeping the tone as speech
  (risk R2);
- `wer_mean` and `wer_delta` vs base — contamination check (R2);
- `empty`, `scored`, `clips`;
- `tail_len_mean` — mean length in words of the §5.5(a) tail;
- `known_phrase_clips` and `known_phrase_counts` — **counts only** of scored
  clips whose tail contains one of the eight fixed phrases from
  `tail_phrases.json` as a contiguous token subsequence. This is the
  diagnostic that connects the metric to the owner's actual report: a rising
  `trailing_junk_rate` whose tails are the classic Whisper filler is the
  symptom; a rising rate whose tails are unrelated words is a different
  failure and must be said so in the outcome.
- Whether `junk rate by duration` is monotonic — reported, never a criterion.

The checked-in record is
`docs/experiments/results/Q09-<run-id>.json`: a copy of
`summary-<stage>.json` with the `known_phrase_counts` map retained (counts) and
no text field of any kind. Write it on **both** outcomes — a validation
experiment's negative result is as load-bearing as its positive one.

## 7 Cost estimate

Per-clip subprocess cost from `HARNESS.md` §8.4: ≈4–5 s (interpreter and
imports ≈1 s, cold load 0.7–2.8 s, decode ≈0.6 s for a 7 s clip). Use 4.5 s.

| Stage | Clips | Wall |
|---|---|---|
| A — `fetch` (346 MB download, shared with every plan) | — | ≈10 min |
| A — lane generation, canonical + probe lanes (numpy, no decode) | — | ≈5 min |
| A — `preflight` (one cold load) | — | ≈1 min |
| B — `q09-base` ×2 | 200 | ≈15 min |
| B — `q09-tail-{1,3,5}s` | 300 | ≈23 min |
| B' — `q09-room-{1,3,5}s` (only if room tone present) | 300 | ≈23 min |
| C — `summarize.py` | — | seconds |
| D — `q09-{n50,n40}-{1,3,5}s` (only on no-accept) | 600 | ≈45 min |
| F4 — deny-path probe, in-process | 200 | ≈3 min + one load |

**Accept path (no room tone, accept in Stage B): ≈55 min.**
**Full deny path (room tone present, Stage D and the F4 probe): ≈2 h 5 min.**
Maximum decoded clips: 1600.

Disk, on top of the corpus `HARNESS.md` §8.4 already budgets (tarball 346 MB
prunable, base WAV ≈24 MB, tail ≈100 MB, cue ≈75 MB): `tail-n50` ≈100 MB,
`tail-n40` ≈100 MB, `tail-room` ≈100 MB, run directories ≈1 MB each × ≤15.
**Budget 1.5 GiB free under `build/`** — above `preflight`'s 1 GiB check
(`HARNESS.md` §8.2 step 7), which will pass but leaves little headroom if all
three probe lanes are built. Generate the probe lanes and, if Stage B accepts,
delete `build/asr-corpus/wav/tail-n50/` and `tail-n40/` — but only *after* the
outcome record is written, and note that doing so changes the manifest and
therefore requires regenerating it before any baseline is established.

## 8 Risks, confounds, invariants

**R1 — the noise is too low and the lane is inert (most likely deny cause).**
−60 dBFS Gaussian noise is ≈0.001 RMS; the Silero VAD at `threshold 0.5` will
almost certainly score it as non-speech, `collect_chunks`
(`faster_whisper/transcribe.py:891-893`) will drop it, and the encoder will
see the base clip plus 250 ms of near-silence (`vad.py:178-181`) — mel features
that a greedy decode maps to the same tokens. *Detection:*
`vad_frames_delta_median ≈ 4000` samples regardless of appended duration.
*Mitigation:* Stage D's −50 / −40 dBFS sweep and the recorded lane, run
automatically. *Residual:* if even −40 dBFS is inert, the deny is real and §5.7
names the next diagnostic.

**R2 — the noise is too high and the VAD keeps it as speech.** At −40 dBFS the
tone may cross `threshold 0.5`, the decoder is then asked to transcribe
seconds of noise, and any resulting insertions are a *different* failure from
the one the owner reports. *Detection:* `vad_frames_delta_median` approaching
`seconds × 16000`; `wer_delta` above +0.05; a rise in `empty`; and
`known_phrase_clips` **not** rising with `trailing_junk_rate`. *Rule:* a cell
that meets the margin while `wer_delta > 0.05` **must** be reported as
contaminated in the outcome and, if a lower-level cell also met the margin,
the lower-level cell wins regardless of §6.2's duration rule. Say so
explicitly in the Outcome; do not silently canonicalise a contaminated cell.

**R3 — LibriSpeech clips already end cleanly.** They are studio reads, cut at
the utterance boundary with no natural trailing room tone, so the appended
tail is the *only* tail — which is what makes the manipulation clean, but also
means the base cell is an unusually favourable control. The corpus is also
19th-century prose read by trained readers: a distribution on which Whisper is
strong and may simply be more hallucination-resistant than short first-person
dictation. This confound cannot be removed within this plan; §5.7 item 2 names
the `user` lane as its resolution, and §10 puts it out of scope.

**R4 — the zero-pad trigger is present in the control.** `pad_or_trim`
(`faster_whisper/transcribe.py:1180`) zero-pads every clip under 30 s, base
included (§2.4). Q09 therefore measures the *marginal* effect of real tail
content over a zero pad, not the presence of the trigger. A null result means
"the tail lane adds nothing over the zero pad", not "Whisper does not
hallucinate at end of audio". Both readings belong in the Outcome.

**R5 — the shipped stack may already suppress the symptom.**
`hallucination_silence_threshold=2.0` and `no_repeat_ngram_size=3` are aimed at
exactly this failure (§2.3). Q09 runs the shipped defaults by design, so a null
result is ambiguous between "the lane is inert" and "the guard works". Fork F4
(§5.5) disambiguates it in 3 minutes and its finding directly informs Q07.

**R6 — synthetic vs recorded is a two-way confound.** Gaussian noise differs
from real room tone in spectrum *and*, once native level is used (§3.1 step 3),
in level. The synthetic sweep brackets the level so the two axes can be read
apart after the fact; the outcome must name which source produced the accepted
cell and never present a `tail-room` accept as validating the synthetic lane.

**R7 — the phrase list is a hypothesis, not a measure.** Eight fixed phrases
cannot cover every filler Whisper emits, and a low `known_phrase_clips` beside
a high `trailing_junk_rate` is informative, not disqualifying. It is a
diagnostic count only; it never enters the accept rule.

**R8 — regenerating a lane invalidates a baseline.** Any change to the corpus
manifest triggers `HARNESS.md` §7.3 rule 2 (re-baseline, ≈5.5 h) and makes
`compare` refuse against an older baseline (§6.4). This is why Q09 runs before
the baseline (§3), why the level sweep lives in **separate probe lanes** rather
than regenerating `tail` in place, and why §7.1's baseline lane list excludes the
probe lanes for free. Since `HARNESS.md` §2.5 records a `lane_sha256` per lane
and §6.4 refuses on the compared lanes' digests only, a probe lane cannot
invalidate anyone else's comparison even if it were in the manifest.

### Invariants (`HARNESS.md` §9, restated)

- **No transcript text** leaves `build/`. `clips.jsonl` is the only file that
  holds hypotheses; `summarize.py` reads it and emits counts and rates only.
  `summary-*.json`, `docs/experiments/results/Q09-*.json`, the variant files,
  `tail_phrases.json`, `thresholds.json` and everything printed to stdout are
  numeric or fixed a-priori configuration. The subprocess engine's
  `stenographer.log` lands in `<run>/state/` and already carries lengths only
  (`AGENTS.md` hard rule 6).
- **No network in the ASR path.** Every variant keeps `local_files_only=True`
  (`model.py:87`); the runner sets `HF_HUB_OFFLINE=1`; the only socket this
  plan opens is `asr_corpus.py fetch`, a `scripts/` dev tool. `preflight`
  refuses rather than downloads a missing model.
- **No platform imports.** Nothing in this plan imports
  `stenographer.platform.linux`, `evdev`, `fcntl`, or any name in
  `tests/platform/test_core_isolation.py`'s `BLOCKED` tuple. `summarize.py`
  imports only `scripts/asr_metrics.py` (stdlib-only per `HARNESS.md` §1) and
  the standard library.
- **Test policy** (`AGENTS.md` hard rule 4). This plan adds no test, because it
  adds no `src/` code and no harness module. `summarize.py` is a one-off under
  `build/`; its two non-trivial helpers (`tail_tokens`, `contains`) are ten
  lines over `asr_metrics.align`, whose own worked examples are already
  seen-to-fail tests under `HARNESS.md` §5.5. Nothing is mocked anywhere.
- **Fixed behaviour stays fixed.** Every Q09 variant is `"config": {}`,
  `"decode": {}`. `DecodeOptions()` defaults are untouched; user config still
  has exactly 23 keys in 4 sections (`AGENTS.md` hard rule 9). Only fork F4
  constructs a non-default `DecodeOptions`, from `scripts/` alone, as
  `HARNESS.md` §3.2 permits, and it produces no accept.
- **Venv only**, SPDX header on the one generated `.py`, ruff-clean, line
  length 100.

## 9 Deliverables & follow-through

### On accept

No `src/` change, no `AGENTS.md` hard-rule change, no re-baseline (the plan
runs before the baseline exists, §3). The deliverables are:

1. **The canonical `tail` cell**, chosen by the mechanical rule of §6.2 — the
   shortest duration meeting the margin, preferring the canonical lane over a
   probe lane on a tie. Recorded as `summary.canonical` in
   `docs/experiments/results/Q09-<run-id>.json`.
2. **A `HARNESS.md` §2.4 edit** in the same commit, replacing the `tail`
   lane paragraph's silent choices with the validated ones. If the canonical
   cell came from the canonical lane, this is one added sentence:

   > Validated by `Q09` (`docs/experiments/results/Q09-<run-id>.json`):
   > `trailing_junk_rate` rises from `<base>` to `<tail>` (`+<delta>`) at
   > `<N>` s of −60 dBFS tone under the shipped defaults. Downstream tail-lane
   > plans filter with `tags_all: ["tail=<N>s"]` unless they state otherwise.

   If it came from a probe lane, the same sentence plus a change of the lane's
   **noise level** (`−60 dBFS` → the accepted level) or **source** (synthetic
   → recorded, with §3.1's file path and handling folded into §2.4). In that
   case the canonical `tail` lane must be regenerated at the accepted level
   before the baseline is established, and the probe-lane paragraph of §3 above
   moves into `HARNESS.md` §2.4 as the record of why.
3. **A `HARNESS.md` §2.5 field addition** (fork F3): `source` and, for
   recorded tone, `tone_sha256` on the `trailing_noise` augmentation object.
   Additive; no schema bump.
4. **A `docs/experiments/README.md` note** that Q09 is a prerequisite of the
   baseline rather than a peer of it (§3), correcting "run alongside step 1".
5. **An Outcome section appended to this file**, numbers only: the stage that
   accepted, the full cell table, `base_run_spread`, `baseline_crosscheck`, the
   canonical cell, the R2 contamination check, the `known_phrase_clips` counts,
   the F4 probe result if it ran, and every run id. Status → `accepted`.
6. **Notification to the tail-lane consumers.** Q01, Q05, Q07 and Q11 keep their
   existing `lanes` and `min_clips` and keep running all three tail durations;
   the canonical duration is reported to them as information only. What they may
   take from this plan is the number: a `trailing_junk_rate` margin no larger
   than a third of the validated lane's rate.

No acceptance gate in `AGENTS.md` is triggered: nothing under `src/` changes,
so there is no real-machine dictation gate to re-run before `dev` → `main`.
The commit is `chore:` or `docs:`, conventional, no attribution trailers
(`AGENTS.md` hard rule 10).

### On deny

1. Copy `build/asr-experiments/q09/summary-D.json` to
   `docs/experiments/results/Q09-<run-id>.json` — numbers only.
2. Append the Outcome section with the same contents as above plus the best
   observed delta and its cell, the `vad_frames_delta_median` column (which
   distinguishes R1 from R2 mechanically), and the F4 probe finding.
3. Set Status to `denied`.
4. State the next diagnostic verbatim from §5.7, including — when it is item 1
   — the one-line request the owner must satisfy: *record ≥ 10 s of silence at
   the daemon's own capture settings and save it as
   `build/asr-corpus/roomtone/roomtone.wav`, then rerun §5.1 step 3, Stage B'
   and Stage C.*
5. Notify Q01, Q05, Q07 and Q11 that the `tail` lane carries no measurable
   signal, and that their plans must retarget `base` (where the zero-pad
   trigger of R4 still exists) or wait for a `user` lane.

## 10 Out of scope

- **Fixing the symptom.** Q09 only establishes that it exists and is
  measurable. `temperature` fallback is Q01; `repetition_penalty` and
  `no_repeat_ngram_size` are Q05; `hallucination_silence_threshold` is Q07; a
  post-decode terminal-n-gram filter is Q11. Q09 proposes no default change
  and no `DecodeOptions` change (fork F4 excepted, and it produces a finding,
  not an accept).
- **The `cue` lane and first-word loss.** Q10, with its own VAD interplay.
- **VAD parameter tuning.** Q02, on the `cue` lane and the quiet-speech
  `vad_frames=0` drop. Q09 *reports* `vad_frames` deltas but changes nothing.
- **WER, latency, empties as objectives.** They appear only as contamination
  diagnostics (R2). `rtf`, `load_ms` and `first_response_ms` are not read at
  all; the S-series owns speed.
- **A user-recorded corpus.** The `user` lane `HARNESS.md` §2.4 reserves is
  the deny path's item 2 and is not hands-off; X01 is the neighbouring plan
  that needs the owner's live microphone.
- **Whether the daemon should trim trailing silence before decode.** That is a
  `src/` change to the capture or pipeline boundary, not a decode experiment;
  no plan in the current index owns it, and Q09's result is the evidence that
  would justify opening one.
- **Trailing silence longer than 5 s.** `audio.max_recording_seconds` is 600
  and a latched `hybrid` recording can run far longer, but a tail beyond 5 s
  exceeds the 30 s encoder window's usable pad for most clips and turns the
  measurement into a window-boundary experiment instead.
