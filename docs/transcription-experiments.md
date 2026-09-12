<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Transcription-quality experiments

Campaign: 2026-09-12. Scope: public recordings, offline recognition, a two-hour
initial screen, and at most 20 GB of explicit downloads. Deliverables are this
report and reproducible diagnostic runners. The installed daemon, application
code, microphone settings, and user configuration are outside the experiment's
write scope. Physical microphone trials are specified below but not authorized
for this campaign.

## Findings

The first settings screen found no reliable improvement: the best profiles
removed only one error from 302 reference words. All 360 comparisons completed
without gate rejection, decode failure, or output-validation failure. Raw
decoder, accepted, and formatted scores were identical in every comparison, so
the application's extra filtering and formatting did not cause these errors.
The model and held-out follow-ups are complete. The strongest measured candidate
is large-v3-turbo; no production default was changed.

The saved baseline uses `Systran/faster-whisper-medium.en`, int8, beam 1,
English decoding, VAD threshold 0.5 with 250 ms padding, a 0.0005 input energy
gate, and a 0.6 no-speech threshold. Refinement is enabled. Read-only inspection
reported input volume 0.30, stereo capture, eight physical CPU cores, and about
31 GiB RAM. CUDA is hidden inside the sandbox; an approved read-only check
outside it found one RTX 3080 Laptop GPU with 8 GiB VRAM, driver 595.84. File-based
ASR experiments run outside the sandbox to access that device, with the actual
backend recorded per run. No driver changes were needed. The input volume alone
does not establish inadequate microphone gain.

### Settings screen: 24 development clips

All profiles used the same 12 conversational, six clean, and six difficult
utterances. Times are observed median decoder durations, excluding the worker's
first attempted decode; these are single passes, not repeated latency trials.
One loaded model executed profiles in a seeded randomized order.

| Profile | Substitutions / deletions / insertions | WER | Exact clips | Median decode, s |
| --- | --- | --- | --- | --- |
| Current baseline | 15 / 16 / 3 | 11.26% | 11/24 | 0.383 |
| Beam 3 | 14 / 16 / 3 | 10.93% | 13/24 | 0.414 |
| Normalize to -24 dBFS | 14 / 16 / 3 | 10.93% | 11/24 | 0.363 |
| VAD padding 500 ms | 14 / 16 / 3 | 10.93% | 12/24 | 0.360 |
| VAD disabled, diagnostic | 13 / 17 / 3 | 10.93% | 12/24 | 0.336 |
| Digital gain -6 dB | 13 / 19 / 2 | 11.26% | 10/24 | 0.360 |
| Digital gain +6 dB | 16 / 15 / 4 | 11.59% | 11/24 | 0.371 |
| Digital gain +12 dB | 15 / 16 / 4 | 11.59% | 10/24 | 0.356 |
| VAD threshold 0.35 | 15 / 17 / 3 | 11.59% | 11/24 | 0.354 |
| Artificial 500 ms prefix | 13 / 18 / 3 | 11.26% | 10/24 | 0.361 |
| Repetition blocking disabled | 15 / 16 / 3 | 11.26% | 11/24 | 0.342 |
| Energy gate disabled | 15 / 16 / 3 | 11.26% | 11/24 | 0.338 |
| Energy gate 0.0001 | 15 / 16 / 3 | 11.26% | 11/24 | 0.373 |
| Decoder no-speech threshold 0.9 | 15 / 16 / 3 | 11.26% | 11/24 | 0.373 |
| Application no-speech threshold 0.9 | 15 / 16 / 3 | 11.26% | 11/24 | 0.339 |

Baseline WER by corpus: AMI 22.64%, clean read speech 3.30%, difficult read
speech 6.67%. Beam 3 improved two clips and worsened one; normalization improved
four and worsened three. All four best profiles' group-bootstrap intervals
included zero improvement. Normalization helped AMI but worsened difficult read
speech. None establishes a generally better default.

Clipping protection limited +6 dB to an actual 2.06–6 dB and +12 dB to
2.06–12 dB (median 8.61). Normalization often *attenuated* the audio: median
-4.20 dB, range -9.19 to +12 dB. These are measured digital transformations,
not tests of changing the microphone's hardware gain. Total decoder time was
144.0 seconds; the worker's lifetime peak RSS was 1.736 GB, excluding GPU memory
and the separate Ollama server. Small observed timing differences between
quality-identical profiles should not be interpreted as established speedups.

### Refinement pilot: 12 development clips

The 12 clips contained 169 reference words and 61.935 seconds of audio. Raw,
accepted, and formatted output each had 22 errors (10 substitutions, ten
deletions, two insertions), WER 13.02%. Refinement reduced this to 19 errors,
WER 11.24%, entirely through one difficult LibriSpeech clip. Conversational AMI
WER remained 25.40%; exact-utterance accuracy remained 5/12 overall.

Seven refinements applied and five were skipped; none failed or timed out. One
correct negation was recovered and none lost. There were no numeric literals
and no independently annotated names in the evaluated protected-token panel,
so number/name preservation is not established. One AMI reference had 12 words,
but ASR omissions produced fewer than ten input words and refinement correctly
skipped it under the current threshold. Verbatim WER cannot independently
evaluate intentional cleanup or semantic correctness.

Warm ASR median was 0.423 seconds. Applied-only refinement median was 1.588
seconds; its first request took 8.086 seconds, with loading overhead not
separately measured. The configured local model was `gemma4:e2b`, Ollama 0.32.6,
digest `7fbdbf8f5e45a75bb122155ed546e765b4d9c53a1285f62fd9f506baa1c5a47e`.
ASR-only timing comparisons exclude these refine calls.

### Paired microphone recordings: 30 development utterances

The same 306 reference words were recorded simultaneously on an individual
headset and a distant array microphone. Reference checksums, clip boundaries,
configuration, model, runtime, and executed-source metadata were checked before
pairing. The near baseline run evaluated all 60 development clips; this table
uses only the 30 matching AMI clips. The distant run evaluated 30 clips under
four profiles. All 180 jobs completed successfully.

| Recording/profile | Raw WER | Accepted WER | Accepted substitutions / deletions / insertions | Empty results |
| --- | --- | --- | --- | --- |
| Near headset | 19.61% | 19.61% | 15 / 44 / 1 | 1/30 |
| Distant array | 51.96% | 52.94% | 34 / 125 / 3 | 7/30 |
| Distant +6 dB | 47.71% | 48.69% | 30 / 114 / 5 | 6/30 |
| Distant +12 dB | 42.48% | 43.79% | 33 / 95 / 6 | 6/30 |
| Distant bounded normalization | 42.48% | 43.79% | 33 / 95 / 6 | 6/30 |

Compared with near capture, distant capture worsened 21 utterances, improved two,
and tied seven. Adding 12 dB improved nine distant utterances, worsened four, and
tied 17. The best distant profile still had 24.18 percentage points more errors
than near capture. The requested +6/+12 dB gains were fully applied without
clipping. Normalization applied 7.92–12 dB and reached its cap on 28/30 clips.

No energy-gate rejection occurred. Additional application filtering slightly
worsened the distant results; formatting added no lexical errors. Most of the
gap was already present in the decoder output, which includes upstream VAD.
This comparison bundles microphone type, placement, acoustics, and signal level:
it cannot isolate hardware gain or diagnose the user's microphone. It covers
one meeting/four speakers, so between-meeting confidence intervals are unavailable.

### Stress controls and larger development confirmation

The stress panel contains four source utterances, each with a three-second
silent tail, a quiet (-20 dB) version with that tail, and a 10 dB SNR noisy
version with that tail. Its 12 speech cases repeat 216 reference words and are
correlated by source. Four additional controls contain silence, noise at two
levels, and clicks, with empty references. All 16 controls were evaluated under
eight profiles (128 jobs).

| Profile | Speech errors / 216 words | Speech WER | False speech on nonspeech controls |
| --- | --- | --- | --- |
| Baseline | 44 | 20.37% | 0/4 |
| Bounded normalization | 30 | 13.89% | 0/4 |
| VAD disabled, diagnostic | 32 | 14.81% | 0/4 |
| +12 dB | 35 | 16.20% | 0/4 |
| VAD padding 500 ms | 40 | 18.52% | 0/4 |
| Energy gate disabled | 44 | 20.37% | 0/4 |
| VAD threshold 0.35 | 46 | 21.30% | 0/4 |
| Beam 3 | 51 | 23.61% | 0/4 |

Normalization reduced quiet-case errors from 15 to six; beam 3 increased them
to 21. No speech case was rejected by the energy gate. Fourteen gate rejections
were correct nonspeech decisions; the gate-disabled control still produced no
false words. This small panel does not establish general hallucination safety.
Synthetic nonspeech selection received a regression fix before these runs;
the runner now rejects unsupported corpus labels rather than silently dropping
them. Earlier speech-only selection is unchanged; source hashes identify each
run version.

The follow-up evaluated baseline and three candidates on all 60 development
utterances (741 words, 240 jobs), including the earlier screen's examples:

| Profile | Word errors | WER | Median warm decode, s |
| --- | --- | --- | --- |
| Baseline | 94 | 12.69% | 0.359 |
| Bounded normalization | 79 | 10.66% | 0.370 |
| Beam 3 | 84 | 11.34% | 0.401 |
| VAD padding 500 ms | 86 | 11.61% | 0.350 |

Normalization improved nine clips and worsened four. It reduced AMI errors
60 to 51, left clean read-speech errors at eight, and reduced difficult
read-speech errors 26 to 20. Most of its gain was fewer deletions (53 to 39).
Its paired WER difference was -2.02 percentage points, with a group-bootstrap
95% interval of -4.17 to +0.45 points. This is a promising development result,
not independent validation. No digit-form reference numbers occurred anywhere
in the development corpus; numeric fidelity remains untested. All 240 jobs
completed successfully, with no additional filtering/formatting errors.

### Precision comparison: 60 development clips

Using the same medium.en checkpoint in GPU float16 instead of the observed
baseline int8_float16 reduced errors from 94 to 81/741 words (12.69% to 10.93%).
Four clips improved, one worsened, and 55 tied. Corpus error counts were
AMI 60 to 54, clean 8 to 6, and difficult read speech 26 to 21. Exact clips
increased 25 to 27. The paired WER difference was -1.75 percentage points,
with a group-bootstrap 95% interval of -4.08 to +0.21 points: promising, but
not a demonstrated general improvement.

Warm median decode was 0.380 seconds versus baseline 0.359 seconds in separate
single-pass runs; neither establishes repeatable latency. Peak process RSS was
1.733 GB, not GPU VRAM. All 60 jobs succeeded, and raw, accepted, and formatted
scores were identical. A separate float32 attempt failed during initialization
with `RuntimeError`, before producing scored rows. The GPU runtime advertises
float32 support; the failure is not evidence that float32 is unsupported or
less accurate. Its cause remains unresolved, and no driver or server changes
were made to pursue it.

### Model screen: 60 development clips

Three pinned Whisper candidates used the same preprocessing and CUDA
int8_float16 backend. The current-host medium.en control reproduced the earlier
94/741 baseline errors exactly. The kernel had changed, so only current-host
warm timings are shown. Normalization is listed separately for every model; it
is not assumed to transfer beneficially between checkpoints.

| Model/profile | Errors / 741 | WER | Exact clips | Median warm decode, s |
| --- | ---: | ---: | ---: | ---: |
| Current medium.en | 94 | 12.69% | 25/60 | 0.209 |
| Current medium.en + normalization | 79 | 10.66% | 25/60 | 0.212 |
| large-v3-turbo | 71 | 9.58% | 28/60 | 0.221 |
| large-v3-turbo + normalization | 75 | 10.12% | 28/60 | 0.220 |
| distil-large-v3 | 83 | 11.20% | 27/60 | 0.211 |
| distil-large-v3 + normalization | 75 | 10.12% | 28/60 | 0.212 |
| large-v3 | 82 | 11.07% | 25/60 | 0.364 |
| large-v3 + normalization | 75 | 10.12% | 26/60 | 0.364 |

Turbo without normalization improved 16 clips, worsened eight, and tied 36
against the current control. Its paired difference was -3.10 percentage points;
the group-bootstrap 95% interval was -7.55 to -0.68 points. Its 71 errors were
55 AMI, six clean, and ten difficult-read errors. Normalization made turbo four
errors worse, illustrating why the settings and model effects cannot simply be
stacked. Large-v3 with normalization also had a development interval excluding
zero (-5.91 to -0.87 points), but tied the 75-error alternatives and was much
slower. Distil and unnormalized large-v3 did not establish an improvement.

Before opening held-out audio, the frozen finalists were (1) current medium.en
with bounded -24 dBFS normalization, because it needs no checkpoint replacement
and helped quiet stress cases, and (2) unnormalized large-v3-turbo, because it
had the lowest development error count. The untouched current pipeline remains
the control and does not count as a tuned finalist. No choice will be revised
from held-out outcomes.

### Alternative native runtime: Moonshine development screen

Moonshine Voice 0.1.5 with its medium English streaming model (architecture 5)
ran CPU-only through its native VAD/output path. All 60 clips succeeded. It
produced 107/741 errors (14.44% WER) versus 94 (12.69%) for the application
control: 15 clips improved, 23 worsened, and 22 tied. The paired difference was
+1.75 percentage points, with a wide group-bootstrap interval of -3.81 to +4.35
points. Median decode was 0.986 seconds, p95 2.522 seconds, and cold load 0.342
seconds. This is not pipeline-parity timing—different devices, VAD, and runtime
are involved—but it supplies no development evidence to promote Moonshine to
held-out validation.

The three pinned Whisper component sets total 6,228,981,313 bytes. Moonshine's
eight verified assets add 269,141,623 bytes, and the source corpus downloads add
1,084,310,342 bytes: 7,582,433,278 bytes counted against the 20 GB allowance.
Model component provenance records exact revisions, sizes, and SHA-256 hashes.

### Frozen held-out validation: 60 clips

After the development screen, no settings were changed and the held-out split
was opened. It contains 906 reference words from disjoint selected speakers and
meetings. The current medium.en control scored 103 errors (11.37% WER; AMI 73,
clean 6, difficult 24). Its frozen normalization finalist scored 110 errors
(12.14%; AMI 78, clean 8, difficult 24): three clips improved, seven worsened,
and 50 tied, for a +0.77-point paired difference (group-bootstrap interval
0.00 to +1.27 points). Normalization therefore is not recommended as a default.

The frozen turbo finalist scored 80 errors (8.83% WER; AMI 64, clean 6,
difficult 10), with 30 exact clips and a 0.227-second warm median (p95 0.272 s).
Against the held-out medium control it improved 16 clips, worsened nine, and
tied 35: -2.54 WER points, with a group-bootstrap 95% interval of -4.89 to
-0.90 points. All 60 turbo jobs and all 120 medium jobs completed successfully;
raw, accepted, and formatted scores were identical, with no gate or validation
failures. The model result is encouraging across this small public proxy, but
one AMI meeting per partition limits generalization. No held-out result was
used to retune a setting.

## Corpus and experimental method

[AMI](https://groups.inf.ed.ac.uk/ami/download/) provides conversational English,
word annotations, and synchronized headset and distant-microphone signals under
CC BY 4.0. [LibriSpeech](https://www.openslr.org/12) supplies clean and difficult
read-speech controls under CC BY 4.0. Public material may have appeared in a
model's training data: held-out here means held out from this experiment's
tuning, not guaranteed unseen during model training.

The frozen corpus contains 120 source utterances: 60 development and 60 held-out, each with
30 AMI, 15 LibriSpeech clean, and 15 LibriSpeech other examples. Selection seed
is 20260912. Speakers and meeting groups are disjoint across partitions. AMI
ES2002a participants FEE005/MEE006/MEE007/MEE008 and ES2003a participants
MEE009/MEE010/MEE011/MEE012 are disjoint according to the official speaker
metadata. Nonoverlapping single-speaker turns avoid scoring another participant's
speech against the wrong reference. Microphone pairs and transformed copies
remain in the same partition and are not independent observations.

The pilot uses 12 development utterances (6/3/3); the screen uses 24 (12/6/6).
Candidates are frozen before evaluation on held-out audio. Dataset source files,
audio, references, manifest checksums, download accounting, and numeric results
remain under the ignored `.cache/transcription-study-20260912/` directory.
The preparation runner supplies provenance sufficient to reconstruct the corpus.
The primary manifest SHA-256 is
`4b3d215b384f6c73c13e266aca5d2f3bcfe46ae5aa2faf676aca02b582849ecc`.
Audio totals 609.445 seconds: 290.140 development and 319.305 held-out.
There are 31 groups per partition, including only one AMI meeting each. The
selected AMI sessions are not a claim of an official model-unseen test split.
The 60 additional distant-microphone variants preserve their source partition;
the 16 synthetic controls belong only to development. Three development and
two held-out AMI turns contain fewer than three lexical words.

The runner follows the actual daemon's channel-0 downmix, resampling, energy
gate, decoder settings, segment rejection, validation, and formatting. The file
CLI alone is not an equivalent test of rejection: it reports the energy gate
but transcribes the named file even when the gate fails. Raw decoder and accepted
output scores locate losses at different processing stages. Gate-rejected speech
counts as deletions, not correct silence. Failed recognition remains a failure.

Word error rate is `(substitutions + deletions + insertions) / reference words`,
aggregated by word count rather than averaged over utterances. Capitalization and
punctuation are normalized; lexical differences, repetitions, negations, and
number wording remain visible. Nonspeech has no WER denominator: false-positive
clips and inserted words are separate metrics. Opening/closing correctness is
an alignment/token proxy, not a semantic hallucination judgment.

Refinement is assessed separately. Intentional filler removal can increase
verbatim WER without damaging the desired written output. Without independent
cleanup references, its WER alone cannot establish better or worse cleanup.
References and hypotheses are consumed in memory during scoring; runners do not
print or persist transcript text, and never write application analytics history.

Comparisons use matched clips. Group-bootstrap intervals resample speakers or
meeting groups; a small number of meetings limits their generality. Screening
results are exploratory. Heavy ASR/refine workloads run sequentially, with model
load reported separately from warm processing. Every run records configuration,
code/corpus fingerprints, versions, actual device/precision, and failures.

## Experiment catalog

Statuses: **deferred** means specified but not run in this screen; **physical** requires a
separate real-machine microphone session; **diagnostic** denotes a control that
is not itself a production recommendation. Completed measurements are identified
in the findings above. A screened subset does not complete its whole family.
Parameter sweeps are separate comparisons against the
baseline, not an exhaustive Cartesian product.

### Audio and capture track

| ID | Comparison and question | Coverage |
| --- | --- | --- |
| A01 | Active input/port and explicit device vs system-default routing: is the intended microphone selected? | Inventory; physical comparison |
| A02 | Input volume 30/50/75/100%, measuring clipping and speech level at every step. | Physical |
| A03 | Hardware microphone boost off/low/medium independently of software volume. | Physical |
| A04 | Left vs right vs mean channels; silent channel and phase-cancellation sensitivity. | Deferred: prepared clips are mono |
| A05 | Fixed channel vs signal-selected channel using public multichannel recordings. | Paired headset/array proxy tested; selection deferred |
| A06 | Distances approximately 10/20/40 cm; angles 0/30/60 degrees; stationary vs normal head movement. | Physical |
| A07 | Desk contact vs isolated mount; fan/keyboard noise; reflective vs absorbent placement. | Physical |
| A08 | Built-in vs an available wired headset/USB mic; wired vs Bluetooth path. No purchases included. | Physical |
| A09 | OS processing bypass vs noise suppression, AGC, echo cancellation, beamforming, individually. | Physical |
| A10 | Source rates 16/44.1/48 kHz and mono/stereo; current resampler vs reference implementation. | Deferred |
| A11 | Native device rate, callback buffering, overflow, USB routing, and suspend/wake behavior. | Physical |
| A12 | Digital gain -12/-6/+6/+12 dB, recording clipping or reducing gain to avoid it. | -6/+6/+12 screened; -12 deferred |
| A13 | Bounded speech-RMS normalization -30/-24/-18 dBFS, maximum +12 dB boost, preserving silence. | -24 screened; other targets deferred |
| A14 | DC-offset removal and high-pass 60/100/150 Hz. | Deferred |
| A15 | 50/60 Hz notch on affected speech; low-pass 4/6/7.5 kHz sensitivity. | Deferred |
| A16 | Mild compression vs bounded automatic gain vs bypass. | Deferred |
| A17 | Spectral suppression vs RNNoise vs DeepFilterNet; include clean-speech regressions and resampling cost. | Deferred |
| A18 | Leading/trailing margins 0/100/250/500 ms; deliberately remove 50/100/200 ms as loss controls. | 500 ms silent prefix and 3 s tail screened; real boundary-loss sweep deferred |
| A19 | Public speech mixed with bundled cues near utterance boundaries at controlled levels. | Deferred |
| A20 | Actual cue on/off/volume, speakers vs headphones, and hotkey start/stop timing. | Physical |

Digital amplification cannot repair clipping or recover uncaptured speech.
Attenuation, synthetic noise, and reverberation probe specific signal conditions;
they do not create evidence about real mumbling or reduced articulation.
Noise-reduction candidates are documented by [RNNoise](https://github.com/xiph/rnnoise)
and [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet). A later OS trial
must inspect supported settings on the actual host, following its
[PipeWire processing documentation](https://docs.pipewire.org/page_module_echo_cancel.html).

### Speech detection and decoding track

| ID | Comparison and question | Coverage |
| --- | --- | --- |
| D01 | RMS gate 0/0.0001/0.00025/0.0005/0.001 on speech, short phrases, and clicks. | 0/0.0001/default screened; other thresholds deferred |
| D02 | VAD speech threshold 0.25/0.35/0.5/0.65. | 0.35/default screened |
| D03 | Minimum VAD speech duration 0/50/100/250 ms. | Deferred |
| D04 | End-of-speech hysteresis: default and narrower/wider gaps from the speech threshold. | Deferred |
| D05 | VAD padding 100/250/500/750 ms. | 250/500 screened |
| D06 | Minimum silence 250/500/1000 ms; maximum speech segments 15/30 s. | Deferred |
| D07 | VAD disabled and reference-boundary segmentation to locate recognition vs trimming losses. | VAD-off diagnostic screened; oracle segmentation deferred |
| D08 | Independently vary decoder and application no-speech thresholds 0.3/0.6/0.9; bypass as control. | 0.6/0.9 independently screened |
| D09 | Beam 1/3/5/8; patience 1/1.5/2; length penalty 0.8/1/1.2. | Beam 1/3 screened; other axes deferred |
| D10 | Repeated-ngram blocking 0/3/4, including genuine repeated phrases. | 0/3 screened; targeted repetition panel deferred |
| D11 | Current token budget vs doubled allowance within model limits; long/fast speech truncation. | Deferred |
| D12 | Current token suppression vs diagnostic relaxation. | Diagnostic, deferred |
| D13 | Temperature 0 vs staged fallback, repeated runs; log-probability/compression thresholds when fallback is active. | Deferred |
| D14 | No prompt vs fixed conversational/technical prompt; no hotwords vs development-only glossary and unrelated controls. | Deferred |
| D15 | Previous-text conditioning within long utterances and context reset behavior. | Deferred |
| D16 | Hallucination-silence threshold disabled/1/2/3 s; genuine low-confidence speech vs noise. | Deferred |
| D17 | Timestamp alignment and relaxed duration/word-density validation to locate false rejection. Invalid output remains failure. | Stage attribution screened; relaxed validation deferred |

The current energy gate accepts or rejects an entire recording: reducing its
threshold cannot fix individual misheard words in an already accepted recording.
The decoder and application currently share a no-speech threshold but apply it
differently; independent controls test which stage loses words. No prompt,
glossary, or adaptive threshold may be derived from held-out reference answers.

### Models, refinement, and combinations

| ID | Comparison and question | Coverage |
| --- | --- | --- |
| M01 | medium.en vs multilingual medium, large-v3, large-v3-turbo, distil-large-v3, with matched preprocessing. | medium.en, large-v3, turbo, and distil screened; multilingual medium deferred |
| M02 | Individually tune finalists on development data after the matched model screen. | One normalization interaction screened per candidate; broader tuning deferred |
| M03 | CPU int8 vs float32; GPU float16/int8_float16 only when supported; actual precision recorded. | GPU int8_float16/float16 screened; float32 init failed; CPU deferred |
| M04 | Threads 2/4/8; cold vs warm; same checkpoint through an alternative local runtime. | Warm/cold recorded; thread/runtime sweep deferred |
| M05 | Parakeet TDT and Moonshine native output, runtime/dependency costs, offline and platform compatibility. | Moonshine CPU screened; Parakeet deferred |
| M06 | Raw recognition vs formatting vs configured refinement; isolate changed names/numbers/negations and omissions. | Stage scores and small refine pilot complete; cleanup truth/numbers/names incomplete |
| M07 | Conservative refine prompts and available local refine models against independent cleanup references. | Deferred |
| M08 | Always-strong model vs selective retry for low-confidence/empty/suspicious output. | Deferred |
| M09 | Model disagreement/candidate selection; confidence calibration on development only. | Development selection complete; confidence calibration deferred |
| M10 | Public domain/accent adaptation, fine-tuning feasibility, vocabulary-aware rescoring. | Expanded research, deferred |
| X01 | Winning gain x VAD and denoising x model combinations. | Normalization × four models screened; denoising/VAD combinations deferred |
| X02 | Winning model x beam and recognition x refinement combinations. | Deferred |
| X03 | Remove one change at a time from a combined winner to establish contribution. | Single-variable controls complete; final ablation deferred |
| X04 | Silence, clicks, fan/babble/noise, fading speech, long silence tails, and reverberation controls. | Silence/clicks/noise/quiet/tails screened; fan/babble/fading/reverb deferred |
| X05 | Short words, fast speech, contractions, repetitions, names/numbers/negations, and long passages. | Incidental short/negation coverage; purpose-built panel deferred |
| X06 | Frozen finalists on disjoint held-out speakers/meetings; repeated warm timings. | Held-out validation complete; repeated timing deferred |

Candidate sources: [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[large-v3](https://huggingface.co/Systran/faster-whisper-large-v3),
[large-v3-turbo](https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo),
[distil-large-v3](https://huggingface.co/Systran/faster-distil-whisper-large-v3),
[Parakeet](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3), and
[Moonshine](https://github.com/moonshine-ai/moonshine). These are candidates for
measurement, not promises of greater accuracy or speed on this machine.

## Execution and reproduction

The coordinator freezes the corpus and scorer, schedules inference, and owns
the combined report. The initial three tracks covered audio/corpus preparation,
speech-detection/decoding, and models/refinement. At the user's request, replacement
subagents used Luna with xhigh reasoning for model comparisons and Moonshine;
the coordinator retained integration and validation responsibility. Heavy runs
are scheduled sequentially; any observed contention limits latency conclusions.
The initial campaign starts at 01:23:35 UTC; no new runs are launched
after 03:08:35 UTC, reserving the final 15 minutes for reporting. Downloads count
toward the 20 GB aggregate allowance. Runtime/provenance failures are explicit,
and completed numeric rows are checkpointed for resumption.

Between the initial settings work and model comparisons, the observed host
kernel changed from `7.0.0-30-generic` to `7.0.0-31-generic`. No host upgrade was
performed by this study. Concurrent edits also changed refinement-only source
files outside the study's scope. They were preserved, not adopted as experiment
fixes. ASR-only runs keep refinement disabled; their hashes identify the actual
source version. Original refinement pilot results apply only to its recorded
prompt/guard version. A refreshed current-host baseline is required for final
model comparisons; timings across these host states are not pooled.

Baseline first; then stage attribution, channels/gain, VAD threshold/padding,
beam 3, and repetition-blocking removal. Extend promising profiles to 24
development clips. Freeze at most two finalists before opening held-out results.
Further model sweeps, physical tests, and combinations receive an estimated
follow-up budget rather than silently extending the initial campaign.

Run from a source checkout with the project's development environment. Preparing
the public corpus is an explicit download; benchmarking never downloads or
captures audio. Existing model caches must be present. The runner reads the
current config (or `--config PATH`) without saving it, so compare its metadata
with the original study before interpreting a rerun as a replication.

```sh
.venv/bin/python -m scripts.transcription_study.corpus --download
.venv/bin/python -m scripts.transcription_study.corpus --controls
.venv/bin/python scripts/transcription_bench.py \
  --manifest .cache/transcription-study-20260912/manifest.json \
  --output .cache/transcription-study-20260912/reproduction-dev.jsonl \
  --split dev --limit 60 --profiles baseline,normalize_minus24,beam3,vad_padding500 \
  --max-seconds 1200
.venv/bin/python scripts/transcription_study/report.py \
  .cache/transcription-study-20260912/reproduction-dev.jsonl \
  --output .cache/transcription-study-20260912/reproduction-dev-summary.json
```

For the 24-clip settings screen use `--limit 24` and the profile names shown by
`--help`. For controls use `controls.json`, `--limit 16`, and the eight stress
profiles. For distant microphones use `variants.json`, `--split dev --limit 30`.
Precision uses `--compute-type float16`; refinement is separately opt-in with
`--refine`. Use a fresh output name per run. `--resume` skips completed matching
fingerprints and repairs only an interrupted final JSON row. The aggregator
rejects mixed configurations and duplicate observations; model/precision runs
must be summarized separately, then compared by matching clip and corpus hashes.

`scripts/transcription_study/download_models.py` downloads only the three pinned
Whisper checkpoints and writes component sizes and SHA-256 manifests. Pass
`--root .cache/transcription-study-20260912/models` and `--deadline` with an
explicit future ISO-8601 UTC deadline; optional `--name turbo`, `distil`, or
`large-v3` selects one. A benchmark then uses `--model` with the corresponding
completed local directory. No arbitrary checkpoint download is hidden in an
inference run. GPU timing must be done on a real CUDA-visible execution host;
the observed sandbox fallback is not a comparable GPU result.

## Verification and limits

The pre-change non-integration suite passed: 1,867 tests, five deselected.
New pure tests cover known scoring errors, empty references, silence false
positives, duplicate observations, matched references, partition separation,
and group-bootstrap accounting. The verified diagnostic tooling passes all
1,933 non-integration tests (five integration tests deselected), `ruff check .`,
`ruff format --check .`, and `stenographer --help`. CLI help falls back to stderr
logging because the sandbox cannot write the normal state log; it exits zero.

The mirrored Git/build allowlists contain 116 identical ordered patterns.
`python -m build --no-isolation` built the 0.13.0 source distribution and then a
wheel from that source distribution. `scripts/verify_distributions.py` passed.
Archive inspection found the study documentation and 12 diagnostic Python files
in the source distribution, no diagnostic scripts in the application wheel,
and no study cache, downloaded recordings, references, or models in either.

This campaign cannot demonstrate that the user's own less-articulated speech
is fixed. It can identify software changes worth trying and produce a precise
later microphone protocol. The study itself performs no microphone access,
speaker playback, native integration test, automatic deployment, or application
behavior change; unrelated concurrent worktree changes are not its deliverable.

## Follow-up budgets and physical protocol

These are proposals, not authorization to continue spending the initial budget:

- **Personal microphone trial: 45–60 minutes, no model downloads.** Requires
  explicit recording consent. Save the original input/port/volume/boost and
  processing settings. Use the same 12 short prompts twice per condition,
  in normal, comfortable speech rather than deliberate over-enunciation.
  Start with current placement and volume; compare positions at approximately
  10/20/40 cm, then volumes 30/50/75/100% at the best practical position,
  changing only one factor at a time. Check clipping and speech RMS before
  accepting a level. Finish by comparing available channels, any existing
  headset, and individual OS processing toggles. Randomize repeated conditions
  and include a return-to-baseline block to detect fatigue or speaking changes.
  Restore original settings afterward; adopt a change only after reviewing the
  paired scores and listening with the user's permission. Microphone type and
  placement remain separate from purely digital amplification.
- **Broader public validation: about three hours, up to 5 GB additional assets.**
  Expand conversational evaluation to several independent meetings per split
  before making a general default recommendation. Freeze finalists and include
  names, spelled/digit-form numbers, contractions, short acknowledgments, fast
  speech, and independently annotated reduced articulation. Publisher selection
  and transfer speed determine the achievable sample size; this is an estimate.
- **Remaining software families: about two hours with cached models**, with
  a separate explicit download allowance if denoisers or another runtime are
  selected. Prioritize boundary loss, channel selection on real stereo,
  normalization-target sensitivity, then VAD/model interactions. Do not run
  the entire Cartesian product or tune against this campaign's held-out set.

Rerecording after changing a microphone setting does not isolate that setting
unless speaking variation is controlled with repeated, randomized blocks.
Likewise, synthetic quiet/noisy speech is an acoustic stress test, not a proxy
that proves performance on actual mumbling. Personal audio should remain local,
be explicitly retained only as needed for the agreed study, and never enter
application logs or analytics history.
