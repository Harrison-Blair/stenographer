# ASR experiment programme

Status: **planning** (2026-08-29). This directory holds the shared harness
specification (`HARNESS.md`), sixteen per-experiment plans (one file each,
listed below), the checked-in baseline (`baseline.json`, once it exists), the
variant and threshold files each plan runs (`variants/<plan>/`), and the
numeric outcome of every denied run (`results/`).

## Purpose and the hands-off principle

The dictation daemon's decode stack is fixed behaviour (`AGENTS.md` hard rule
5), tuned by hand once. The owner reports four things about it: (1) the first
words of an utterance go missing although the overlay showed input; (2) some
utterances end in hallucinated loops ("thank you", "and more and more");
(3) the hallucination rate is high in general; and (4) the first utterance
after a cold start waits ≈4 s (`lock_wait_ms=4048` in the log) and decode
latency is noticeable. Nine logged utterances add two facts: `activate_ms ≤
0.4` with no mid-session stream re-negotiation, so capture is not late; and
two utterances that passed the RMS gate had `vad_frames=0` at `peak_rms
0.024`, so the VAD pre-filter discards quiet speech wholesale. Each plan
turns one hypothesis about these into a run of the harness. **An agent runs a
plan end-to-end; the harness exit code is the verdict (0 accept, 1 deny, 2
harness error); the owner only reviews the accepted change and the numbers.**
No plan may contain a step that needs a human, except `X01`, which says so.

## Provisional decisions

These are the working assumptions; each is labelled *provisional* in
`HARNESS.md` and can be flipped by editing that one section.

- **Corpus** (`HARNESS.md` §2): LibriSpeech `test-clean`, a seeded
  100-utterance subset (CC BY 4.0), fetched once by `scripts/asr_corpus.py`
  — never by the daemon or the ASR path — into gitignored
  `build/asr-corpus/`, converted to 16 kHz mono WAV, plus six numpy-generated
  augmentation lanes, all of them landed in the foundation commit before the
  baseline: `tail` (1 s / 3 s / 5 s of room tone appended), `cue` (the bundled
  `record_start` cue plus a 0–300 ms gap prepended, including `cue=legacy`
  clips), `quiet` (per-clip gain to a target peak RMS of 0.030 / 0.020 over a
  seeded −60 dBFS floor), `silence` (20 clips of pure room tone with an empty
  reference), `onset` (300 ms of leading room tone, and a 0.25→1.0 ramp over the
  first 200 ms), and `longform` (60 clips of 60–130 s, seeded concatenations of
  base clips). Q09 adds three `tail-*` probe lanes and Q11 a `control` manifest,
  both self-controlled and outside the baseline. The manifest is source-agnostic
  (`lane` tag) so an owner-recorded set or a large-v3 pseudo-gold set drops in
  beside it.
- **Injection seam** (`HARNESS.md` §3.2): a frozen `DecodeOptions` dataclass
  in `src/stenographer/transcribe/model.py` whose defaults are exactly
  today's literals, threaded through `Model.__init__`, constructed with
  non-default values only by `scripts/`, and never exposed to user config.
  Monkeypatching module constants from the harness is the rejected
  alternative: it cannot reach the call-site literals and leaves no record of
  what ran.
- **Baseline** (`HARNESS.md` §7): established once from the shipped defaults
  with the subprocess engine, three repeats, over all seven baseline lanes;
  re-baselined only after an accepted change is merged, or when a *compared*
  lane's own digest moves (`HARNESS.md` §7.3).
- **Guards** (`HARNESS.md` §6.1): a plan states everything it must not break as
  entries in the `thresholds.json` `guards` array, and `"target": null` is legal
  for a plan whose whole claim is "nothing gets worse". Several plans also carry
  a small local check script; those are the fallback if the foundation commit
  has not landed `guards` yet, never a second mechanism.

## Index

Files not yet present are linked anyway; other agents write them against the
template in `HARNESS.md` §10.

| Plan | Goal |
|---|---|
| [`Q01-temperature-fallback.md`](Q01-temperature-fallback.md) | Replace the scalar `temperature=0.0` with the library's fallback ladder so `compression_ratio_threshold` becomes live; trade trailing junk against WER and latency. |
| [`Q02-vad-parameter-grid.md`](Q02-vad-parameter-grid.md) | Grid over `vad_threshold` / `min_speech_duration_ms` / `min_silence` / `speech_pad` against leading-word recall and the quiet-speech `vad_frames=0` drop. |
| [`Q03-beam-size.md`](Q03-beam-size.md) | `asr.beam_size`: control 1, then 3 and 5; 8 only if the curve is still descending. WER against decode latency. |
| [`Q04-compute-type.md`](Q04-compute-type.md) | `int8` (control, resolving to `int8_float16` on this GPU) vs `float16`, with `default` and `float32` as resolution and numerical references; `bfloat16` is blocked by config validation. Load and decode latency at equal WER; settles the default before the speed plans. |
| [`Q05-repetition-penalty.md`](Q05-repetition-penalty.md) | `repetition_penalty` and `no_repeat_ngram_size` against end-of-utterance loops. |
| [`Q06-assemble-no-speech-gate.md`](Q06-assemble-no-speech-gate.md) | The daemon-side `_assemble` re-gate on vs off: empties on quiet clips. A **no-harm** experiment — the library-equivalent arm is excluded on proof, and the accept rests on a pre-registered mechanism argument (§6.2 Branch B), not on a metric that improves. |
| [`Q07-hallucination-silence-threshold.md`](Q07-hallucination-silence-threshold.md) | `hallucination_silence_threshold` `{None, 1.0, 2.0} × min_silence {500, 2000 ms}` on the `tail` lane, plus `vad_filter=false` diagnostics; `0.5` only conditionally. |
| [`Q08-initial-prompt.md`](Q08-initial-prompt.md) | A dictation-style `asr.initial_prompt`: punctuation and register priming against WER and junk. |
| [`Q09-trailing-silence-augmentation.md`](Q09-trailing-silence-augmentation.md) | Build the `tail` lane and characterise junk rate as a function of appended room tone. |
| [`Q10-leading-cue-augmentation.md`](Q10-leading-cue-augmentation.md) | Build the `cue` lane and characterise first-word loss from cue bleed plus onset gap, including the VAD interplay. |
| [`Q11-post-decode-tail-filter.md`](Q11-post-decode-tail-filter.md) | A pure post-decode filter that drops a low-probability trailing run of words and a fixed-phrase final segment: junk rate against deletions of genuine text. |
| [`Q12-alternate-models.md`](Q12-alternate-models.md) | `small.en`, `distil-medium.en`, `large-v3-turbo` and others against `medium.en`: WER and latency (hotwords need a full model). |
| [`S01-cold-start-latency.md`](S01-cold-start-latency.md) | Break the ≈4 s first-utterance wait into import, load and decode; what shortens it within the press-lazy invariant. |
| [`S02-batched-inference-long-utterances.md`](S02-batched-inference-long-utterances.md) | `BatchedInferencePipeline` for utterances above a length threshold: decode latency at equal WER. |
| [`S03-idle-unload-reload-cost.md`](S03-idle-unload-reload-cost.md) | `asr.idle_unload_seconds` against the measured reload penalty; a default recommendation, not a decode change. |
| [`X01-mono-first-channel-order.md`](X01-mono-first-channel-order.md) | Mono-first channel negotiation on the owner's array microphone; the channel mean is measured as a diagnostic only, never proposed as a default. **Needs a live microphone; not hands-off.** |

## Execution order and dependencies

1. **Foundation** — implement `HARNESS.md` §1–§8: `asr_corpus.py`,
   `asr_metrics.py`, `asr_experiment.py` and their pure tests, the
   `DecodeOptions` seam, the `thresholds.json` `guards` mechanism, and **every
   lane generator** (`tail`, `cue` including `cue=legacy`, `quiet`, `silence`,
   `onset`, `longform`, Q09's three `tail-*` probe lanes and Q11's `control`
   builder). A lane added after the baseline forces a re-baseline of the lanes it
   is compared on, so they all land here. Then fetch and build the corpus.
2. **Lane validation** — `Q09` and `Q10`, **before** the baseline. Both are
   self-controlled: each compares an augmented condition against the same clips'
   own un-augmented control inside one run, so neither needs
   `docs/experiments/baseline.json` to exist. They are what says the `tail` and
   `cue` lanes are worth freezing into it.
3. **Baseline** — over all seven baseline lanes, three repeats, subprocess
   engine. Nothing after this point starts before
   `docs/experiments/baseline.json` exists with its `noise` block.
4. **`Q04`** — settles `compute_type` so the speed plans measure the right
   default.
5. **Quality plans** — `Q01`, `Q02`, `Q03`, `Q05`, `Q06`, `Q07`, `Q08`, `Q11`,
   `Q12`. Independent of each other; run in any order, but merge one accepted
   change at a time and re-baseline between (`HARNESS.md` §7.3).
6. **Speed plans** — `S03` any time after the foundation; `S01` after `Q04`
   (its V1/V6/V7 take Q04's accepted compute type, S01 §3.4). Both run on their
   own rig (`scripts/asr_cold_start.py`) and need no corpus baseline at all.
   `S02` after `Q04` too, on the in-process engine, because its target is a
   decode-time metric behind a `DecodeOptions` field (`HARNESS.md` §3.1).
7. **`X01`** — any time; it is self-baselining, and only needs the owner's
   machine and the owner present.

## What belongs in the implementation commit, not here

This directory's documentation commit changes no code and no `AGENTS.md`
line. The commit that implements `HARNESS.md` must, in the same commit:

- add `docs/experiments/` to the `docs/` row of the `AGENTS.md` architecture
  map;
- record the `DecodeOptions` decision in `AGENTS.md` hard rule 5 (or the
  `transcribe/` row): a dev-only seam with fixed defaults that only
  `scripts/` may construct with non-default values;
- extend the `AGENTS.md` sentence naming the only permitted download to cover
  `scripts/asr_corpus.py fetch`;
- add `scripts/asr_*.py` (corpus, metrics, experiment), `scripts/asr_cold_start.py`
  (the S01/S03 rig), `scripts/q10_vad_probe.py` and `scripts/x01_record.py` (the
  X01 rig) to `tests/platform/test_core_isolation.py`'s source grep;
- add one sentence to the `AGENTS.md` `packaging/`, `scripts/` row naming those
  tools and the two rigs, on the model of the `cue_audition.py` entry already
  there.
