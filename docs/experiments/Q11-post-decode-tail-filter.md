# Q11 — post-decode tail filter

Status: planned (2026-08-29)

## 1 Hypothesis

A pure post-decode filter that drops the trailing words of an utterance whose
per-word probability falls below `tail_min_prob` — optionally combined with a
whole-final-segment blocklist of fixed junk phrases — reduces
`trailing_junk_rate` on the `tail` lane by ≥ 0.03 absolute without moving
`wer_mean` by more than +0.002, without moving `leading_word_recall_mean` by
more than −0.005 on either the `base` or the `tail` lane, without raising
`trailing_junk_rate` on the `base` lane by more than +0.01, without lowering
`tail_word_recall_mean` on the purpose-built control corpus by more than
−0.01, and without moving `rtf_p95` by more than ×1.25.

The plan is falsified for a variant if any one of those fails.

## 2 Symptom & mechanism

**Symptom** (README.md, symptom 2): some utterances end in hallucinated loops
— a terminal "thank you", "and more and more". `HARNESS.md` §5.5 makes this
measurable as `trailing_junk`: either ≥ 2 hypothesis words past the last
aligned reference word, or a terminal n-gram repeated three times that the
reference does not itself repeat.

**Why nothing in the current stack removes it.** Five gates exist and each is
structurally blind to a *word-level* tail:

- `temperature=0.0` is a scalar (`src/stenographer/transcribe/model.py:114`),
  so faster-whisper wraps it into a one-element ladder and never falls back;
  `compression_ratio_threshold` and `log_prob_threshold` are only consulted to
  decide whether to *retry at a higher temperature*
  (`.venv/lib/python3.14/site-packages/faster_whisper/transcribe.py`, the
  fallback loop around `generate_with_fallback`). With one temperature they
  cannot discard anything. This is Q01's subject; the finding is taken as
  verified here.
- `no_speech_threshold` is applied per decoder *pass* and again per segment in
  `_assemble` (`model.py:215`) against `seg.no_speech_prob`. A confidently
  decoded hallucination has a low `no_speech_prob` — it is not silence to the
  model, it is text. Q06's subject.
- `hallucination_silence_threshold=2.0` (`model.py:27,119`) is computed on the
  audio *after* the VAD pre-filter has removed silence, so a trailing gap long
  enough to trigger it has usually already been cut. Q07's subject.
- `no_repeat_ngram_size=3` (`model.py:115`) suppresses exact 3-gram repeats
  inside one generation, not a short two-word coda.
- `_validate_output` (`model.py:178-204`) is a density/timestamp sanity check
  with an 8-words-per-VAD-second ceiling; a two-word tail never approaches it.

**Why a word-probability tail filter should act on it.** `word_timestamps=True`
is already set (`model.py:124`) and each word already arrives with a
probability, captured into `WordInfo.probability` (`model.py:44-49,132-135`)
and then discarded: nothing downstream reads it. `_assemble` (`model.py:207`)
joins segment text and returns. A filter placed there is the only mechanism in
the stack that can act *per word* on the decoded tail, and it costs no decode
work — the probabilities are already in hand.

The blocklist half addresses the complementary failure: the classic
subtitle-corpus hallucination ("thank you", "thanks for watching") is often
decoded with *high* word probability, because the model has seen it end
thousands of training clips. Probability cannot see it; an exact whole-segment
string match can.

**What consumes the result.** `TranscriptionResult.text` (`model.py:216,226`)
→ `transcript_text` (`src/stenographer/transcribe/pipeline.py:148-157`) →
`format_transcript` (`src/stenographer/transcribe/format.py:29`), which
re-normalizes all whitespace. So a filter that rebuilds segment text from the
surviving word tokens cannot produce spacing artefacts.

## 3 Prerequisites

### 3.1 Harness pieces that must already exist

`scripts/asr_corpus.py`, `scripts/asr_metrics.py`, `scripts/asr_experiment.py`
with `preflight` / `baseline` / `run` / `compare` (HARNESS.md §1), the
`DecodeOptions` seam (HARNESS.md §3.2), `docs/experiments/baseline.json` with its `noise`
block for `trailing_junk_rate`, `leading_word_recall_mean` and `wer_mean`, and
the `base` and `tail` lanes (Q09).

### 3.2 Fork P1 — `DecodeOptions` has no tail-filter fields (blocking)

Checked against HARNESS.md §3.2: the dataclass has no tail-filter field. Four
must be added, defaulting to today's behaviour (both rules **off**), so the
shipped stack is byte-identical until this plan is accepted:

```python
    # post-decode tail filter, Q11; both rules off by default
    tail_filter_min_prob: float | None = None   # None → probability rule off
    tail_filter_max_words: int = 6              # cap on words the rule may drop
    tail_filter_min_words: int = 2              # shorter tails are never dropped
    tail_filter_blocklist: bool = False         # whole-final-segment rule off
```

The HARNESS.md §3.2 pinning test (`dataclasses.asdict(DecodeOptions())` equals
a literal dict) gains these four entries in the same commit.

`validate_variant` gains two rules: `tail_filter_min_prob` must be `null` or in
`(0.0, 1.0)`; `tail_filter_max_words` and `tail_filter_min_words` must be
integers ≥ 1 with `max_words >= min_words`.

**Recommendation:** implement exactly these four fields. Do not add a
`tail_filter_blocklist_words` field: the list stays fixed in code (§8.1).

A **code-fixed, checked-in phrase vocabulary is acceptable** — it is an a-priori
configuration artefact in exactly the sense `asr.initial_prompt` and
`asr.hotwords` already are, and Q09's `tail_phrases.json` is the same kind of
thing. What is not acceptable is a *variant field*: that would let arbitrary
phrases into `docs/experiments/variants/`, where HARNESS.md §9's no-text rule
applies. The boundary is which file the phrases live in, not the phrases
themselves.

### 3.3 Fork P2 — a `tail_word_recall` metric does not exist (blocking)

`scripts/asr_metrics.py` has `leading_word_recall` (HARNESS.md §5.4) and no
mirror. Add:

```
tail_word_recall(ref, hyp, k=3) -> float
```

Over the **last** `min(k, len(ref))` reference words, the fraction whose op in
`align` is `match`. `1.0` when the reference is empty. Aggregate key
`tail_word_recall_mean` in HARNESS.md §4.2, plus per-clip `tail_word_recall`.

Worked examples (each a seen-to-fail test in `tests/test_asr_metrics.py`):

| ref | hyp | expected |
|---|---|---|
| `see you tomorrow` | `see you tomorrow` | `1.0` |
| `see you tomorrow` | `see you` | `2/3 = 0.6667` |
| `see you tomorrow` | `see you tomorrer` | `0.6667` (sub, not match) |
| `see you tomorrow` | `see you tomorrow thank you` | `1.0` (a tail insertion does not reduce recall) |
| `see you tomorrow` | `` | `0.0` |
| `` | `anything` | `1.0` |
| `ok` | `ok` | `1.0` (k clamps to len(ref)) |

This is **additive**: it touches no existing metric, so HARNESS.md §7.3(3)
does not fire and `docs/experiments/baseline.json` is **not** re-generated.
The key is simply absent from the existing baseline, which is fine because the
guard that uses it is evaluated only on the new control corpus (§3.5), whose
baseline is generated after the metric exists. `decide` must therefore treat a
guard whose metric is missing on either side as a **harness error (exit 2)**,
never as a pass.

### 3.4 Fork P3 — non-inferiority in `thresholds.json` (settled)

HARNESS.md §6.2 rule 2 requires the target metric to *improve* by its margin.
Three of this plan's five guards are "must not get worse", and one whole run
(the control corpus) has no metric it expects to improve. **The additive
extension below is now HARNESS.md §6.1**, so this section records the reasoning
rather than proposing a change:

- `"target": null` is legal and means "guards only": rule 2 is skipped.
- Optional `"guards": []`, each entry
  `{"metric": "<aggregate key>", "direction": "lower"|"higher",
    "lane": "<optional per_lane key>", "margin_kind": "absolute"|"relative"}`
  plus **exactly one** of `max_regression`, `max_absolute`, `min_improvement`.
  A `max_regression` guard passes iff the run value is no worse than the
  baseline value by more than that (`absolute`: baseline ± max_regression;
  `relative`: baseline × (1 ± max_regression)). This is literally rule 1
  generalised, so rule 1 is implemented as a built-in guard and
  `wer_mean_max_delta` / `rtf_p95_max_ratio` stay as sugar for it.
  `max_absolute` bounds the run value alone, without consulting the baseline —
  which is what this plan's control-corpus guards need, since the metric they
  read does not exist in `docs/experiments/baseline.json`. `min_improvement` is
  the mirror of `max_regression` for a guard that must show a gain.
  This array is the **one** spelling in the programme.
- `Verdict` gains one row per guard with both values, and the verdict line
  prints them after the built-in guards.
- `validate_variant`'s "margin ≥ 2 × recorded noise" check applies to `target`
  only. For a guard, `max_regression` must instead be **≥ the recorded noise**
  for that metric; a `max_regression` below the noise floor is a harness error,
  because the guard would fire on run-to-run jitter.

The rejected alternatives — inventing a fake "target" for the no-harm runs, or
encoding non-inferiority as a negative `margin` — make the verdict line lie about
what was tested and collide with the noise check. This is also why S02's absolute
decode floor is spelled `min_improvement` rather than a negative
`max_regression`.

### 3.5 Fork P4 — the control corpus does not exist (blocking, and the
subtlest part of this plan)

Both halves of the filter are designed to delete text. The experiment is
worthless unless it is also run against clips whose reference **genuinely**
ends in the material the filter targets. Two control populations are needed,
because the two rules have different failure modes.

Everything below is built by a new `scripts/asr_corpus.py control` subcommand
into a **separate manifest**, `build/asr-corpus/manifest-control.json`, schema
1, same field rules as HARNESS.md §2.5, lane `control`. It is a separate
manifest on purpose: appending to the main manifest would change
`corpus.manifest_sha256` and force a 3 h re-baseline (HARNESS.md §7.3(2)) for
no benefit. `asr_experiment.py` gains `--manifest <path>` (default
`build/asr-corpus/manifest.json`) so a run can target it; `compare` continues
to refuse a manifest-sha mismatch, which now correctly separates the two
corpora.

**Population A — genuine blocklist endings (`control=blocklist`).** Built from
the *whole* of LibriSpeech `test-clean` (2620 utterances), not the 100-clip
subset, by scanning every `<speaker>-<chapter>.trans.txt`:

1. **Tier A1 — exact.** References whose normalized text *equals* a blocklist
   phrase (§8.1's list). These are the only clips that directly stress the
   whole-final-segment rule.
2. **Tier A2 — suffix.** References whose normalized text *ends with* a
   blocklist phrase but is longer. Included as `derived_from`-style
   concatenations: `base clip` + 250 ms of −60 dBFS noise (seed
   `zlib.crc32(donor_id)`) + `donor clip`, reference
   `ref(base) + " " + ref(donor)`, where `base` is drawn from the main
   subset's `short` stratum in sorted order and each donor is used once. This
   yields a clip whose genuine last words are a blocklist phrase, sitting
   after ordinary speech — the shape a real dictated "…and that's it, thank
   you" has.
3. Take up to 40 clips, A1 first then A2, both in lexicographic id order (no
   randomness needed; the population is small).
4. Duration bound: the concatenation must stay ≤ 35 s (HARNESS.md §2.2); skip
   pairs that would exceed it.

**Fork P4a — if Tier A1 is empty.** LibriSpeech is 19th-century audiobook
prose; a whole utterance whose entire text is "THANK YOU" may not exist, and
phrases like "thanks for watching" certainly do not. The `control` subcommand
must therefore write, into `manifest-control.json`, a numeric
`blocklist_coverage` block: `{"<phrase>": {"a1": n, "a2": n}}` for every
blocklist phrase. Then:

- If **every** phrase has `a1 == 0`, the blocklist arm has no clip that can
  make the whole-final-segment rule fire on genuine speech, so a green control
  run proves nothing about it. In that case the executing agent **must deny
  the `blocklist` and `both-*` variants regardless of their numbers**, record
  the reason in §9's "On deny" section, and let the probability-only variants
  stand or fall on their own. Do not "accept an untested rule because the
  numbers looked fine" — that is the exact failure mode this plan exists to
  avoid.
- Options considered for manufacturing A1 clips, with recommendations:
  - *(rejected)* text-to-speech synthesis — a new dependency and a network
    fetch, and synthetic speech has no bearing on the probabilities a real
    microphone produces.
  - *(rejected)* hand-recording — needs a human; the programme is hands-off
    except X01.
  - *(fork, use only if Tier A1 is empty and the owner later wants the
    blocklist arm resolved)* **word-timestamp excision**: decode a Tier A2
    donor once in-process at temperature 0, take the word timestamps for the
    trailing blocklist phrase, cut the donor's audio at
    `[first_word.start - 0.15 s, last_word.end + 0.15 s]`, and use that
    fragment as an A1 clip with the phrase as its reference. It is
    deterministic and hands-off, but it uses the model under test to build its
    own control, so a clip whose phrase the model mis-times is silently
    mislabelled. **Recommendation: do not do this inside Q11.** Record the
    zero-coverage fact, deny the blocklist arm, and raise it as an X-series
    item needing owner-recorded audio.

**Population B — genuinely soft real tails (`control=lowprob`).** The clips a
probability threshold would eat are exactly those the model gets *right* but
with low confidence at the end. Build them numerically, with no human
judgement:

1. Run `asr_experiment.py tailprobe --lanes base --manifest <main>` — a new
   read-only in-process subcommand that decodes the `base` lane once at
   shipped defaults and writes, per clip, only numbers: the mean probability
   of the final `min(6, n)` words, the minimum probability among them, and the
   existing per-clip scores. No text leaves `build/`.
2. Select the clips satisfying **all** of: `wer == 0.0`,
   `trailing_junk == false`, `leading_word_recall == 1.0`, `empty == false` —
   i.e. clips the shipped stack transcribes perfectly — and rank them by the
   mean final-word probability ascending. Take the lowest 30.
3. Those 30 base clips are copied into the control manifest with tag
   `control=lowprob`. Their WAV bytes are unchanged, so their sha256 rows are
   copied verbatim.

If fewer than 20 clips satisfy step 2, widen step 2 to `wer <= 0.05` and
re-rank; if still fewer than 20, that is a harness error (exit 2) — the base
lane is not behaving as the baseline says it does.

**Control baseline.** `manifest-control.json` needs its own baseline:

```sh
.venv/bin/python scripts/asr_experiment.py baseline \
  --manifest build/asr-corpus/manifest-control.json \
  --lanes control --engine inprocess --repeats 3 \
  --out docs/experiments/control-baseline.json
```

Deviation from HARNESS.md §7.1, deliberate and recorded here: the control
baseline uses the **in-process** engine, because every Q11 run against it is
in-process (a non-empty `decode` block forces it) and HARNESS.md §6.4 only
refuses cross-engine comparison for *speed* targets. Both sides are in-process,
so every comparison is like-for-like. `repeats: 3` still produces the `noise`
block P3's guard check needs.

### 3.6 Fork P5 — per-clip drop counts (blocking, small)

`TranscriptionResult` gains two numeric fields, defaulting to 0:

```python
    tail_dropped_words: int = 0
    tail_dropped_segments: int = 0
```

The in-process engine reads them straight off the object it already has
(HARNESS.md §3.1) and writes them into the per-clip record (§4.1); `aggregate`
gains two descriptive, **non-gating** keys: `tail_drop_rate` (fraction of
scored clips with `tail_dropped_words + tail_dropped_segments > 0`) and
`tail_dropped_words_mean`. They are reported in `report.md` so a denied run
still says whether the filter ever fired — a variant that never fires and a
variant that fires and hurts are different findings. The subprocess engine
leaves both `null`; this plan never uses it.

## 4 Variant matrix

The change under test is one pure function with two independently
switchable rules; §4.1–§4.4 specify it exactly enough to write its tests
first, and §4.5 is the matrix of parameter settings the runs compare.

### 4.1 The filter under test

Pure, total, no I/O, no logging, in `src/stenographer/transcribe/model.py`
beside `_assemble`. Written here precisely enough to become tests before it
becomes code.

```python
@dataclass(frozen=True)
class TailFilterResult:
    segments: list[SegmentInfo]
    dropped_segments: int
    dropped_words: int
    rule: str            # "" | "blocklist" | "probability" | "blocklist+probability"


def filter_tail(
    segments: list[SegmentInfo],
    *,
    min_prob: float | None,
    max_words: int,
    min_words: int,
    blocklist: tuple[str, ...],
) -> TailFilterResult:
    ...
```

### 4.2 Rule order and the two rules

Both rules fire **at most once each**, in this order, on a single pass. There
is no iteration, so the filter cannot cascade and eat a transcript.

**Rule 1 — blocklist (whole final segment).** Skipped when `blocklist` is
empty.

1. Requires `len(segments) >= 2`. The only segment is never dropped.
2. `_normalize_tail_text(segments[-1].text)`: NFKC, `casefold()`, map
   `’ ‘ ‛ ′` → `'`, delete every character outside `[a-z0-9' ]`, collapse
   whitespace, strip. (A tiny local copy of the harness's normalizer's first
   steps. `scripts/` and `src/` do not import each other.)
3. Drop the final segment iff the normalized text is **exactly equal** to a
   blocklist entry. Not "ends with", not "contains": a genuine sentence that
   merely ends in "thank you" keeps every word.
4. `dropped_segments = 1`, `dropped_words = len(segments[-1].words)`.

**Rule 2 — low-probability tail (words).** Skipped when `min_prob is None`.
Applied to whatever rule 1 left.

1. Let `W` be every word of every remaining segment, in order. If `W` is empty,
   or if any remaining segment has a non-empty `text` but an empty `words`
   list, the rule is **skipped entirely** — there are no probabilities to
   judge, and a partial judgement is worse than none.
2. Walk backwards from the end while `w.probability < min_prob`, stopping at
   `max_words` words. Call the collected suffix `S`.
3. If `len(S) < min_words`: no drop. A single soft final word is left alone —
   this is the guard that protects a trailing-off dictation, and it is also
   what aligns the filter with `trailing_junk`'s own ≥ 2-word definition
   (HARNESS.md §5.5a).
4. If `len(S) == len(W)`: no drop. The filter never empties a non-empty
   transcript.
5. Otherwise drop those `len(S)` words: for each affected segment, keep the
   words not in `S` and rebuild `text` as `"".join(w.word for w in kept)`;
   drop the segment entirely when its word list becomes empty. `start`/`end`
   are narrowed to the surviving words' extremes (or left as-is when the
   segment is untouched).
   Rebuilding from `w.word` is safe because faster-whisper's word tokens carry
   their own leading space and `format_transcript`
   (`src/stenographer/transcribe/format.py:29`) re-normalizes whitespace
   anyway; a unit test pins that `"".join(w.word for w in seg.words).strip()
   == seg.text.strip()` for the fixtures used.
6. `dropped_words += len(S)`; `dropped_segments +=` however many segments
   emptied.

### 4.3 Where it is called

Inside `_assemble` (`model.py:207-227`), in this order — binding:

1. the existing `no_speech_prob` gate (`model.py:215`) produces `kept`;
2. `_validate_output` runs on `kept` **unchanged** — the density ceiling must
   keep measuring the raw decode, or the filter would silently make an
   existing anti-hallucination guard easier to pass;
3. `filter_tail` runs on `kept`;
4. `text` is joined from the filtered segments and stripped;
5. `TranscriptionResult` carries the filtered segments plus the two counts.

### 4.4 Worked examples (each becomes a seen-to-fail test)

Notation: `seg(text, [(word, prob), …])`. Parameters unless stated:
`min_prob=0.5, max_words=6, min_words=2, blocklist=("thank you",)`.

| # | Input segments | Expect |
|---|---|---|
| 1 | `seg("Ship the box.", [(" Ship",.98),(" the",.97),(" box.",.95)])`, `seg(" Thank you.", [(" Thank",.91),(" you.",.93)])` | blocklist fires: 1 segment, 2 words dropped, `rule="blocklist"`, text `Ship the box.` |
| 2 | same as #1 but only the second segment present | no drop (`len(segments) < 2`), `rule=""` |
| 3 | `seg("Ship the box thank you.", [...])` (one segment, phrase is a suffix) | no blocklist drop — the rule is whole-segment equality |
| 4 | `seg("Ship the box.", [(" Ship",.98),(" the",.97),(" box.",.95)])`, `seg(" and more and more", [(" and",.31),(" more",.22),(" and",.19),(" more",.18)])` | probability fires: 4 words, 1 segment, `rule="probability"` |
| 5 | as #4 with `min_prob=0.3` | drops 3 words (`" and",.31` stops the walk), segment keeps `" and"`, `dropped_segments=0` |
| 6 | `seg("Okay.", [(" Okay.",.34)])` alone | no drop (rule 2 step 4: dropping all of `W`) |
| 7 | `seg("Send it now.", [(" Send",.99),(" it",.98),(" now.",.41)])` | no drop (`len(S)=1 < min_words=2`) |
| 8 | `seg("A.", [(" A.",.99)])`, `seg(" Thank you.", [(" Thank",.12),(" you.",.14)])` with blocklist **and** prob on | blocklist fires first (1 seg, 2 words); rule 2 then sees only `[" A."]` and step 4 blocks it. `rule="blocklist"`, total 2 words |
| 9 | any segments with `words=[]` and non-empty text, `min_prob=0.5` | rule 2 skipped, `dropped_words=0` |
| 10 | `[]` | `TailFilterResult([], 0, 0, "")` — total on empty input |
| 11 | `min_prob=None, blocklist=()` | returns the input segments unchanged, identity, counts 0 |

Example 11 is the inertness test that makes the `off` variant meaningful.

### 4.5 The matrix

All variants: `plan: "Q11"`, `schema: 1`, `engine: "auto"` (resolves to
`inprocess` because `decode` is non-empty), `repeats: 1` (no temperature above
zero is in play, HARNESS.md §8.3), `config: {}`.

Each variant is run three times against three different corpora/lane sets
(§5), so each name below is one JSON file, reused across runs via `--lanes` and
`--manifest` overrides on the command line.

| # | Name | File | `decode` |
|---|---|---|---|
| 0 | `q11-off` | `docs/experiments/variants/Q11/q11-off.json` | `{"tail_filter_min_prob": null, "tail_filter_blocklist": false}` |
| 1 | `q11-prob-03` | `.../q11-prob-03.json` | `{"tail_filter_min_prob": 0.3, "tail_filter_max_words": 6, "tail_filter_min_words": 2, "tail_filter_blocklist": false}` |
| 2 | `q11-prob-05` | `.../q11-prob-05.json` | `{"tail_filter_min_prob": 0.5, "tail_filter_max_words": 6, "tail_filter_min_words": 2, "tail_filter_blocklist": false}` |
| 3 | `q11-blocklist` | `.../q11-blocklist.json` | `{"tail_filter_min_prob": null, "tail_filter_blocklist": true}` |
| 4 | `q11-both-03` | `.../q11-both-03.json` | `{"tail_filter_min_prob": 0.3, "tail_filter_max_words": 6, "tail_filter_min_words": 2, "tail_filter_blocklist": true}` |
| 5 | `q11-both-05` | `.../q11-both-05.json` | `{"tail_filter_min_prob": 0.5, "tail_filter_max_words": 6, "tail_filter_min_words": 2, "tail_filter_blocklist": true}` |

Variant 0 is the control in the experimental sense: it exercises the new seam
with both rules off and **must** come out numerically identical to the
baseline. `lanes` in each file is `["base", "tail"]`; the control-corpus runs
override it with `--lanes control`.

`tail_filter_max_words` and `tail_filter_min_words` are held fixed at 6 and 2
across the matrix. Sweeping them is deliberately out of scope (§10): with five
live variants the matrix already costs 45 minutes, and the two thresholds this
plan is about are the ones the audit named.

## 5 Procedure

Every command is run from the repo root with the repo venv. No step needs a
human. Steps 1–4 are one-time setup; step 5 is the experiment.

**1. Implement the prerequisites** (P1–P5, §3), each with its pure tests seen
to fail first, then `ruff check . && ruff format --check .` and
`.venv/bin/pytest -m "not integration"` green.

**2. Preflight.**

```sh
.venv/bin/python scripts/asr_experiment.py preflight
```

Exit 2 → stop and report; the model cache, corpus, GPU or disk is not ready.

**3. Build the control corpus.**

```sh
.venv/bin/python scripts/asr_experiment.py tailprobe \
  --lanes base --out build/asr-experiments/q11-tailprobe/
.venv/bin/python scripts/asr_corpus.py control \
  --tailprobe build/asr-experiments/q11-tailprobe/clips.jsonl \
  --out build/asr-corpus/manifest-control.json
```

Read `blocklist_coverage` from the written manifest. If every phrase has
`a1 == 0`, set the flag `BLOCKLIST_UNCONTROLLED` for step 5 (§3.5 fork P4a).
Exit 2 from either command → stop and report.

**4. Control baseline.**

```sh
.venv/bin/python scripts/asr_experiment.py baseline \
  --manifest build/asr-corpus/manifest-control.json \
  --lanes control --engine inprocess --repeats 3 \
  --out docs/experiments/control-baseline.json
```

**5. Per variant**, for each of `q11-off`, `q11-prob-03`, `q11-prob-05`,
`q11-blocklist`, `q11-both-03`, `q11-both-05`, run three comparisons:

```sh
V=q11-prob-03   # repeat for each name

# A — target run, tail lane
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q11/$V.json --lanes tail \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q11/thresholds-tail.json

# B — no-harm run, base lane
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q11/$V.json --lanes base \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q11/thresholds-base.json

# C — control corpus
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q11/$V.json \
  --manifest build/asr-corpus/manifest-control.json --lanes control \
  --baseline docs/experiments/control-baseline.json \
  --thresholds docs/experiments/variants/Q11/thresholds-control.json
```

Exit-code handling, per run:

- `2` anywhere → **stop the whole plan**, report the message; a harness error
  invalidates every later comparison.
- `q11-off`: A, B and C must all exit `0`… except that A's target
  (`trailing_junk_rate` must *improve*) cannot be met by an inert variant. So
  `q11-off` is checked differently: run only B and C for it, and additionally
  assert from `verdict.json` that every **text** metric delta on both —
  `wer_mean`, `trailing_junk_rate`, `leading_word_recall_mean`, `empty`,
  `errors` — is exactly `0.0`. Speed metrics (`decode_ms_*`, `rtf_*`,
  `load_ms_*`) are **excluded**: they vary run to run by construction and an
  inert seam is not required to reproduce them to the millisecond. A non-zero
  text delta means the seam is not inert — a harness error, stop.
- Every other variant: it is **accepted** iff A, B and C all exit `0`, and, if
  `BLOCKLIST_UNCONTROLLED` is set and the variant enables the blocklist
  (`q11-blocklist`, `q11-both-*`), it is **denied regardless** of exit codes,
  with the reason recorded.
- Deny → append the verdict line to §9's "On deny" record and continue with the next
  variant.

**6. Choose.** Among accepted variants, the winner is the one with the lowest
`trailing_junk_rate` in run A; ties broken by lower `wer_mean`, then by matrix
order (so the simpler rule wins a tie). If none is accepted, the plan's status
becomes `denied`.

**Margin adjustment rule** (keeps step 5 hands-off): before the first run, read
`noise.trailing_junk_rate` from `docs/experiments/baseline.json`. If
`2 × noise > 0.03`, the agent must raise `margin` in `thresholds-tail.json` to
`2 × noise` rounded up to the next `0.01`, and record the substitution in §9's
"On deny" record. `validate_variant` enforces the same rule, so failing to do this
produces exit 2, not a wrong accept. The same applies to every
`max_regression` in the three thresholds files: each must be ≥ the recorded
noise for its metric; raise it to the recorded noise, rounded up to the next
`0.005`, if it is not.

## 6 Metrics & accept/deny

Target: `trailing_junk_rate`, direction `lower`, margin `0.03` absolute, on
the `tail` lane (subject to the margin-adjustment rule above).

`docs/experiments/variants/Q11/thresholds-tail.json`:

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
     "max_regression": 0.005, "margin_kind": "absolute"}
  ],
  "lanes": ["tail"],
  "min_clips": 300
}
```

`docs/experiments/variants/Q11/thresholds-base.json`:

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.25,
  "forbid_empty_regressions": true,
  "target": null,
  "guards": [
    {"metric": "trailing_junk_rate", "direction": "lower",
     "max_regression": 0.01, "margin_kind": "absolute"},
    {"metric": "leading_word_recall_mean", "direction": "higher",
     "max_regression": 0.005, "margin_kind": "absolute"}
  ],
  "lanes": ["base"],
  "min_clips": 100
}
```

`docs/experiments/variants/Q11/thresholds-control.json`:

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.25,
  "forbid_empty_regressions": true,
  "target": null,
  "guards": [
    {"metric": "tail_word_recall_mean", "direction": "higher",
     "max_regression": 0.01, "margin_kind": "absolute"},
    {"metric": "deletion_rate", "direction": "lower",
     "max_regression": 0.01, "margin_kind": "absolute"}
  ],
  "lanes": ["control"],
  "min_clips": 40
}
```

Why these and not others:

- `leading_word_recall_mean` appears on both A and B because the filter must
  be provably a *tail* change; a regression there would mean a bug in the
  segment rebuild (§4.2 step 5), not a trade-off.
- `deletion_rate` on the control corpus is the direct measure of "the filter
  ate real words"; `tail_word_recall_mean` is the same fact localised to the
  last three reference words. Both, because a filter that drops a genuine
  four-word tail moves `deletion_rate` more visibly than a `k=3` recall.
- `forbid_empty_regressions` is left on and is load-bearing here: §4.2's
  never-empty guards are exactly what it audits.
- `tail_drop_rate` and `tail_dropped_words_mean` are **reported, never
  gating** — a filter that fires often and harms nothing is a good filter, and
  a threshold on how often it fires would only encode a prior.

## 7 Cost estimate

In-process throughout (HARNESS.md §8.4: ≈0.7 s per clip after one ≈2.5 s
load).

| Step | Clips | Wall |
|---|---|---|
| 3 — `tailprobe`, base lane | 100 | ≈2 min |
| 3 — control corpus build (text scan + numpy concat) | — | < 1 min |
| 4 — control baseline, 3 repeats | 3 × ≈70 | ≈4 min |
| 5A — 5 live variants × 300 tail clips | 1500 | ≈18 min |
| 5B — 6 variants × 100 base clips | 600 | ≈8 min |
| 5C — 6 variants × ≈70 control clips | 420 | ≈6 min |
| model loads, 15 runs | — | ≈1 min |
| **Total** | ≈2700 | **≈40 min** |

Plus preflight (one cold load, ≈10 s) and the implementation/test cycle for
P1–P5, which is developer time rather than machine time.

Disk: control WAVs ≈ 15 MB (30 copied base clips are referenced, not copied,
if the manifest keeps their original `wav` paths — do that; only Tier A2
concatenations are new files), 15 run directories ≈ 20 MB. Well inside the
1 GiB budget.

**No re-baseline of `docs/experiments/baseline.json` is required to run this
plan** (§3.3). One is required only if it is accepted (§9).

## 8 Risks, confounds, invariants

### 8.1 The blocklist

The fixed list, to live as `_TAIL_BLOCKLIST` in `model.py` with a comment
naming this plan. Entries are compared against the *whole* normalized final
segment:

```
"thank you"
"thank you very much"
"thanks for watching"
"thank you for watching"
"thank you for listening"
"please subscribe"
```

Deliberately excluded: bare `thanks`, `bye`, `okay`, `you`. Each is a
plausible whole final segment in real dictation, and no evidence names them as
hallucinations here.

Risks:

- **It needs maintenance**, and every addition is a text-matching rule shipped
  in the ASR path. Follow-through (§9):
  the list is fixed in code, and adding an entry is a recorded decision in
  `AGENTS.md`, not a config knob and not a user-editable file. This is why P1
  exposes only a boolean.
- **It can eat a genuine closing phrase.** Mitigated three ways: whole-segment
  equality rather than suffix matching (a real "…and that's all, thank you"
  is one segment and survives); the `len(segments) >= 2` guard; and the
  control corpus. The residual risk is a dictation that genuinely ends with a
  standalone "Thank you." as its own sentence — that *is* eaten, by design,
  and the owner must be told so in the acceptance note.
- **The control may be vacuous** (fork P4a). Handled by the mandatory denial
  rule, not by judgement.

### 8.2 The probability rule

- **Word probabilities are not calibrated confidences.** They are averaged
  token probabilities from the decoder; a threshold tuned on LibriSpeech read
  speech may sit in the wrong place for the owner's microphone, room and
  speaking rate. This is the single largest external-validity risk in the
  plan. It is *not* fixable inside the harness; it is why §9's acceptance
  gate requires real dictation in all three hotkey modes before dev → main,
  and why the accepted default should be the *more conservative* of two
  otherwise-equal thresholds.
- **Soft real words at the end of an utterance** — trailing off, a quiet last
  syllable — are exactly what `min_prob` sees. Guarded by `min_words = 2`
  (a single soft word is never dropped), by `tail_word_recall_mean` and
  `deletion_rate` on the control corpus, and by `wer_mean` on both lanes.
- **`max_words = 6`** bounds the damage of a mis-set threshold to six words in
  the worst case; without it, a low-confidence quiet utterance could be
  erased down to its first word.

### 8.3 Confounds

- The `tail` lane's junk is *induced* by 1/3/5 s of synthetic −60 dBFS room
  tone (HARNESS.md §2.4). Real trailing junk follows breath, key clicks and
  room noise with different spectra, so the effect size measured here is an
  estimate of the real one, not a measurement of it. Q09 characterises the
  lane; this plan inherits that caveat.
- **Overlap with Q01, Q05, Q07.** All four target the same symptom. If any of
  them is merged first, `docs/experiments/baseline.json` moves (README step 4
  and HARNESS.md §7.3(1)) and this plan must be re-run against the new
  baseline — its accepted margin may vanish once temperature fallback or a
  repetition penalty is doing the same work. Merge one accepted change at a
  time.
- **Segment count is model-dependent.** The blocklist rule's
  `len(segments) >= 2` precondition depends on how `medium.en` segments; a
  different model (Q12) may fold the hallucination into the final real
  segment, making the rule inert. Recorded, not guarded: `tail_drop_rate`
  makes it visible.
- **`q11-off` proves the seam is inert**, which separates "the filter helped"
  from "adding four `DecodeOptions` fields perturbed something".

### 8.4 Invariants (HARNESS.md §9, restated)

- **No transcript text** in `result.json`, `report.md`, `verdict.json`,
  stdout, `docs/experiments/control-baseline.json`, or anything under
  `docs/experiments/variants/Q11/`. Text lives only in `clips.jsonl` under
  `build/`. Note specifically: `blocklist_coverage` in the control manifest is
  a **count per phrase**, and the phrases are the fixed blocklist, which is
  code, not transcript. The control manifest's `reference` fields are corpus
  ground truth under `build/`, exactly like the main manifest's.
- **The filter never logs the words it drops.** `filter_tail` does no logging
  at all; only the two integers travel, and they surface as
  `tail_drops=<n>` on the existing summary line (§9). AGENTS.md hard rule 6:
  numeric and structural metrics only.
- **No network in the ASR path.** `local_files_only=True` (`model.py:87`)
  untouched; the in-process engine sets `HF_HUB_OFFLINE=1`; no new download.
- **No platform imports** in any harness code; add nothing to core that
  imports a provider.
- **Test policy** (AGENTS.md hard rule 4): `filter_tail`,
  `_normalize_tail_text` and `tail_word_recall` are pure and get seen-to-fail
  tests from §4.4 and §3.3. No mocking of the model, `soundfile`, or
  `subprocess`.
- **Fixed behaviour stays fixed until accepted.** `DecodeOptions()` defaults
  keep both rules off and are pinned by the §3.2 test; user config still has
  exactly 23 keys (AGENTS.md hard rule 9); nothing under `src/` constructs a
  non-default `DecodeOptions`.
- **Venv only**, SPDX header on every new file, ruff clean, line length 100.

## 9 Deliverables & follow-through

### On accept

1. **The filter ships in `src/stenographer/transcribe/model.py`**, beside
   `_assemble` (`model.py:207`): `TailFilterResult`, `filter_tail`,
   `_normalize_tail_text`, `_TAIL_BLOCKLIST`, and the call site in `_assemble`
   in the order fixed by §4.3 (gate → `_validate_output` → `filter_tail` →
   join).
2. **`DecodeOptions` defaults change** to the winning variant's values
   (`model.py`, the §3.2 dataclass), and the pinning test's literal dict is
   updated in the same commit — the two-place edit is the point.
3. **`TranscriptionResult` gains `tail_dropped_words` / `tail_dropped_segments`**
   (`model.py:61-68`), both `int = 0`. They cross the worker boundary for free:
   the child returns the `TranscriptionResult` itself
   (`src/stenographer/transcribe/worker.py:167-175`), so no protocol change.
   `WorkerTimings` (`worker.py:68-77`) is **not** touched — it is a wall-clock
   record, and these are counts.
4. **The summary line reports the counts.** Add
   `tail_drops: int | None = None` to `UtteranceRecord`
   (`src/stenographer/transcribe/pipeline.py:34-74`) and a `tail_drops` entry
   to `summary_fields` after `words`, filled from the result at
   `src/stenographer/daemon.py:655-656` and
   `src/stenographer/cli/commands/transcribe.py:82-89`. One integer
   (`dropped_words`; segments are implied and not worth a second key). The
   `fmt_event` template test that parses every template under `src/` covers
   the new key automatically.
5. **`AGENTS.md`**, same commit:
   - hard rule 5, the fixed-stack sentence (`AGENTS.md:229-231`): extend to
     "(VAD pre-filter, no-speech gate, silence trimming, short-audio token
     ceiling, output validation, **post-decode tail filter**) is fixed
     behavior, not configuration", with one clause naming what the tail filter
     does — drops a trailing run of words below a fixed probability, and a
     final segment whose whole text is a fixed junk phrase; both thresholds
     and the phrase list are code, never config.
   - the `transcribe/` architecture-map row (`AGENTS.md:355`): add
     `filter_tail` to `model.py`'s parenthetical.
   - hard rule 6 needs no change — the counts are numeric — but the
     acceptance-gate bullet for logging changes should gain "and `tail_drops`
     is a count, never a word".
6. **Re-baseline** per HARNESS.md §7.3(1): the shipped defaults moved.
   `docs/experiments/baseline.json` regenerated with the subprocess engine,
   three repeats, all seven baseline lanes (≈5.5 h, overnight), in a commit that touches
   nothing under `src/` and says why. `docs/experiments/control-baseline.json`
   is regenerated at the same time.
7. **Acceptance gates (AGENTS.md, real machine, before dev → main):**
   `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest` green; real dictation
   end-to-end in `hold`, `toggle` and `hybrid`; and the logging gate — a
   dictation leaves exactly one `pipeline: utterance` line, now carrying
   `tail_drops=`, and inspection of `stenographer.log` shows counts with no
   transcript content. Add one explicit manual check to the gate list: dictate
   a sentence that genuinely ends in a soft trailing word and one that
   genuinely ends in "thank you", and confirm both arrive intact or that the
   loss is the one §8.1 documents.
8. **Status** in this file → `accepted (<date>)` with the winning variant name
   and the three verdict lines (numbers only).

### On deny

Append an `## Outcome` section here with the verdict line and run id for every
variant, copy each `verdict.json` to
`docs/experiments/results/Q11-<run-id>.json`, set Status to `denied (<date>)`,
and record whether `BLOCKLIST_UNCONTROLLED` was set. Numbers only. Nothing
under `src/` changes; the four `DecodeOptions` fields stay, defaulting off, as
the seam a later plan can reuse — or are removed if no later plan wants them.

## 10 Out of scope

- **Terminal repeated-n-gram collapsing.** `docs/experiments/README.md`'s index
  line for Q11 describes the plan as "removes terminal repeated n-grams"; this
  plan is the probability + blocklist design the audit asked for instead.
  Repetition is Q05's subject (`repetition_penalty`, `no_repeat_ngram_size`),
  and `trailing_junk`'s condition (b) already measures it. **The README index
  line must be reworded in the commit that lands this file** — this plan may
  not silently answer a different question than the index advertises.
- **Sweeping `tail_filter_max_words` / `tail_filter_min_words`.** Fixed at 6
  and 2 (§4.5). A follow-up plan may sweep them if this one is accepted.
- **Leading-side filtering.** First-word loss is Q10 (cue bleed) and Q02 (VAD
  parameters); `leading_word_recall_mean` appears here only as a guard.
- **Exposing any of this to user config.** AGENTS.md hard rule 9: 23 keys, 4
  sections, no setup-only keys.
- **A user-editable or downloadable blocklist.** Local-only, in code, fixed.
- **Cross-segment or whole-transcript probability filtering**, mid-utterance
  low-confidence deletion, and probability calibration. This filter touches
  the tail only.
- **Any decode-parameter change.** `temperature` (Q01), `no_speech_threshold`
  (Q06), `hallucination_silence_threshold` (Q07), `beam_size` (Q03),
  `initial_prompt` (Q08) and the model choice (Q12) are all held at shipped
  defaults in every variant here (`config: {}`), so the only difference
  between variant 0 and the rest is the filter itself.
- **Real-microphone validation.** The corpus is read audiobook speech; the
  owner's acoustics are X01-shaped work and the acceptance gate above.
- **The `_assemble` no-speech gate itself.** That is Q06's subject. If Q06 has
  merged before this plan runs, step 1 of §4.3's ordering no longer exists and
  the order is `_validate_output` → `filter_tail` → join; nothing else about
  this filter changes, because it reads word probabilities and that gate never
  touched them. Q06 §10 carries the mirror of this sentence.
