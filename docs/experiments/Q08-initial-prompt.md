# Q08 — dictation-style `asr.initial_prompt`

Status: planned (2026-08-29)

Baseline for every `file:line` citation: `dev` @ `a1b9807` (v0.11.6),
faster-whisper 1.2.1, CTranslate2 4.8.1, in the repo venv. Paths into the
library are relative to
`.venv/lib/python3.14/site-packages/faster_whisper/`.

## 1 Hypothesis

Setting `asr.initial_prompt` to a short, punctuated, first-person dictation
sentence reduces `wer_mean` by ≥ 0.005 absolute on lanes `base` + `tail`
without moving `rtf_p95` by more than ×1.25, without raising
`trailing_junk_rate` by more than +0.01 or `leading_miss_rate` by more than
+0.02, and without echoing any distinctive prompt 3-gram into a single `tail`
hypothesis or into more than 1 % of `base` hypotheses.

The hypothesis is falsified by any one of those guards. It is expected to be
denied on WER (see §8, external validity); the value of running it is the
recorded number and the leak measurement, both of which settle whether the key
may ever be recommended to a user.

## 2 Symptom & mechanism

**Symptom.** From `docs/experiments/README.md`: symptom (3), "the
hallucination rate is high in general", and the general quality of dictated
output. The user-visible complaint that motivates a *prompt* specifically is
that dictated text arrives without the punctuation and casing a written note
needs; the daemon has no post-processor that can invent them.

**Mechanism, our side.** `Model.transcribe` passes
`initial_prompt=(cfg.initial_prompt or None)`
(`src/stenographer/transcribe/model.py:123`) straight through to
faster-whisper. The key exists in the schema today
(`src/stenographer/config.py:63`, read at `config.py:200`, rendered in the
annotated template at `config.py:257` as
`initial_prompt = ""  # style/domain context prepended to decoding`, and
`None` in the in-memory defaults at `config.py:311-312`). Its shipped value is
`""`, and `"" or None` is `None`, so **today no prompt is sent at all**. This
plan therefore changes no code path — it changes one configuration value that
the code already honours, which is why it is a `config`-lane experiment.

Downstream, `format_transcript`
(`src/stenographer/transcribe/format.py:29-43`) owns spacing and capitalises
the token after any of `.?!` (`format.py:19,39`) but **never inserts
punctuation**: `_NO_SPACE_BEFORE` (`format.py:18`) only decides spacing. So
every comma and every sentence-terminal mark in the delivered text comes from
the decoder, and capitalisation of the second sentence is downstream of the
decoder having emitted a period. A prompt is the only lever the shipped
configuration has on either.

**Mechanism, library side.** `initial_prompt` is tokenised once and seeded
into `all_tokens` before the window loop
(`transcribe.py:1143-1149`: `initial_prompt = " " + options.initial_prompt.strip()`,
then `all_tokens.extend(tokenizer.encode(initial_prompt))`). Each window then
takes `previous_tokens = all_tokens[prompt_reset_since:]`
(`transcribe.py:1187`) and `get_prompt` prepends them after `sot_prev`
(`transcribe.py:1542-1550`), i.e. the model sees the prompt as *previous
transcript text*. Whisper is not instruction-following here; it continues a
style. This is why §4's prompts are exemplary prose and not instructions.

Three consequences the plan depends on, each verified in the installed
library:

1. **The prompt reaches the first window only.** At the end of every window,
   `if not options.condition_on_previous_text ... prompt_reset_since =
   len(all_tokens)` (`transcribe.py:1372-1383`). We pass
   `condition_on_previous_text=False` (`model.py:121`), so from window 2
   onwards `previous_tokens` is empty and the prompt is gone. A window is 30 s
   of features, so every `short` and `medium` clip and most `long` clips
   decode entirely under the prompt; the tail of a >30 s clip does not. This
   contradicts the common assumption that `condition_on_previous_text=False`
   makes the prompt apply to every window — it does the opposite. §8 records
   it as a dilution confound for the `long` stratum (20 % of `base`).
2. **The prompt does not eat the token budget.** `max_length = len(prompt) +
   options.max_new_tokens` (`transcribe.py:1416-1419`), so our
   `_token_budget(...)` allowance (`model.py:26,28,29` and the call at
   `model.py:120`) stays intact when the prompt grows. A prompt therefore
   cannot cause truncation, and a WER change cannot be blamed on it.
3. **The prompt is not truncated.** `previous_tokens[-(self.max_length // 2 - 1):]`
   (`transcribe.py:1550`) keeps the last 223 tokens; §4's longest prompt is
   ≈50 BPE tokens.

**Why it could hurt.** The same seeding makes the prompt a hallucination
vector: on audio with little or no speech, a decoder conditioned on prompt
text can continue that text instead of transcribing. That is the exact failure
this plan must be able to detect, and it is why the `tail` lane and the
prompt-leak guard are non-negotiable parts of the design rather than extras.

## 3 Prerequisites

**Harness pieces.** `scripts/asr_corpus.py`, `scripts/asr_metrics.py`,
`scripts/asr_experiment.py` (`preflight`, `run`, `compare`) per
`HARNESS.md` §1, with their pure tests green.

**Corpus lanes.** `base` (100 clips) and `tail` (300 clips). The `tail` lane is
produced and characterised by **Q09**; Q08 must not start before Q09 has run
and the tail lane exists in `build/asr-corpus/manifest.json`.

**Baseline.** `docs/experiments/baseline.json` present, covering `base`,
`tail` and `cue`, with a `noise` block carrying `wer_mean` and
`trailing_junk_rate` (`HARNESS.md` §7.1).

**Injection fields.** Config only: `asr.initial_prompt`. **No `DecodeOptions`
field is used and none may be added** — the whole point of Q08 is that the
lever is already in user configuration.

**Harness additions Q08 requires.** These are additive, general, and land in
Q08's own implementation commit together with the matching `HARNESS.md` edits
and seen-to-fail tests (`AGENTS.md` hard rule 4). None of them changes an
existing metric definition, so **no re-baseline is triggered**
(`HARNESS.md` §7.3 rule 3 covers changed definitions, not new ones); every new
guard that could not be evaluated against the existing baseline is defined as
run-absolute rather than baseline-relative, precisely so the checked-in
baseline stays usable.

1. `scripts/asr_metrics.py` gains four pure functions — `ngrams`,
   `corpus_ngrams`, `effective_prompt_ngrams`, `prompt_leak` (§6.1) — and
   `punctuation_stats` (§6.2). Stdlib only, no I/O, per `HARNESS.md` §1.
2. The per-clip record (`HARNESS.md` §4.1) gains the numeric fields
   `prompt_leak` (bool), `prompt_leak_ngrams` (int), `punct_terminal_runs`
   (int), `punct_commas` (int), `punct_words` (int). All are numbers, so all
   are also carried into `clip_scores` in `result.json`. The leaked n-grams
   themselves are written **only** to `clips.jsonl` under `build/`, never to
   `result.json`, `report.md`, `verdict.json` or stdout.
3. `aggregate` (`HARNESS.md` §4.2) gains `prompt_leak_rate` (fraction of
   scored clips with `prompt_leak == true`), `terminal_runs_per_100w` and
   `commas_per_100w` (§6.2), in the run-wide block and in `per_lane`.
4. `result.json` gains `prompt_ngrams_total` and `prompt_ngrams_effective`
   (§6.1) under a new top-level `prompt` object, alongside `prompt_tokens`
   (the count of normalized prompt tokens). The prompt string itself is
   already in `variant.config.asr.initial_prompt`, which `HARNESS.md` §3
   explicitly permits as configuration.
5. The runner computes `prompt_norm = normalize(variant.config.asr.initial_prompt or "")`
   once per run, and the corpus n-gram pool once per run over the normalized
   references of every clip it will score. Both are inputs to the pure
   scorer; neither needs the model.
6. `decide` (`HARNESS.md` §6.2) reads the optional `guards` array in
   `thresholds.json` — the canonical mechanism, specified in `HARNESS.md` §6.1
   and restated for this plan in §6.4 — and reports each entry in `Verdict` and
   in the report table. `decide` stays pure. Q08 adds no new threshold
   vocabulary of its own; if the foundation commit has not landed `guards`, the
   fallback is a plan-local check script over `result.json` and the guard rows
   move into `thresholds.json` on the next pass.
7. `preflight` (`HARNESS.md` §8.2) gains step 8: when the variant sets a
   non-empty `initial_prompt`, compute `prompt_ngrams_effective /
   prompt_ngrams_total` and **exit 2** if it is below `0.5` — a prompt more
   than half of whose 3-grams already occur in the corpus references cannot
   be used as a leak probe (§6.1, blind spot).

## 4 Variant matrix

Three variants, one repeat each, engine `auto` — which resolves to
`subprocess` because `decode` is empty (`HARNESS.md` §3), and subprocess is
also the faithful engine here: the deliverable is a *configuration*
recommendation, so the run should exercise `Config.load` →
`AsrConfig.initial_prompt` → `model.py:123` exactly as a user's daemon would.

| # | Name | `asr.initial_prompt` | Lanes | Engine | Repeats | Variant file |
|---|---|---|---|---|---|---|
| 0 | `q08-control` | `""` (explicit empty; identical to today's default, `"" or None` → `None`) | `base`, `tail` | `auto` → subprocess | 1 | `docs/experiments/variants/Q08/q08-control.json` |
| 1 | `q08-prompt-short` | prompt **A** below | `base`, `tail` | `auto` → subprocess | 1 | `docs/experiments/variants/Q08/q08-prompt-short.json` |
| 2 | `q08-prompt-long` | prompt **B** below | `base`, `tail` | `auto` → subprocess | 1 | `docs/experiments/variants/Q08/q08-prompt-long.json` |

### 4.1 The prompt strings, verbatim

**Prompt A** (one sentence, 22 normalized words, two commas, one terminal
period):

```
I made a few notes about the meeting, and I want to write them out properly, so I can send them today.
```

**Prompt B** (two sentences, 41 normalized words, three commas, two terminal
periods; a strict superset of A):

```
I made a few notes about the meeting, and I want to write them out properly, so I can send them today. Let me know what you think when you have read it, and we can talk about the rest tomorrow.
```

### 4.2 Why exactly these strings

- **Exemplary, not instructional.** `get_prompt` splices the prompt in after
  `sot_prev` as previous transcript text (`transcribe.py:1542-1550`); Whisper
  continues a register, it does not obey a request. An instruction
  ("transcribe with punctuation") is out-of-distribution as speech, which both
  weakens the style transfer and raises the odds of it being echoed verbatim.
  Both strings read as ordinary dictated prose.
- **Carries exactly the punctuation the formatter cannot invent.** Commas
  (which `format.py` only spaces, never inserts, `format.py:18`) and
  sentence-terminal periods (which are also what drives downstream
  capitalisation, `format.py:19,39`). B adds a second sentence so that a
  sentence *boundary* is demonstrated and not just a terminating one.
- **Register of dictation.** First person, present tense, conversational, a
  note-to-self about ordinary work. This is the register the daemon serves.
  It is deliberately *not* the register of the corpus, which is 19th-century
  read narrative prose — see §8, this is the plan's principal external-validity
  limitation and it is stated, not hidden.
- **No rare words, no proper nouns, no numbers.** Every token is high-frequency
  English. Rare words would be conspicuous if echoed, would bias vocabulary
  toward a domain the corpus does not contain, and (for numbers) would
  interact with `normalize`'s spoken-number folding (`HARNESS.md` §5.1 step 6).
- **No discourse opener.** Neither string starts with a greeting, "Yes", "So",
  "Okay" or similar, because an opener biases the *first* words of a transcript
  and would confound `leading_word_recall`, a metric another plan (Q02/Q10)
  owns.
- **Content words are spread through the string**, so most of its 3-grams
  carry at least one content word and survive the corpus-collision filter of
  §6.1. Purely functional 3-grams such as `(i, want, to)` will be filtered out
  automatically if the corpus references contain them; §3 item 7 refuses the
  run if too many are.
- **B ⊃ A.** Length is the only dimension that varies between the two prompt
  variants, so "does more prompt help or hurt" is answered without any second
  confound. The concatenation also produces two cross-sentence 3-grams
  (`(them, today, let)`, `(today, let, me)`) which exist only in B — a leak of
  those is unambiguous evidence that the model continued past the prompt's
  first sentence.

### 4.3 Variant JSON (checked in verbatim)

`docs/experiments/variants/Q08/q08-control.json`:

```json
{
  "schema": 1,
  "name": "q08-control",
  "plan": "Q08",
  "lanes": ["base", "tail"],
  "tags_any": [],
  "tags_all": [],
  "engine": "auto",
  "repeats": 1,
  "config": {"asr": {"initial_prompt": ""}},
  "decode": {}
}
```

`q08-prompt-short.json` and `q08-prompt-long.json` are identical but for
`name` and the `initial_prompt` value, which is prompt A and prompt B
respectively, copied byte-for-byte from §4.1.

## 5 Procedure

Every command runs from the repository root with the repo venv
(`AGENTS.md` hard rule 1). No step requires a human.

**Step 1 — preflight.**

```sh
.venv/bin/python scripts/asr_experiment.py preflight
```

Exit 2 → stop; fix the reported cause (model not cached → run
`.venv/bin/stenographer model download`; corpus missing or a lane absent →
run `scripts/asr_corpus.py` per `HARNESS.md` §2 and, for the `tail` lane,
Q09) and repeat. Do not proceed on exit 2.

**Step 2 — resolve the margin from the baseline's noise block.**

```sh
.venv/bin/python - <<'PY'
import json, math, pathlib
b = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
n = b["noise"]["wer_mean"]
print("noise.wer_mean =", n, " required margin >=", 2 * n)
PY
```

The checked-in `thresholds.json` (§6.4) declares
`target.margin = 0.005`. If `2 × noise.wer_mean > 0.005`, edit
`docs/experiments/variants/Q08/thresholds.json` and set
`target.margin` to `ceil(2 × noise.wer_mean × 1000) / 1000` (three decimals,
rounded up), then record the edited value in this file's Outcome section.
`validate_variant` enforces the same rule and returns exit 2 if the margin is
still too small, so a mistake here fails loudly rather than silently.

**Step 3 — the control run.**

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q08/q08-control.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q08/thresholds.json
```

(If the implemented CLI takes the variant path positionally rather than under
`--variant`, use that form; everything else is unchanged.)

The control's own verdict is meaningless — it cannot improve on a baseline it
is identical to — and is expected to be exit 1. **Ignore the control's exit
code** and instead run the drift check:

```sh
.venv/bin/python - <<'PY'
import json, pathlib, glob
b = json.loads(pathlib.Path("docs/experiments/baseline.json").read_text())
run = json.loads(sorted(glob.glob("build/asr-experiments/*-q08-control/result.json"))[-1])
noise = b["noise"]["wer_mean"]
d = abs(run["aggregates"]["wer_mean"] - b["aggregates"]["wer_mean"])
print(f"control drift {d:.4f} vs allowance {2 * noise:.4f}")
raise SystemExit(0 if d <= 2 * noise else 3)
PY
```

Exit 3 → **stop the plan.** The machine, the library stack or the corpus has
drifted from the baseline and no Q08 verdict would mean anything. Record the
two numbers in the Outcome section, set Status to abandoned, and hand the
drift to a re-baseline decision (`HARNESS.md` §7.3 rule 4). Exit 0 → continue.
Keep the control run directory: it supplies the punctuation-density reference
numbers that `baseline.json` predates.

**Step 4 — the two prompt runs, in matrix order.**

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q08/q08-prompt-short.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q08/thresholds.json

.venv/bin/python scripts/asr_experiment.py run \
  --variant docs/experiments/variants/Q08/q08-prompt-long.json \
  --baseline docs/experiments/baseline.json \
  --thresholds docs/experiments/variants/Q08/thresholds.json
```

Per run: exit `0` accept, `1` deny, `2` harness error. Exit 2 → stop, fix the
harness cause, re-run that variant; a preflight refusal for a too-generic
prompt (§3 item 7) is a design failure of the prompt, not of the run: record
`prompt_ngrams_effective / prompt_ngrams_total` in the Outcome and close the
plan as denied rather than inventing a new prompt string, because changing the
probe after seeing the corpus is not a fair test. **Run both variants even if
the first accepts** — the comparison between them is part of the deliverable.

**Step 5 — decide.** Apply §6.5. Then write the Outcome section per §9 in
every case, accept or deny.

**Step 6 — record the punctuation reading (never a gate).**

```sh
.venv/bin/python - <<'PY'
import json, glob
for name in ("q08-control", "q08-prompt-short", "q08-prompt-long"):
    p = sorted(glob.glob(f"build/asr-experiments/*-{name}/result.json"))[-1]
    a = json.loads(open(p).read())["aggregates"]
    print(name,
          "commas/100w", a["commas_per_100w"],
          "terminals/100w", a["terminal_runs_per_100w"],
          "wer_mean", a["wer_mean"],
          "leak_rate", a["prompt_leak_rate"])
PY
```

Copy those numbers into the Outcome section. They are the only evidence this
plan can produce about punctuation (§6.2, §8).

## 6 Metrics & accept/deny

### 6.1 Prompt-leak — exact semantics

All token lists are outputs of `normalize` (`HARNESS.md` §5.1). Define, for a
fixed `n = 3`:

```python
def ngrams(tokens: list[str], n: int = 3) -> set[tuple[str, ...]]:
    """Contiguous n-grams; empty when len(tokens) < n."""
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def corpus_ngrams(references_norm: list[list[str]], n: int = 3) -> set[tuple[str, ...]]:
    """Union of ngrams() over every reference the run will score."""
    return set().union(*(ngrams(r, n) for r in references_norm)) if references_norm else set()


def effective_prompt_ngrams(
    prompt_norm: list[str], corpus: set[tuple[str, ...]], n: int = 3
) -> set[tuple[str, ...]]:
    """Prompt n-grams the corpus never says, i.e. the usable leak probes."""
    return ngrams(prompt_norm, n) - corpus


def prompt_leak(
    effective: set[tuple[str, ...]], ref_norm: list[str], hyp_norm: list[str], n: int = 3
) -> tuple[bool, int]:
    """(leaked, count) for one clip."""
    leaked = (effective & ngrams(hyp_norm, n)) - ngrams(ref_norm, n)
    return bool(leaked), len(leaked)
```

`effective` and `corpus` are computed once per run; `prompt_leak` is called
once per clip. `prompt_leak_rate` (run-wide and per lane) is the fraction of
clips with a hypothesis whose `leaked` is true.

**Why 3-grams.** A single prompt word is uninformative (`the`, `notes` occur
everywhere); a contiguous 3-gram reproduces the prompt's *phrasing*, which is
what an echo does. Longer n would miss short echoes.

**Why the reference is subtracted.** If a clip genuinely says the phrase, its
appearance in the hypothesis is correct transcription, not a leak.

**Why the corpus pool is subtracted.** Without it, a generic prompt 3-gram
such as `(i, want, to)` would be flagged whenever the decoder produced it as
an ordinary substitution somewhere in the corpus, and a `0.0` tail bound would
be unattainable for reasons having nothing to do with the prompt. Subtracting
every 3-gram the corpus references contain leaves only probes the corpus never
utters.

**Known blind spot, stated plainly.** Collision removal makes the metric
*conservative*: an echo consisting solely of corpus-shared 3-grams is not
counted, so the metric can under-report. That is the unsafe direction for a
hard-deny guard, and it is bounded two ways — the prompts in §4.1 are built so
most 3-grams carry a content word, and `preflight` refuses any prompt whose
effective fraction falls below `0.5` (§3 item 7). `result.json` reports
`prompt_ngrams_total` and `prompt_ngrams_effective` so a reader can see how
much of the prompt was actually probing.

**Control.** For `q08-control`, `prompt_norm` is `[]`, so `ngrams` is empty,
`effective` is empty and `prompt_leak_rate` is `0.0` by construction. The
control's leak number is therefore not evidence of anything; only its WER and
punctuation numbers are.

**Worked examples** (each becomes a test in `tests/test_asr_metrics.py`, seen
to fail against a stub before implementation, per `AGENTS.md` hard rule 4):

*Example 1 — a leak.*
`prompt_norm = ["please", "add", "commas", "and", "periods"]`;
corpus references `[["he","opened","the","door"], ["and","periods","of","rain"]]`.
`ngrams(prompt)` is `{(please,add,commas), (add,commas,and), (commas,and,periods)}`;
the corpus pool is `{(he,opened,the), (opened,the,door), (and,periods,of), (periods,of,rain)}`;
no collision, so `effective` is all three. For the clip
`ref = ["he","opened","the","door"]`,
`hyp = ["he","opened","the","door","please","add","commas"]`:
`ngrams(hyp)` contains `(please,add,commas)`, which is in `effective` and not
in `ngrams(ref)`. Result **`(True, 1)`**.

*Example 2 — no leak, because the phrase is the reference's own.*
Same prompt and corpus. Clip
`ref = ["please","add","commas","and","periods","to","this"]`,
`hyp = ["please","add","commas","and","periods","to","this"]`.
All three prompt 3-grams appear in the hypothesis, but all three also appear
in `ngrams(ref)` and are subtracted. Result **`(False, 0)`**.

*Example 3 — collision removal (the blind spot, made explicit).*
`prompt_norm = ["and","periods","of","rain","fell"]`;
same corpus pool. `ngrams(prompt)` is
`{(and,periods,of), (periods,of,rain), (of,rain,fell)}`; the first two collide
with the corpus, so `effective = {(of,rain,fell)}` and
`prompt_ngrams_effective / prompt_ngrams_total = 1/3 < 0.5` — `preflight`
would refuse this prompt (§3 item 7). Scored anyway, for the clip
`ref = ["he","opened","the","door"]`, `hyp = ["and","periods","of","rain"]`,
the result is **`(False, 0)`** even though the hypothesis is a verbatim echo.

*Example 4 — the control.* `prompt_norm = []` → `effective = set()` →
**`(False, 0)`** for every clip, whatever the hypothesis.

### 6.2 Punctuation — measured, reported, never a gate

**LibriSpeech references carry no punctuation** (`HARNESS.md` §2.1: "uppercase,
no punctuation"), and `normalize` deletes every character outside
`[a-z0-9' ]` (`HARNESS.md` §5.1 step 3). Two consequences, both binding on
this plan:

1. WER is completely blind to punctuation. A prompt that fixes every comma in
   the corpus moves `wer_mean` by exactly zero.
2. **Punctuation *correctness* cannot be scored at all** on this corpus. There
   is no ground truth. Any threshold on a punctuation metric would be an
   invented number defended by nothing.

So this plan scores punctuation **density only**, reports it, and gates on
none of it. Density answers one useful question — *did the prompt's
punctuation mechanism engage at all?* — which is what makes a WER result
interpretable: a prompt that does not move comma density did not do the thing
it was supposed to do, and any WER change it produced needs another
explanation.

```python
@dataclass(frozen=True)
class PunctuationStats:
    words: int          # len(normalize(raw))
    terminal_runs: int  # maximal runs of characters drawn from ".?!"
    commas: int         # count of "," characters


def punctuation_stats(raw: str) -> PunctuationStats: ...
```

`words` reuses `normalize` so the denominator matches the WER denominators
exactly. `terminal_runs` counts *maximal runs* so that `...` and `?!` each
count once. Aggregates, over clips with a hypothesis:

- `terminal_runs_per_100w = 100 × Σ terminal_runs / Σ words`
- `commas_per_100w = 100 × Σ commas / Σ words`
- both `null` when `Σ words == 0`.

Stats are computed on `hypothesis_raw` — the formatted string the user would
receive (`transcript_text(result, raw=False)`,
`src/stenographer/cli/commands/transcribe.py:86`) — not on the normalized
tokens, which have no punctuation left.

Known bias: abbreviation periods (`Mr.`) inflate `terminal_runs`. The bias is
constant across variants on the same audio, so cross-variant deltas remain
sound; absolute values are not meaningful.

**Worked example** (a test, seen to fail first): for the raw string
`Mr. Holmes said, "Don't!" Really... yes`, `normalize` gives
`["mister", "holmes", "said", "don't", "really", "yes"]` → `words = 6`; the
runs of `.?!` are `.` (after `Mr`), `!`, and `...` → `terminal_runs = 3`;
one `,` → `commas = 1`. Result **`PunctuationStats(words=6, terminal_runs=3,
commas=1)`**.

### 6.3 Target metric

`wer_mean`, direction `lower`, margin `0.005`, `margin_kind` `absolute`,
computed over lanes `base` + `tail` against `docs/experiments/baseline.json`.
The target is WER and not punctuation because punctuation has no ground truth
here (§6.2) and because the hypothesis worth falsifying is that a prompt makes
recognition *better*, not merely different.

`HARNESS.md` §6.2 guard 1 (`wer_mean <= baseline + 0.002`) is subsumed by the
target when the target is `wer_mean` itself; it is left at its template value
for consistency.

### 6.4 `thresholds.json` — full contents

`docs/experiments/variants/Q08/thresholds.json`:

```json
{
  "schema": 1,
  "wer_mean_max_delta": 0.002,
  "rtf_p95_max_ratio": 1.25,
  "forbid_empty_regressions": true,
  "target": {
    "metric": "wer_mean",
    "direction": "lower",
    "margin": 0.005,
    "margin_kind": "absolute"
  },
  "guards": [
    {"metric": "prompt_leak_rate", "lane": "tail", "direction": "lower",
     "margin_kind": "absolute", "max_absolute": 0.0},
    {"metric": "prompt_leak_rate", "lane": "base", "direction": "lower",
     "margin_kind": "absolute", "max_absolute": 0.01},
    {"metric": "trailing_junk_rate", "direction": "lower",
     "margin_kind": "absolute", "max_regression": 0.01},
    {"metric": "leading_miss_rate", "direction": "lower",
     "margin_kind": "absolute", "max_regression": 0.02}
  ],
  "lanes": ["base", "tail"],
  "min_clips": 400
}
```

`guards` semantics, as specified in `HARNESS.md` §6.1 and restated here for the
reader:

- `lane` absent → the run-wide aggregate over the thresholds' lanes; present →
  `per_lane[<lane>]`.
- `max_absolute` → the run value alone must satisfy it (`<=` for `lower`, `>=`
  for `higher`); the baseline is not consulted. This is what lets a brand-new
  metric gate a run against an older baseline.
- `max_regression` → baseline-relative: `run <= baseline + max_regression` for `lower`,
  `run >= baseline - max_regression` for `higher`.
- A metric key missing from the run, or missing from the baseline while
  `max_regression` is used, or a `null` run value under `max_absolute`, is a
  **harness error (exit 2)**, never a silent pass.
- Every entry appears in the verdict line and in `report.md`, with both values.

Guard rationale:

- **`prompt_leak_rate` on `tail`, bound `0.0`.** Prompt echo onto trailing
  silence is the specific new failure this change could introduce, it is the
  classic Whisper prompt pathology, and in production it would paste text the
  user never said. Zero tolerance across 300 clips is deliberate; one flagged
  clip denies the plan.
- **`prompt_leak_rate` on `base`, bound `0.01`.** At most one clip in 100, to
  absorb the residual chance that an ordinary decoding error happens to
  reproduce a probe 3-gram on real speech.
- **`trailing_junk_rate`, `max_regression` 0.01.** The general hallucination
  symptom must not get worse; the baseline carries this metric, so it can be
  baseline-relative.
- **`leading_miss_rate`, `max_regression` 0.02.** A prompt biases how a transcript
  *begins*; symptom (1) is missing first words. Q02/Q10 own that metric, so
  Q08 only guards against making it worse.

### 6.5 Deciding the matrix

Run both prompt variants regardless of the first result. Then:

- If **neither** prompt variant exits 0 → the plan is **denied**. §9.
- If **exactly one** exits 0 → that variant is the result.
- If **both** exit 0 → the winner is the one with the lower `wer_mean`; on a
  tie within `noise.wer_mean`, the **shorter prompt (A)** wins, because a
  shorter prompt is less to explain to a user, fewer tokens per decode, and a
  smaller echo surface.

An accept still does not automatically change a default — see §9.

## 7 Cost estimate

Clips per variant: 100 (`base`) + 300 (`tail`) = 400. Repeats 1 (temperature
stays `0.0`, so `HARNESS.md` §8.3's three-repeat rule does not apply). Engine
subprocess at ≈4–5 s per clip (`HARNESS.md` §8.4: `base + tail` ≈ 32 min).

| Item | Clips | Wall |
|---|---|---|
| `preflight` (×3, one cold load + 400 SHA-256 checks each) | — | ≈3 min total |
| `q08-control` | 400 | ≈32 min |
| `q08-prompt-short` | 400 | ≈32 min |
| `q08-prompt-long` | 400 | ≈32 min |
| **Total** | **1200** | **≈100 min (1 h 40 m)** |

Disk: three run directories at a few MB each plus their per-run
`XDG_STATE_HOME` logs — well under 100 MB. The corpus (`base` ≈24 MB, `tail`
≈100 MB) already exists as a prerequisite. No new download of any kind.

GPU: one process at a time; no concurrency, no memory pressure beyond a single
`medium.en` load.

## 8 Risks, confounds, invariants

**Confound 1 — corpus register mismatch (the big one).** LibriSpeech
`test-clean` is read 19th-century narrative prose from audiobooks. §4.1's
prompts are modern conversational first-person dictation. Whisper prompts work
by style continuation, so a register mismatch can plausibly *hurt* WER on this
corpus while helping on the owner's real speech. **Therefore: an accept here is
strong evidence (a prompt that helps even on mismatched audio is robust); a
deny here is weak evidence (it does not show that a dictation prompt is useless
for dictation).** This asymmetry must be repeated verbatim in the Outcome
section so a later reader does not over-read a deny. The only way to close it
is a `user` lane of owner-recorded clips with typed references
(`HARNESS.md` §2.4) — out of scope (§10).

**Confound 2 — the prompt reaches only the first 30 s window**
(`transcribe.py:1372-1383`, §2). Every `short` and `medium` clip is fully
prompted; `long` clips (15–35 s, 20 % of `base` and of each `tail` variant)
are partly not. The measured effect is therefore diluted by roughly the `long`
stratum's share of audio. `aggregate` has no per-tag block, so the plan does
not attempt to quantify it; a follow-up with `tags_all: ["short"]` would
(§10).

**Confound 3 — punctuation is unscoreable** (§6.2). The plan cannot show the
benefit that motivates it. It can only show that the mechanism engaged
(density) and that nothing else broke. Stated as a fork in §9.

**Ruled out — token budget.** `max_length = len(prompt) + max_new_tokens`
(`transcribe.py:1416-1419`), so the prompt does not consume our
`_token_budget` allowance and cannot cause truncation. Ruled out by reading
the library, not by measurement.

**Ruled out — prompt truncation.** ≈50 BPE tokens against a 223-token window
(`transcribe.py:1550`).

**Ruled out — sampling noise.** `temperature=0.0` (`model.py:114`) is
unchanged, so `HARNESS.md` §8.3's determinism argument holds and one repeat is
sufficient; the baseline's `noise` block bounds what remains, and step 3's
drift check confirms it on the day.

**Risk — `hotwords` interaction.** `get_prompt` places hotword tokens and
previous tokens under the same `sot_prev` (`transcribe.py:1542-1550`), so a
user who sets both gets hotwords first and the prompt after. The default
`hotwords` is `""` → `None` (`model.py:122`, `config.py:256`), so this run
does not exercise the combination and the recommendation must not claim
anything about it (§10).

**Risk — model scope.** `initial_prompt`, unlike `hotwords`, needs no full
model — it is ordinary prompt-token conditioning, so it works on distil
models too. But the *measured* effect is specific to
`Systran/faster-whisper-medium.en`, and `compare` refuses a run whose
`environment.model` differs from the baseline's (`HARNESS.md` §6.4). If Q12
changes the default model, Q08's result expires.

**Risk — empties.** A prompt can make the decoder emit prompt-flavoured text
where it previously emitted nothing, or the reverse. `forbid_empty_regressions`
catches only the direction where a previously-transcribed clip goes empty; a
clip that was empty and now carries an echo is caught by the leak guard on the
lane where it matters most (`tail`).

**Risk — a leak-caused deny is final.** If a prompt is refused by
`preflight` (§3 item 7) or denied by the leak guard, the plan closes as
denied. Re-running with a prompt string revised *after* seeing the corpus
would be fitting the probe to the data; a new prompt is a new plan.

**`HARNESS.md` §9 invariant checklist, restated for Q08:**

- **No transcript text** anywhere but `build/asr-experiments/<run>/clips.jsonl`.
  Q08 adds `prompt_leak_ngrams` (a count) to `result.json`/`clip_scores`; the
  leaked n-grams themselves stay in `clips.jsonl`. `report.md`, `verdict.json`,
  stdout, this plan file and everything under `docs/experiments/variants/`
  carry numbers only — plus the two prompt strings, which are configuration and
  are explicitly permitted by `HARNESS.md` §3.
- **No network in the ASR path.** No `DecodeOptions` change, `local_files_only`
  untouched (`model.py:87`), subprocess env sets `HF_HUB_OFFLINE=1`. Q08
  downloads nothing at all — not even a corpus; `asr_corpus.py fetch` is a
  prerequisite, not a step.
- **No platform imports.** Q08 adds only pure functions to
  `scripts/asr_metrics.py` and pure guard evaluation to `decide`; the
  `tests/platform/test_core_isolation.py` grep over `scripts/asr_*.py` and the
  two rigs (`HARNESS.md` §9) still passes.
- **Test policy** (`AGENTS.md` hard rule 4): the four `prompt_leak` examples,
  the `punctuation_stats` example, an `aggregate` test for
  `prompt_leak_rate`/`per_lane`, and three `decide` tests (a `max_absolute`
  breach denies with every other guard passing; all guards passing accepts; a
  `max_regression` guard whose metric is absent from the baseline exits 2). Each
  written against a stub and **seen to fail** before implementation. Nothing is
  mocked — no model, no `subprocess`, no `soundfile`.
- **Fixed behaviour stays fixed.** `DecodeOptions()` defaults untouched and
  still pinned; user config still has exactly 23 keys in 4 sections
  (`AGENTS.md` hard rule 9) — Q08 changes at most the *value* of a key that
  already exists.
- **Venv only**, SPDX header on any new file, ruff clean at line length 100,
  py312 target.

## 9 Deliverables & follow-through

### On accept

The winning variant's result is **a configuration finding, not a code change.**
`asr.initial_prompt` already exists (`config.py:63,200,257,311-312`), so
`AGENTS.md` hard rule 9 — exactly 23 keys, no new keys, no setup-only keys —
is satisfied without touching the schema. Nothing under `src/` *must* change.

What to change is a product decision the owner makes, not one this plan
settles. Present it as this fork, with the measured numbers attached:

- **Option A (this plan's recommendation) — document, do not default.** Leave
  `config.py:257`'s template value at `""`. Add a short paragraph to README §3
  ("Configure") next to the existing `[stenographer.asr]` guidance, giving the
  tested prompt verbatim, the measured `wer_mean` delta, the measured
  comma/terminal density change, and the measured leak rate, so a user can opt
  in with an informed expectation. Rationale: a shipped default prompt changes
  every user's decode; it hard-codes one English conversational register into a
  tool whose users dictate code, prose and notes; it is a standing
  hallucination vector on quiet audio; and the accept was earned on read
  narrative prose, not on dictation (§8, confound 1). This option costs
  nothing, forecloses nothing, and needs **no re-baseline** (`HARNESS.md` §7.3
  lists a re-baseline trigger for shipped defaults that moved — they did not).
- **Option B — change the default.** Set the template value at
  `config.py:257` and the in-memory default at `config.py:311-312` to the
  winning prompt (both must agree, or `setup --default` and a fresh install
  would disagree), update the trailing comment on that line, update README §3,
  and note the change in `AGENTS.md`'s decode paragraph. This **is** a shipped
  default moving, so it triggers a re-baseline (`HARNESS.md` §7.3 rule 1) —
  ≈5.5 h — and it triggers the `AGENTS.md` acceptance gates before `dev` → `main`:
  `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest` green, real dictation
  end-to-end in `hold`, `toggle` and `hybrid` on a real machine, and the
  logging gate (one `banner:` block naming every effective key — which now
  includes a non-empty `asr.initial_prompt` — and one `pipeline: utterance`
  line per dictation with no transcript content). Note that the banner would
  begin printing the prompt string on every daemon start; that is
  configuration, not transcript, so `AGENTS.md` hard rule 6 permits it, but it
  should be a conscious choice.
- **Option C — recommend only after a `user` lane.** Hold the finding, build
  the owner-recorded `user` lane (`HARNESS.md` §2.4), re-run Q08's winning
  variant on it, and decide then. This is the only option that actually tests
  the claim on dictation.

Whichever option the owner takes, append the Outcome section below.

### On deny (the expected outcome)

1. Append an `## Outcome` section to this file containing: the verdict line
   from each of the two prompt runs verbatim, both run ids, the resolved
   `target.margin` from step 2, the control's drift number from step 3, the
   punctuation table from step 6, `prompt_ngrams_total` /
   `prompt_ngrams_effective` for each prompt, and the §8 confound-1 sentence
   repeated verbatim so the deny is not over-read. **Numbers only** — no
   hypothesis text, no reference text; the two prompt strings may be referred
   to as "A" and "B" since they are already in §4.1.
2. Copy each `verdict.json` to
   `docs/experiments/results/Q08-<run-id>.json`.
3. Set this file's Status to `denied (<date>)`.
4. Leave `config.py:257` at `""` and change nothing under `src/`.

In both cases the harness additions of §3 (the pure metrics, the aggregates,
`guards`) stay: they are general, they are tested, and `Q05`/`Q07`/`Q11`
can use `guards` immediately — it is the programme's one guard mechanism
(`HARNESS.md` §6.1), not a Q08 extension.

## 10 Out of scope

- **Instructional or meta prompts** ("transcribe with punctuation", "add
  commas") — a different mechanism from style continuation, higher echo risk,
  and untested here. A separate plan if anyone wants it.
- **Domain or per-user prompts**, vocabulary priming, and `asr.hotwords` —
  `hotwords` is a separate key with a separate mechanism
  (`transcribe.py:1542-1550`) and a full-model requirement (`AGENTS.md` hard
  rule 5); the combination of both keys is untested and unrecommended.
- **faster-whisper's `prefix`** — a different parameter with different
  semantics (`transcribe.py:1557-1563`), not exposed by our config and not
  exposable without a 24th key, which `AGENTS.md` hard rule 9 forbids.
- **`condition_on_previous_text=True`**, which would keep the prompt alive
  across every 30 s window (§2, consequence 1). That is a `DecodeOptions`
  change, not a config one, and it would reintroduce cross-window
  hallucination coupling; a separate plan if the >30 s dilution ever matters.
- **Per-stratum effect** (`short` vs `long`), which would need per-tag
  aggregation or a `tags_all: ["short"]` variant. Named as a follow-up in §8,
  confound 2.
- **Punctuation correctness**, which no LibriSpeech-referenced experiment can
  measure (§6.2). Only a `user` or `pseudo-gold` lane with punctuated
  references could.
- **The `cue` lane and first-word loss** — Q10. **Trailing-silence
  characterisation itself** — Q09 (Q08 consumes its lane). **Junk-loop
  suppression** — Q05, Q07, Q11. **Model choice** — Q12. **Latency** — the
  S-series; Q08 only guards `rtf_p95`.
- **Anything requiring a live microphone or the owner's presence** — X01.
