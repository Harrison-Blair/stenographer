# X01 — mono-first channel negotiation

Status: planned (2026-08-29)

**Needs a live microphone and the owner speaking. Not hands-off.** Every step
outside the single recording session is automatic; the session itself is
scripted, blinded, and budgeted at ~20 minutes (§7).

Baseline for `file:line` citations: `dev` @ `a1b9807` (v0.11.6).

## 1 Hypothesis

Opening the input stream **mono-first** (`_FALLBACK_CHANNELS = (1, 2)`,
`src/stenographer/audio.py:30`) instead of stereo-first-then-keep-channel-0
raises the mean captured level on this laptop's microphone array by
≥ 1.5 dB (`peak_dbfs_mean`, and at least 2× the measured within-arm
spread) **without** losing signal-to-noise (`snr_db_mean` no worse than
−0.5 dB), **without** lowering `leading_word_recall_mean` by more than 0.01,
**without** raising `wer_mean` by more than +0.002, and **without** producing
a new `vad_frames == 0` drop or a new empty transcript.

Falsifiable in one sitting: if mono-first is merely a duplicate of channel 0
the level delta is ≈ 0 dB and the plan denies; if the mono open is a hotter
but noisier AGC path, `snr_db_mean` or `wer_mean` denies it.

## 2 Symptom & mechanism

**Symptoms** (`docs/experiments/README.md`, items 1 and 3, plus the two logged
utterances): the first words of an utterance go missing although the overlay
showed input, and two utterances that *passed* the RMS gate at
`peak_rms ≈ 0.024` (−32.4 dBFS) still decoded with `vad_frames=0` — the
Silero VAD pre-filter discarded the whole capture. The owner's microphone runs
at 30 % capture gain (machine note), so the input is quiet by construction and
sits close to whatever level floor the VAD applies.

**Code path.**

- `src/stenographer/audio.py:30` — `_FALLBACK_CHANNELS: tuple[int, ...] = (2, 1)`.
- `src/stenographer/audio.py:216-253` — `_negotiate` loops channels **outer**,
  sample rates inner, and keeps the first stream PortAudio accepts. On this
  machine the first attempt (2 channels @ 16 kHz) succeeds: the owner's log
  reads `recorder: prepared ... rate_hz=16000 channels=2`
  (`audio.py:203-208`).
- `src/stenographer/audio.py:328` — the callback keeps
  `indata[:, 0].copy()`. Channel 0 only, never an average; the same choice is
  restated for file input in
  `src/stenographer/transcribe/pipeline.py:136-145` (`downmix`), whose
  docstring gives the reason: averaging a stereo mic whose second channel is
  silent or out of phase halves or cancels the speech.
- `src/stenographer/audio.py:72-101` — `speech_gate_stats` frames the result
  at 50 ms and reports `peak_rms` / `mean_rms`; the default threshold is
  `audio.min_speech_rms = 0.0005` (`config.py:249`), far below the
  −32.4 dBFS observed peak, which is why the gate passes and the VAD still
  drops everything.
- `src/stenographer/transcribe/model.py:32-37` — `_VAD_PARAMETERS`
  (`threshold: 0.5`); `model.py:147-151` — the `vad_frames` the summary line
  reports.

**Why the change should act on it.** When a client opens a 2-channel stream on
a laptop array, PortAudio/ALSA hands through the device's own two capsules and
`indata[:, 0]` is *one physical capsule*. When a client opens a 1-channel
stream, the ALSA/PipeWire graph must produce mono itself, and what it produces
is device- and profile-dependent:

- a **sum or average of correlated capsules** — speech is correlated across a
  small array, so it adds coherently (up to +6 dB), while uncorrelated
  capsule noise adds at 3 dB, for up to +3 dB of SNR as well as a hotter
  signal; or
- the array's **processed / beamformed mono node** (PipeWire may route a mono
  client to a different node or profile entirely), which is usually hotter and
  cleaner still; or
- a plain **duplicate of channel 0** (0 dB, hypothesis dead); or
- an **AGC/echo-cancel** path that is hotter *and* noisier or spectrally
  mangled — the case guards 2 and 3 exist to catch.

A hotter, cleaner capture raises the per-frame speech probability the VAD
computes, which is the direct lever on both the `vad_frames=0` drop and the
soft-onset first-word loss.

**This plan does not change what the callback keeps.** Channel 0 stays channel
0; a mono open simply makes channel 0 *be* the device's mono. The "channel 0
vs. channel mean" question the index page raises is answered here only as a
free diagnostic (§4, arm C) because it costs no extra human time; changing
`downmix`/`_on_audio` to average would be a separate plan (§10).

## 3 Prerequisites

**Harness pieces** (`HARNESS.md` §1):

- `scripts/asr_metrics.py` — `normalize`, `align`, `wer`,
  `leading_word_recall`, `trailing_junk`, `aggregate`. Used unchanged.
- `scripts/asr_experiment.py` — `preflight` and `run`, the **in-process**
  engine (`HARNESS.md` §3.1), and `--manifest PATH`. If `run` still hardcodes
  `build/asr-corpus/manifest.json`, X01's implementation adds `--manifest`
  (a pure argument with the existing path as its default; no behaviour change
  to any other plan). See fork F3.
- `docs/experiments/baseline.json` is **not** required. X01 is
  self-baselining: arm A (the shipped order) is the control, recorded in the
  same session on the same corpus, so `HARNESS.md` §6.4's manifest/device
  refusals are satisfied trivially and the LibriSpeech baseline is never
  consulted. X01 may therefore run before or after the rest of the programme;
  `README.md` schedules it last for convenience, not dependency.

**New pieces this plan adds:**

- `src/stenographer/audio.py` — one keyword-only `Recorder.__init__`
  parameter, `channel_order: tuple[int, ...] = _FALLBACK_CHANNELS`, read by
  `_negotiate` in place of the module constant. **This is a production-code
  touch;** see fork F1.
- `scripts/x01_record.py` — the recording, diagnostic and scoring tool
  (§4, §5). Development tooling on the `scripts/cue_audition.py` model: never
  shipped, never imported by `src/stenographer/`, writes only under `build/`.
- `tests/test_x01_record.py` — pure tests for `schedule`, `clip_id`,
  `noise_floor_dbfs`, `snr_db`, `arm_split`, the X01 aggregates and
  `x01_decide`, each seen to fail first (`AGENTS.md` hard rule 4). Uses the
  `sys.path.insert` convention of `tests/test_cue_audition.py:18-29`.

**Corpus lane:** `user` (`HARNESS.md` §2.4, §2.5) — this plan produces it. No
existing lane is read or written; `build/asr-corpus/manifest.json` and its
SHA-256 are untouched, so no re-baseline is triggered (`HARNESS.md` §7.3).

**Machine:** the owner's laptop, its array microphone at its normal 30 %
capture gain (do **not** change it for the session — see §8), the model
cached, CUDA present. A quiet room, door shut, fan noise as it normally is.

## 4 Variant matrix

The matrix is **channel order × passage × repeat**, interleaved A-B-B-A. The
decode variant is constant: shipped defaults, so any difference between arms
comes from the audio and nothing else.

### 4.1 Arms

| Arm | `channel_order` | Role | Takes |
|---|---|---|---|
| **A** (control) | `(2, 1)` — shipped, `audio.py:30` | Stereo-first; callback keeps channel 0 | 24 |
| **B** (treatment) | `(1, 2)` | Mono-first; falls back to stereo if mono is refused | 24 |
| **C** (diagnostic) | raw 2-channel stream opened by the script, both channels kept | Answers "channel 0 vs channel 1 vs mean" from one capture. **Never enters the accept rule.** | 4 |

Arm B falling back to stereo mid-session is a **harness error** (exit 2), not
a result: it would silently make B a copy of A. `x01_record.py` records the
negotiated `channels` and `rate_hz` per take and refuses the session if any
arm-B take negotiated 2 channels.

### 4.2 Passages (12; the reference text, verbatim)

Fixed, checked into this file, printed one at a time by the script, and used
verbatim as the manifest `reference`. They avoid digits, abbreviations and
unusual proper nouns so `asr_metrics.normalize`'s number folding and
abbreviation table (`HARNESS.md` §5.1) are inert and cannot bias one arm.

| id | tags | passage |
|---|---|---|
| `p01` | `onset=fricative`, `level=normal` | Federal funding for the survey finished last Friday. |
| `p02` | `onset=fricative`, `level=normal` | Several of these settings should stay the same. |
| `p03` | `onset=fricative`, `level=normal` | Whether the weather holds is anyone's guess. |
| `p04` | `onset=fricative`, `level=normal` | Think about the third option before you answer. |
| `p05` | `onset=plosive`, `level=normal`, `ending=thanks` | Please send the revised notes when you get a chance, thank you. |
| `p06` | `onset=fricative`, `level=normal`, `ending=thanks` | That covers everything on the list for now, thanks a lot. |
| `p07` | `onset=fricative`, `level=soft` | Something about the schedule seems slightly off. |
| `p08` | `onset=fricative`, `level=soft` | Have a look at the second paragraph on page four. |
| `p09` | `onset=fricative`, `level=soft` | For the moment, leave the microphone where it is. |
| `p10` | `onset=vowel`, `level=normal` | Open the terminal and run the installer again. |
| `p11` | `onset=plosive`, `level=normal` | Backup copies of the database live on the second drive. |
| `p12` | `onset=vowel`, `level=normal`, `long` | I would like to move the meeting to Thursday afternoon if that works for everyone. |

Why these: `p01`–`p04` and `p06`–`p09` start on a soft fricative, the onset a
quiet capture loses first; `p05` and `p06` end in a natural "thank you" /
"thanks a lot", the exact tokens the hallucination loop invents, so
`trailing_junk`'s reference guard (`HARNESS.md` §5.5b) is exercised on real
text rather than only on augmented silence; `p07`–`p09` are read **softly**,
reproducing the quiet-input condition the whole hypothesis is about; `p12` is
long enough to give the VAD several speech regions.

### 4.3 Take schedule

24 A/B takes per arm: 12 passages × 2 repeats. Order within a passage
alternates by repeat, giving an A-B-B-A block across each passage pair:

```
repeat 0: p01(A,B) p02(B,A) p03(A,B) p04(B,A) … p12(B,A)
repeat 1: p01(B,A) p02(A,B) p03(B,A) p04(A,B) … p12(A,B)
```

Pure `schedule(passages, repeats) -> list[Take]` produces this list; the test
asserts each passage sees each arm exactly `repeats` times, that no arm runs
more than twice consecutively, and that the arm that goes first alternates.
Arm C's 4 takes (`p01`, `p05`, `p07`, `p12`) run last, after the A/B block, so
they cannot perturb the paired comparison.

### 4.4 Harness variant

`docs/experiments/variants/X01/x01-user.json`:

```json
{
  "schema": 1,
  "name": "x01-user",
  "plan": "X01",
  "lanes": ["user"],
  "tags_any": [],
  "tags_all": [],
  "engine": "inprocess",
  "repeats": 1,
  "config": {},
  "decode": {}
}
```

`engine: "inprocess"` — X01 measures no cold-load number, both arms decode
through one identically-configured `Model`, and one load instead of 48 keeps
the agent's half of the run under two minutes. `repeats: 1` — the decode is
deterministic at temperature 0 (`HARNESS.md` §8.3); X01's repeats are
**acoustic**, and live in the corpus (§4.3), which is where the variance
actually is.

## 5 Procedure

### 5.1 Automatic — before the human is called (agent, ~3 min)

```sh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration" tests/test_x01_record.py tests/test_audio.py
.venv/bin/python scripts/asr_experiment.py preflight
.venv/bin/python scripts/x01_record.py probe --json build/asr-corpus/user-x01/probe.json
```

`x01_record.py probe` is read-only and silent-by-construction: it calls
`stenographer.audio_probe.query_devices()` (`audio_probe.py:35`), then for each
of `channels=1` and `channels=2` constructs a `Recorder(..., channel_order=…)`
and calls `prepare()` followed immediately by `close()`. `prepare` opens but
never **starts** the stream (`audio.py:184-190`, `audio.py:255`), so no
callback runs and no audio is captured. It records, per arm, the negotiated
`channels` and `rate_hz`, and the enumerated `max_input_channels`.

`probe` exits 2, and the plan stops before any human is involved, when:

- no input device is enumerated, or `query.error` is set;
- the default input device reports `max_input_channels < 2` — arm A cannot be
  stereo, so there is nothing to compare (record `reason:
  "device_is_mono"`);
- `channels=1` is refused with PortAudio `-9998` (`_ERR_BAD_CHANNELS`,
  `audio.py:31`, `audio.py:232-234`) — **the "array reports mono unsupported"
  risk**; record `reason: "mono_unsupported"`, set this file's Status to
  `abandoned`, and stop;
- arm B's probe negotiates `channels != 1` for any other reason.

### 5.2 The recording session (human present, ~20 min)

```sh
.venv/bin/python scripts/x01_record.py record \
  --out build/asr-corpus/user-x01 \
  --repeats 2 --take-seconds 9 --lead-in 0.6 --stereo-diagnostic 4
```

**What the human sees and does — and nothing else.** The script prints a
five-line briefing once (sit at your usual distance, normal speaking voice
except where the screen says *softly*, read only the printed line, do not
adjust the microphone or the system volume for the whole session, silence
notifications). Then, per take:

```
Take 7 of 52                                        [Enter] record   [q] quit

    Something about the schedule seems slightly off.

    Read this SOFTLY, at the volume you'd use late at night.
```

On Enter: a 0.6 s lead-in (`--lead-in`, recorded, deliberately containing no
speech — it is the noise-floor window of §6.2), then `SPEAK` in bold and a
9 s fixed capture with a one-line countdown, then:

```
    captured 9.0 s   peak -28.7 dBFS   floor -61.2 dBFS
    [Enter] keep    [r] redo    [q] quit
```

The only judgement asked of the human is *redo* — used when they stumbled,
coughed, said something other than the printed line, or a notification chimed.
A redo re-records the same passage and arm immediately and discards the
previous WAV. **The arm is never shown.** The take counter, the passage, and
the two numbers are the entire human-visible surface; the schedule is blinded
so the reader cannot unconsciously push harder on one arm.

Arm C's 4 takes follow, labelled only `Take 49 of 52` with the same prompt.

Human effort: 52 takes × (≈4 s to read the prompt + 9 s capture + ≈2 s to
keep) ≈ 13 min, plus the briefing and a redo or two ≈ **20 minutes,
door-to-door, once**. The human's involvement ends when the script prints
`session complete`.

**What the script does per take.** Fresh `Recorder(device=cfg.audio.input_device,
max_seconds=take_seconds, channel_order=arm.channel_order)`, `prepare()`,
`start()`, sleep the window, `stop()`, `close()` — a full re-negotiation every
take, which is both what the daemon's cold path does and what forces the arm's
channel order to be honoured. It writes:

```
build/asr-corpus/user-x01/
  probe.json                       §5.1 output
  manifest.json                    schema 1, HARNESS.md §2.5 shape, lane "user"
  wav/x01-p07-r1-a.wav             16 kHz mono 16-bit PCM, via soundfile
  wav/diagnostic/x01-p01-c.wav     2-channel, arm C only
  session.json                     per-take negotiated channels/rate, timings, redo count
```

Clip id: `x01-<passage>-r<repeat>-<arm>`; tags:
`["arm=stereo-first"|"arm=mono-first", "passage=p07", "repeat=1",
"level=soft", "onset=fricative", "ending=thanks"?, "long"?]`; `lane: "user"`;
`reference`: the passage verbatim; `derived_from: null`; `augmentation: null`;
`sha256` of the WAV bytes, as §2.5 requires. Each take's
`x01: {peak_rms, peak_dbfs, floor_dbfs, snr_db, negotiated_channels,
negotiated_rate_hz, redos}` block rides in the clip entry — extra keys in a
manifest clip are additive and no other plan reads them.

The manifest is rewritten after every kept take, so an interrupted session
still yields a scorable (if smaller) corpus; `x01_record.py manifest --out …`
rebuilds it from the WAVs alone if it is ever lost.

The script never calls `setup_logging`, so the `stenographer` logger has no
handlers and nothing reaches any `stenographer.log` (`HARNESS.md` §3.1, the
in-process engine's rule). The passage text exists in this plan and in the
gitignored manifest; **no transcript of what was actually said** is written
anywhere but `clips.jsonl` under `build/` (§8).

If the human quits early, the run is scorable only when every passage has at
least one take in **both** arms and there are ≥ 20 kept takes per arm
(`min_clips`, §6.4); otherwise `score` exits 2.

### 5.3 Automatic — after the human leaves (agent, ~5 min)

```sh
.venv/bin/python scripts/asr_experiment.py run \
  --manifest build/asr-corpus/user-x01/manifest.json \
  --variant docs/experiments/variants/X01/x01-user.json
```

Prints the run directory `build/asr-experiments/<run-id>-x01-user/`. Then:

```sh
.venv/bin/python scripts/x01_record.py score \
  --run build/asr-experiments/<run-id>-x01-user \
  --manifest build/asr-corpus/user-x01/manifest.json \
  --thresholds docs/experiments/variants/X01/thresholds.json
```

`score` reads `clips.jsonl` (the harness's per-clip records, `HARNESS.md`
§4.1 — including `wer`, `leading_word_recall`, `trailing_junk`, `empty`,
`gate`, `peak_rms`, `vad_frames`), joins the manifest's `x01` block by clip
id, splits the records by the `arm=` tag, aggregates each side, applies §6,
and writes `verdict.json` + `report.md` into the run directory. It prints one
verdict line and the comparison table. **No text in either file or on stdout.**

Exit codes, and what the agent does with each:

- **0 — accept.** Proceed to §9's accept branch.
- **1 — deny.** Append the Outcome section (§9's deny branch); the shipped
  order stands.
- **2 — harness error.** Do not interpret any number. The distinguishable
  causes, each printed with a `reason=` token: `mono_unsupported` /
  `device_is_mono` (probe, §5.1); `arm_b_negotiated_stereo` (any arm-B take
  whose `negotiated_channels != 1`); `min_clips` (session cut short);
  `unpaired_passages` (a passage missing from one arm); `decode_errors` (any
  clip with `exit_code != 0` or `error` set, in either arm);
  `manifest_mismatch` (a clip's SHA-256 changed under the runner). Fix and
  re-run §5.3; only `mono_unsupported`, `device_is_mono` and `min_clips`
  require the human again.

## 6 Metrics & accept/deny

### 6.1 Per-clip metrics

| Metric | Source | Meaning here |
|---|---|---|
| `peak_rms`, `gate` | harness clip record (`speech_gate_stats`, `audio.py:72`) | how hot the capture actually was, and whether the energy gate passed |
| `peak_dbfs` | `x01_record.py`, `20·log10(max(peak_rms, 1e-6))` | the same number in the domain the accept rule is stated in |
| `floor_dbfs` | `x01_record.py`, RMS of the `--lead-in` window (the first 0.6 s, recorded before `SPEAK` is printed, so it is speech-free by construction) | the room + preamp noise floor for this take |
| `snr_db` | `peak_dbfs − floor_dbfs` | catches "hotter, but only because the noise got hotter" |
| `vad_frames` | harness clip record (`model.py:147-151`) | 0 means the VAD discarded the whole capture — the observed failure |
| `leading_word_recall` | `asr_metrics` §5.4, `k=3` | the first-words symptom |
| `wer` | `asr_metrics` §5.3 | overall decode quality |
| `trailing_junk` | `asr_metrics` §5.5 | the hallucinated-tail symptom |
| `empty` | `hyp_words == 0` | the whole utterance lost |

### 6.2 Per-arm aggregates (pure, in `x01_record.py`)

Over an arm's kept, error-free clips: `peak_dbfs_mean`, `floor_dbfs_mean`,
`snr_db_mean`, `wer_mean`, `leading_word_recall_mean`, `leading_miss_rate`,
`trailing_junk_rate`, `vad_zero_rate` (fraction with `vad_frames == 0`),
`gate_pass_rate`, `empty_rate`, `clips`. Means are arithmetic in the dB
domain — the hypothesis is about level, and averaging linear RMS would let one
loud take dominate.

`spread_db` is the **within-arm noise measure**: for arm A, the mean absolute
difference between the two repeats' `peak_dbfs` for the same passage,
averaged over passages. It is the honest local equivalent of `HARNESS.md`
§7.1's `noise` block, measured in this session rather than assumed.

### 6.3 `docs/experiments/variants/X01/thresholds.json`

```json
{
  "schema": 1,
  "plan": "X01",
  "paired": false,
  "target": {
    "metric": "peak_dbfs_mean",
    "direction": "higher",
    "margin": 1.5,
    "margin_kind": "absolute",
    "margin_floor": "2x_spread_db"
  },
  "guards": {
    "snr_db_mean_min_delta": -0.5,
    "leading_word_recall_mean_min_delta": -0.01,
    "wer_mean_max_delta": 0.002,
    "vad_zero_rate_max_delta": 0.0,
    "empty_rate_max_delta": 0.0,
    "trailing_junk_rate_max_delta": 0.05
  },
  "lanes": ["user"],
  "min_clips": 20,
  "require_all_passages_paired": true
}
```

**This file never passes through `decide`.** X01 is self-baselining: it compares
two arms recorded in one session against each other, on metrics
(`peak_dbfs_mean`, `floor_dbfs_mean`, `snr_db_mean`, `spread_db`) that no corpus
run produces and that `docs/experiments/baseline.json` does not carry. The file
is read by `x01_decide` in `scripts/x01_record.py` and by nothing else, which is
why its `guards` may be an **object** of per-metric delta keys rather than
`HARNESS.md` §6.1's array: the two spellings never meet, and the array stays the
canonical one for everything `decide` judges. `target.margin_floor` is likewise
rig-local vocabulary — it says the 1.5 dB margin is additionally floored at
`2 × spread_db`, measured in this session (§6.2).

### 6.4 The rule (pure `x01_decide(arm_a, arm_b, thresholds) -> Verdict`)

**Mono-first is accepted iff all of the following hold**, with `A` the arm-A
aggregate and `B` the arm-B aggregate:

1. **Target.** `B.peak_dbfs_mean − A.peak_dbfs_mean ≥ max(1.5,
   2 × A.spread_db)`. The floor exists because a margin smaller than twice the
   session's own repeat-to-repeat spread is not a measurement
   (`HARNESS.md` §7.1's rule, applied to a locally measured spread).
2. **No SNR loss.** `B.snr_db_mean − A.snr_db_mean ≥ −0.5`.
3. **Leading words not worse.** `B.leading_word_recall_mean −
   A.leading_word_recall_mean ≥ −0.01`.
4. **WER not worse.** `B.wer_mean − A.wer_mean ≤ +0.002` (`HARNESS.md`
   §6.2 guard 1, unchanged).
5. **No new VAD wipeout.** `B.vad_zero_rate ≤ A.vad_zero_rate`.
6. **No new empties.** `B.empty_rate ≤ A.empty_rate`.
7. **No junk explosion.** `B.trailing_junk_rate − A.trailing_junk_rate ≤
   0.05` (loose: 24 clips resolve this rate to ≈0.04, so a tighter bound
   would be noise; `Q05`/`Q11` own this metric properly).
8. **Both arms complete.** `A.clips ≥ 20`, `B.clips ≥ 20`, every passage
   present in both, zero decode errors in either.

Anything else is a **deny**; a violation of 8 is exit 2, not a deny.

Failing 1 while passing 2–8 is the "mono is just a duplicate of channel 0"
outcome and is the single most likely result; the report must state the
measured delta so the answer is *quantified*, not merely negative.

There is no multi-variant tie-break: the matrix has exactly one treatment arm.

### 6.5 Verdict line and report

```
DENY x01-mono-first: peak_dbfs_mean -31.4 -> -31.1 (+0.3 < margin 1.5, spread 0.4); snr_db_mean +0.1 (>= -0.5 OK); leading_word_recall_mean 0.958 -> 0.972 (OK); wer_mean 0.071 -> 0.069 (OK); vad_zero_rate 0.083 -> 0.083 (OK); empty_rate 0.000 -> 0.000 (OK)
```

Followed by a Markdown table with one row per §6.2 aggregate (arm A, arm B,
delta, guard status), then the same table sliced by `level=soft` vs
`level=normal` and by `onset=fricative` vs the rest — the soft/fricative slice
is where the hypothesis predicts the effect, and reporting it separately turns
a null overall result into information rather than a shrug. Then arm C's
diagnostic table (§6.6). Numbers only, in every one of them.

### 6.6 Arm C diagnostic (reported, never decisive)

From each 2-channel take, `x01_record.py score` reports, purely:
`ch0_peak_dbfs`, `ch1_peak_dbfs`, `mean_peak_dbfs` (the level of
`(ch0+ch1)/2`), `ch0_floor_dbfs`, `ch1_floor_dbfs`, `mean_snr_db`, and the
inter-channel Pearson correlation over the speech region. This says, in one
table and at zero extra human cost, whether the two capsules are correlated
(a mean would gain), anti-correlated (a mean would cancel — the risk
`pipeline.py:136-145` names), or whether channel 1 is simply the hotter one.
It informs a possible follow-up plan (§10) and nothing in this one.

## 7 Cost estimate

| Phase | Who | Time |
|---|---|---|
| Implement the seam, script, tests, variant, thresholds | agent | ≈2 h |
| §5.1 lint, pure tests, preflight, probe | agent | ≈3 min |
| §5.2 recording session, 52 takes | **human** | **≈20 min, once** |
| §5.3 in-process decode of 48 clips (one model load ≈2.5 s + 48 × ≈0.7 s, `HARNESS.md` §8.4) | agent | ≈2 min |
| §5.3 scoring | agent | <5 s |
| §9 follow-through on accept (change, tests, integration suite, real dictation gate) | agent + ≈10 min human | ≈40 min |

Disk: 48 mono takes × 9.6 s × 16 kHz × 2 B ≈ 15 MB, 4 stereo diagnostics
≈ 2.5 MB, run directory ≈ 1 MB. **Under 20 MB**, all under gitignored
`build/`. No download; no GPU time beyond one model load and 48 short decodes.

Total human cost of the whole plan: **one 20-minute session**, plus ≈10
minutes at the acceptance gate if it accepts.

## 8 Risks, confounds, invariants

| Risk / confound | Handling |
|---|---|
| **Room noise drifts across the session** (fan spins up, street noise) | A-B-B-A interleaving (§4.3) plus 2 repeats: drift is shared by both arms at every point in the session. `floor_dbfs` is recorded per take, and `score` reports arm A's floor over take order so a monotone drift is visible rather than silent. |
| **The speaker drifts louder or quieter** (fatigue, or unconsciously "helping" a variant) | The arm is never displayed (§5.2); interleaving distributes drift; the `spread_db` floor on the margin (§6.4 rule 1) means an effect smaller than the speaker's own repeat-to-repeat variation can never accept. |
| **PipeWire profile switching**: a mono open may move the node to a different profile that then persists into the next take | Every take re-negotiates from a fresh `Recorder`, and `negotiated_channels`/`rate_hz` are recorded per take; a persistent switch shows up as an arm-A take negotiating something other than 2 channels, which `score` reports and which invalidates the pairing (exit 2, `arm_b_negotiated_stereo` / its arm-A twin). |
| **The array refuses mono** (`-9998`) | Detected in `probe` (§5.1) *before the human is called*; the plan is abandoned with `reason: mono_unsupported` and zero human time spent. |
| **Mono is a duplicate of channel 0** | The expected null result; rule 1 denies, and the report quantifies the delta. |
| **Mono routes through AGC / echo-cancel**: hotter but noisier or spectrally mangled | Guard 2 (`snr_db_mean`), guard 4 (`wer_mean`) and guard 7 (`trailing_junk_rate`). A hotter capture that decodes worse cannot accept. |
| **Clipping**: a much hotter mono path could clip on loud passages | `score` reports a per-arm `clip_rate` (fraction of takes whose peak sample ≥ 0.999) in the table; any non-zero arm-B `clip_rate` with a zero arm-A rate is called out in the verdict line, and guard 4 catches the decode damage. |
| **The 30 % capture gain is changed mid-session** | The briefing forbids it; `floor_dbfs` per take makes a step change obvious in the report. |
| **Sample size**: 24 clips per arm resolves WER to ≈0.01 and a rate to ≈0.04 | Which is why WER and junk are *guards with slack*, not the target; the target is a level, which 24 paired takes resolve to well under 1 dB. The rule never claims a decode improvement — only that decode is **not made worse**. |
| **A soft passage is read at a different softness in each arm** | Paired by passage, two repeats, and the arm-first order alternates by repeat; the soft slice is reported separately so an implausible split is visible. |
| **The result generalizes only to this machine** | Stated: X01 answers a question about *this* array. Accepting changes a global default on that evidence, which §9 flags for the owner's judgement and the acceptance gate re-tests end-to-end. |

**Invariant checklist** (`HARNESS.md` §9, restated):

- **No transcript text** anywhere but `clips.jsonl` under `build/`.
  `x01_record.py` installs no logging, so nothing reaches `stenographer.log`;
  `manifest.json` carries the *passage* (reference text from this file, under
  gitignored `build/`), never what was actually said; `verdict.json`,
  `report.md`, stdout and everything under `docs/experiments/` are numbers
  only. The `x01` per-clip block is numeric. `AGENTS.md` hard rule 6 is
  untouched: no production logging changes.
- **No network in the ASR path.** `Model` keeps `local_files_only=True`
  (`model.py:87`); the in-process engine is used; X01 downloads nothing at
  all, so it does not even extend the permitted-download sentence.
- **No platform imports.** `x01_record.py` imports `stenographer.audio`,
  `stenographer.audio_probe`, `stenographer.config` and `soundfile` only —
  never `stenographer.platform.linux`, `evdev`, `fcntl`, or any name in
  `tests/platform/test_core_isolation.py`'s `BLOCKED` tuple. Add
  `scripts/x01_record.py` to that test's source grep alongside the three
  harness scripts.
- **Platform boundary.** The seam is a plain keyword argument on a core class
  with a stdlib-typed value; `sounddevice` is already core's dependency and
  already reached from `audio.py`. No `Platform` Protocol method is added, and
  `platform/windows/` is untouched (§9).
- **Test policy** (`AGENTS.md` hard rule 4): `schedule`, `clip_id`,
  `noise_floor_dbfs`, `snr_db`, the dB conversions, `arm_split`, the
  aggregates and `x01_decide` are pure and tested with seen-to-fail tests on
  synthetic arrays and synthetic record dicts. **Nothing mocks
  `sounddevice`, `Recorder`, `soundfile` or the model** — the recording path
  is exercised by actually recording, which is the whole point of the plan.
- **Fixed behaviour stays fixed.** No `DecodeOptions` field is used; no config
  key is added; user config still has exactly 23 keys in 4 sections.
- **Venv only**, SPDX header on `scripts/x01_record.py` and
  `tests/test_x01_record.py`, ruff clean, line length 100, py312 syntax.

## 9 Deliverables & follow-through

**Always** (regardless of verdict): `scripts/x01_record.py`,
`tests/test_x01_record.py`, `docs/experiments/variants/X01/x01-user.json`,
`docs/experiments/variants/X01/thresholds.json`, the `Recorder.channel_order`
seam and its pinning test, `scripts/x01_record.py` added to
`tests/platform/test_core_isolation.py`'s grep, and the `--manifest` flag on
`asr_experiment.py run` if it was not already there (fork F3). The seam and
the `--manifest` flag are behaviour-preserving and land whether or not the
experiment accepts.

In the **same commit as the seam**, add one sentence to the `AGENTS.md`
architecture map's `audio.py` row naming `Recorder(channel_order=)` as a
dev-only injection seam whose default is the shipped negotiation order and which
only `scripts/` may construct with a non-default value — the same treatment
`DecodeOptions` gets in the `transcribe/` row (`HARNESS.md` §3.2). That sentence
is owed by the seam, not by the verdict, so it lands even if X01 denies; item 5
below is the *separate* edit the accepted change would make to the same row.

**On accept:**

1. `src/stenographer/audio.py:30` — `_FALLBACK_CHANNELS: tuple[int, ...] =
   (1, 2)`, with a comment giving the measured dB delta and the run id.
2. `src/stenographer/audio.py:145-152` — the `Recorder` class docstring says
   "negotiating channels and sample rate down the fallback lists"; extend it
   to say mono is tried first and why (the device's own downmix is hotter than
   one capsule on an array).
3. `src/stenographer/transcribe/pipeline.py:136-145` — `downmix`'s docstring
   stays **correct and unchanged**: channel 0 is still what is kept; on a mono
   open it is simply the only channel. Do not weaken that paragraph — it is
   the reason the average was rejected.
4. `tests/test_audio.py` — currently asserts **nothing** about channels (its
   17 tests cover device-string normalization, the gate and the resampler), so
   nothing breaks. Add the pinning test:
   `Recorder(device=None, max_seconds=1)._channel_order == (1, 2)` after the
   change, mirroring `HARNESS.md` §3.2's `DecodeOptions` pinning idea —
   changing the shipped order then means editing the test, which is the point.
   Pure attribute read; no PortAudio, no mock.
5. `AGENTS.md` — the architecture map's `audio.py` row reads "retained
   pre-negotiated stream, block-copy callback…, sample-rate fallback +
   resample"; change "sample-rate fallback" to "mono-first channel and
   sample-rate fallback". This is a settled-decision edit and must land **in
   the same commit** as the code (`AGENTS.md` preamble).
6. **Windows:** unaffected. Channel negotiation is core and `sounddevice` is
   cross-platform; `platform/windows/` has no audio surface to change. Note in
   the commit body that WASAPI shared-mode devices commonly refuse mono —
   `(1, 2)` degrades to the stereo open on those, which is exactly today's
   behaviour, so the Windows path cannot regress. `docs/windows/SCOPE.md`
   needs no edit.
7. **Re-baseline:** none. `docs/experiments/baseline.json` is decoded from
   files and never touches negotiation; `HARNESS.md` §7.3's four triggers are
   all unmet.
8. **Acceptance gate** (`AGENTS.md`, before dev → main, on the real machine):
   `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest` green; real dictation
   end-to-end in `hold`, `toggle` and `hybrid`; and — the capture-affecting
   gate — a cold-start dictation that retains its opening words, with
   `stenographer.log` showing `recorder: prepared ... channels=1` and metrics
   but no transcript or audio content. ≈10 minutes of the owner's time.
9. Set this file's Status to `accepted (<date>)` and append an Outcome section
   with the verdict line and the run id. Numbers only.

**On deny:** append the unnumbered `## Outcome` section (`HARNESS.md` §10) with
the verdict line and the run id,
copy `verdict.json` to
`docs/experiments/results/X01-<run-id>.json`, set Status to `denied (<date>)`,
and leave `audio.py:30` alone. Keep the arm-C diagnostic table in the Outcome:
a denied X01 that shows two strongly correlated capsules is the direct
motivation for the follow-up in §10, and a denied X01 that shows an
anti-correlated pair closes that door permanently. Numbers only.

**On abandon** (`mono_unsupported` / `device_is_mono` from §5.1): Status
`abandoned (<date>)`, with `probe.json`'s numbers in the Outcome. No human
time was spent.

## 10 Out of scope

- **Averaging the channels** (`indata.mean(axis=1)` in `audio.py:328` and
  `downmix` in `pipeline.py:136-145`). X01 only *measures* it, on arm C, and
  never changes it. If arm C shows strongly correlated capsules and a mean
  that is meaningfully hotter than channel 0 at equal or better SNR, that is a
  new plan (**X02 — channel mean vs channel 0**), reusing this session's
  2-channel diagnostic takes plus a short follow-up session; it must argue
  against `downmix`'s stated cancellation risk with numbers.
- **VAD parameters.** `vad_threshold`, `min_silence`, `speech_pad` are `Q02`;
  X01 changes what the VAD is fed, not how it is tuned, and reports
  `vad_zero_rate` only as a guard.
- **The energy gate.** `audio.min_speech_rms` is user configuration and was
  passing already; X01 does not propose changing it.
- **Microphone gain / ALSA mixer / PipeWire configuration.** Machine settings,
  not code; the session deliberately holds them fixed at the owner's normal
  30 % so the result describes the machine as it actually runs.
- **Sample-rate fallback order.** `_FALLBACK_SAMPLE_RATES` (`audio.py:29`) is
  untouched; this machine already negotiates 16 kHz on the first try.
- **`audio.input_device` selection**, and any comparison across microphones —
  one device, the default, for the whole session.
- **Windows channel behaviour.** No Windows audio backend exists to measure
  (`AGENTS.md` platform boundary; `docs/windows/SCOPE.md`).
- **Cue bleed and leading-silence effects** (`Q10`), trailing-silence
  hallucination (`Q07`, `Q09`, `Q11`), and every decode-side parameter — X01's
  variant is the shipped decode, unchanged, in both arms.
