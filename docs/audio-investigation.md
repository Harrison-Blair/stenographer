# Audio investigation — 2026-09-06

Scope: investigate appended phrases and missing opening words on a cold model
load; compare experimental changes before the owner chooses an implementation.
No production fix, installed daemon change, or configuration change is authorized
by this report. Model loading remains press-lazy.

## Current conclusion

Neither reported failure has yet been reproduced reliably. Model loading did not
lose opening words in the direct-worker or isolated virtual-capture trials.
This does **not** exclude a physical microphone wake-up problem, acoustic cue
interference, or speech being discarded/misrecognized by VAD/ASR.

## Safety and method

- Public speech only: [OpenSLR LibriSpeech](https://www.openslr.org/12/), CC BY 4.0,
  obtained through the Hugging Face `openslr/librispeech_asr` dataset rows API.
  Fixtures were downloaded into memory during experiment preparation, not by the
  application ASR path. No personal microphone recording or speaker playback.
- Cached `faster-whisper-medium.en`, int8, CUDA selected automatically;
  faster-whisper 1.2.1, CTranslate2 4.8.1, sounddevice 0.5.5. ASR used
  `local_files_only=True` and `HF_HUB_OFFLINE=1`.
- Application source and live settings were unchanged. The installed service
  remained active with PID 3935. Pre-existing deleted experiment documents and
  untracked `.fledge/` content were left alone.
- Temporary experiment scripts live in
  `/tmp/stenographer-audio-study.Q5FJYW/`. They are diagnostic runners, not a new
  application command or shipped host backend. Temporary files are not durable
  repository assets. They emit structural/numeric results, not transcripts.
- Word errors use lowercase tokenization and Levenshtein distance. “Exact opening”
  means the first four reference tokens (or all tokens for a shorter reference).
  “Tail insertion” is a right-edge alignment proxy, **not** a semantic hallucination
  detector. Number/name spelling variations can count as recognition errors.
- Variants and transformed versions of one recording are correlated observations,
  not independent speakers or statistically conclusive trials. Decode timings in
  the first screen were not randomized; they do not establish speed improvements.

## Initial decode comparison

Six `clean/test` offsets: 0, 400, 800, 1200, 1600, 2000. Each used original audio,
three seconds of trailing silence, three seconds of Gaussian noise at RMS 0.002,
and an opening attenuated tenfold. Four profiles × six clips = 24 cases/variant,
468 reference tokens. Gaussian generator seed: 41.

| Variant | Word errors | Tail insertions | Exact openings |
| --- | ---: | ---: | ---: |
| Current settings | 33 | 0 | 16/24 |
| Beam 5 | 47 | 0 | 16/24 |
| Hallucination-silence threshold 1 s | 33 | 0 | 16/24 |
| VAD threshold 0.35 | 33 | 0 | 16/24 |
| VAD padding 500 ms | 29 | 0 | 16/24 |
| VAD disabled, diagnostic only | 29 | 0 | 16/24 |

Held-out `other/test` offsets: 100, 500, 900, 1300, 1700, 2100. Same profiles,
but noise RMS 0.01; 24 cases/variant, 372 reference tokens.

| Variant | Word errors | Tail insertions | Exact openings |
| --- | ---: | ---: | ---: |
| Current settings | 37 | 0 | 4/24 |
| Hallucination-silence threshold 1 s | 37 | 0 | 4/24 |
| VAD padding 500 ms | 40 | 0 | 5/24 |

All 216 decodes completed without an empty result or output-validation failure.
Wider VAD padding helped the first group but worsened held-out total errors; it
is not a demonstrated general fix. A shorter hallucination-silence threshold
did not improve the metrics. Disabling VAD removes a protection and is not a
recommended production change.

## Direct worker cold/warm/reload comparison

Three public clean clips (offsets 0, 800, 2000) were supplied as identical numpy
waveforms to real ASR worker processes. A background warm-up overlapped the cold
request. A one-second idle-unload setting applied only to these experiment workers
allowed real unload/reload testing.

All nine transcriptions matched normalized reference text exactly; cold, warm,
and reloaded results were identical for each clip. Cold requests took about
4.9–6.8 seconds, warm requests 0.34–0.73 seconds, reload requests 4.8–5.3 seconds.
These timings include worker/model setup as applicable. They say nothing about
audio lost before the supplied waveform reaches the worker.

## Real PortAudio capture through isolated virtual audio

Runner: `capture_study.py`, with `public_helpers.py` and `alsa.conf` beside it.
Run with the repository venv on the real Linux desktop, not as a mocked test.

A temporary PipeWire loopback exposed a virtual sink/source pair with low session
priority and no autoconnection. Only the experiment's ALSA PCM explicitly targeted
these endpoints. Stream properties disabled fallback, reconnection, and movement.
Actual graph links were inspected to confirm every endpoint touching an experiment
node belonged to the experiment. Desktop default metadata was byte-identical before
and after; owned streams and loopback process were closed at completion.

The routing uses PipeWire's documented [loopback facility](https://docs.pipewire.org/page_module_loopback.html)
and [explicit-target/fallback properties](https://docs.pipewire.org/page_man_pipewire-props_7.html).

The original `Recorder` ran through real sounddevice/PortAudio. An experiment-only
subclass captured the first callback's clock and ADC timestamp, then delegated to
the original callback. No signal analysis ran in the input callback. A control
recorder was already active; a virtual output stream supplied the known public
waveform at the simulated press. A real worker loaded after recording began on
each cold trial. Analysis and recognition ran after capture stopped.

| Public clip | Model state | Activation ms | First callback ms | Word errors |
| --- | --- | ---: | ---: | ---: |
| 6930-75918-0000 | Cold | 0.40 | 10.90 | 0 |
| 6930-75918-0000 | Warm | 0.31 | 11.10 | 0 |
| 6930-75918-0000 | Warm repeat | 0.34 | 12.84 | 0 |
| 1580-141083-0051 | Cold | 0.26 | 7.52 | 0 |
| 1580-141083-0051 | Warm | 0.30 | 10.06 | 0 |
| 1580-141083-0051 | Warm repeat | 0.31 | 8.41 | 0 |

All six retained exact opening words and reported no overflow. Whole-waveform
cross-correlation found no negative source offset indicating a missing prefix;
measured waveform correlation was 0.933–0.999. Alignment sanity checks recovered
an intentionally added 50 ms prefix and an intentionally removed 100 ms prefix.

Limitations: only two speech clips and two cold loads; the virtual producer and
control capture keep the audio graph active. Virtual transport added approximately
43–63 ms before the supplied waveform in the measured capture. This is **not** a
physical-microphone cold-start test, does not establish sample-perfect capture,
and bypasses the daemon's actual hotkey/cue/overlay orchestration.

Two initial attempts exited with code 134 before valid capture measurements. They
are excluded. The successful run included standard ALSA definitions in the
process-local test configuration; the native-abort cause was not established.

## Expanded ending stress test

Eight public clips: clean offsets 0, 400, 1600, 2000 and other offsets 100, 500,
900, 1700. Eight profiles per clip: 15 s silence; 15 s smoothed Gaussian noise at
RMS 0.002 and 0.02; a fading last second followed by noise; speech scaled by 0.1
or 0.01 followed by noise; noise added throughout speech followed by noise; and
45 s silence. The noise generator used seed 20260906. Each same waveform was
decoded with all three variants (192 decodes, 64 cases and 632 reference tokens
per variant). A dataset-server HTTP 500 interrupted preparation after six clips;
the remaining two were completed separately, preserving generator progression.

| Variant | Word errors | Tail insertions | Empty results |
| --- | ---: | ---: | ---: |
| Current settings | 144 | 0 | 3/64 |
| Hallucination-silence threshold 1 s | 152 | 0 | 3/64 |
| Beam 5 | 134 | 0 | 3/64 |

No output-validation failures occurred. These deliberately degraded inputs did
produce recognition errors and empty results, but no tail insertions by the
alignment proxy. Shortening the hallucination-silence threshold worsened total
errors; beam 5 improved this screen but worsened the earlier clean screen. Neither
has demonstrated prevention of the owner's appended-phrase problem. An empty
result is not counted as successful recognition or as a successful hallucination
fix. No blanket suffix-removal rule was deployed or claimed to be validated.

Runner and numeric results: `ending_study.py` and `ending-results.jsonl` in the
temporary study directory. `STUDY_RESUME=1` skips completed first-six-clip decodes;
the combined result file contains each of the 192 cases once.

## Leading-context candidate

Runner: `opening_study.py`; numeric results: `opening-results.jsonl` in the
temporary study directory. The same 12 clips from the initial and held-out
screens were decoded as original audio and with a tenfold-attenuated first
second. Each waveform received either no added prefix, 100 ms of zeros, or
500 ms of zeros before the existing Model/VAD path: 72 decodes, 24 cases per
variant, 420 reference tokens. This adds artificial silence to already-captured
audio; it cannot recover microphone samples that were never recorded.

| Group / variant | Word errors | Exact openings |
| --- | ---: | ---: |
| Clean / current | 16 | 8/12 |
| Clean / 100 ms prefix | 16 | 8/12 |
| Clean / 500 ms prefix | 15 | 8/12 |
| Other / current | 19 | 2/12 |
| Other / 100 ms prefix | 19 | 3/12 |
| Other / 500 ms prefix | 16 | 3/12 |

All results were nonempty and passed output validation; no tail insertions were
detected. A 500 ms prefix reduced errors from 35 to 31 and improved exact openings
from 10/24 to 11/24. This is a small promising signal, not proof of a cold-start
fix: the reported bug was not reproduced, only one additional opening became
exact, and these clips were already used in earlier comparisons. There is no
independent acceptance corpus for this candidate yet. It has not been tested
against the expanded ending-stress corpus, so its hallucination tradeoff is unknown.

A production implementation would need to account for timestamp offsets,
real-vs-synthetic duration/token-budget semantics, and empty/silent input. It
should not introduce a half-second sleep or a pre-recording microphone buffer.

## Verification and next decision

The focused audio/model pure suites passed: 50 tests. An earlier broader focused
run passed 110 tests. These validate existing pure behavior, not real dictation or
the still-unreproduced reports. No release acceptance gate is claimed.

The recommended next production change is privacy-safe timing diagnostics:
time from accepted press to first callback, first-block timing relative to stream
activation, and VAD's retained audio boundaries. This would help distinguish
capture startup from recognition trimming during normal use without storing
transcript text or audio. It is a diagnostic proposal, not an implemented fix.
An alternative the owner can choose is a limited trial of the 500 ms artificial
prefix, with the uncertainty above made explicit. No candidate is selected or
implemented on the owner's behalf.

Do not deploy a generic last-sentence filter: it could remove genuine dictated
sentences. Do not add startup model preload, always-on microphone capture, or
audio pre-roll without a separate owner decision. A real microphone reproduction
may still be necessary, with explicit consent and a short scripted utterance.
