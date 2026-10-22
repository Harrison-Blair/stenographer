<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Underdog Bark 3.0 Pro and Clean for stenographer: evaluation report

Task 26-bark-eval, 2026-10-21. Research only; no production file changed.
Base commit `f5a0fc86ca1650c9531df75e6a570f9783c7b3e8` (`dev`).

## Summary

- **Pro is clearly more accurate than the current turbo model.** Public corpus,
  1,647 reference words: Pro has 5.5 % WER and turbo 9.2 %. On AMI meeting
  speech Pro has 8.4 % and turbo 17.1 %.
- **Pro runs through sherpa-onnx with no new runtime dependency.** It needs a
  local int8 export (done here). That export matches transformers' accuracy on
  the corpus (5.3 % WER).
- **On CPU, Bark through sherpa-onnx int8 is about 18 times faster per 3 s
  phrase than turbo here:** about 0.3 s against 5.3-5.6 s, both busy and
  quiet. It also uses about 1.25 GB RSS against 2.06 GB. turbo's CPU time here
  is about 3 times the project's 2026-10-20 screen, and that gap is unresolved
  (§3c). Against the earlier figure, Bark is still 3-6 times faster.
- **Clean removes fillers reliably** (0 filler words in every run on the
  private excerpts; 1 filler word per run on the public corpus, against 36 in
  the references). On
  multi-speaker system audio, however, Clean keeps only 80 % of Pro's
  non-filler words and blanks 5-8 phrases that Pro transcribes. On the public
  corpus it keeps 98 %.
- **Timestamps are not a blocker for any of the models.** Diarization in
  live/Files uses VAD phrase times only. All Bark runs give valid word times
  from TDT token durations, Clean included: its word starts are within a
  median of 10 ms of Pro's.
- **Recommendation:**
  - Pro int8 through sherpa-onnx for Files and live.
  - Pro as the dictation candidate as well.
  - Clean only as an opt-in dictation model, after a consented microphone
    trial.
  - Do not add the transformers + torch runtime.

Details and limits follow. All numbers come from one machine on one day. CPU
timings were taken while other agents' test suites were also running (load
average 4-15).

## 1. Runtime path in stenographer

| Model | Format published | sherpa-onnx (no new dependency) | transformers + torch |
| --- | --- | --- | --- |
| Current: turbo | CTranslate2 `model.bin` | not applicable (faster-whisper + CTranslate2, already a dependency) | not applicable |
| Bark 3.0 Pro | BF16 `model.safetensors` (1,254 MB); Core ML; MLX config | **Yes, after a one-time ONNX export.** There is no usable published export: `joshthomasdev/sherpa-onnx-nemo-underdog-bark-3.0-pro-int8` returns HTTP 401 (removed or private), and no other sherpa export of Pro was found on the Hub on 2026-10-21. The local export here (`bench/export_pro_sherpa.py`) gives the NeMo TDT layout: int8 files total 655 MB, encoder 630.7 MB. | Yes. Stock `ParakeetForTDT`, no custom code. |
| Bark 3.0 Clean | `model.bark` (180 MB; ANS + LZMA entropy-coded levels, format `bark-levels-v3`) | **Yes.** sherpa-onnx cannot read `model.bark` itself. Conversion needs: (1) unpack the weights with numpy + lzma + constriction (`bark_loader.load_state_dict`); (2) load them into transformers `ParakeetForTDT`; (3) export the encoder, decoder and joiner with `torch.onnx.export` (opset 17) and the NeMo metadata; (4) quantize to int8 with `MatMulNBits`. Steps 2-3 need torch at conversion time, not at run time. The vetted third-party export `velddev/Underdog-Bark-3.0-Clean-sherpa-onnx@bdcbdca` does exactly this and was used here. | Yes, through `bark_loader.py`. Every load unpacks the weights again: 26-27 s and about 6 GB peak RSS on this machine. |

The two Bark exports have the same architecture. The int8 file sizes of my Pro
export and velddev's Clean export agree to within 300 bytes. Each export's
`tokens.txt` matches Pro's `tokenizer.json` BPE vocabulary in order, plus
`<blk>`.

**Installed size of the transformers path** (scratch venv, Python 3.14,
torch 2.14.1+cu130 from PyPI, transformers 5.20.2, constriction 0.5.0, plus
onnx and scoring tools):

| Part | Installed |
| --- | --: |
| Whole scratch venv | 6.1 GB |
| `nvidia/*` CUDA 13 libraries | 3,196 MB |
| `torch` | 1,185 MB |
| `triton` | 897 MB |
| transformers + tokenizers + safetensors + huggingface_hub + constriction | 146 MB |
| For comparison: stenographer's whole `.venv` | 1.4 GB (sherpa_onnx 38 MB, ctranslate2 60 + 75 MB libs, onnxruntime 58 MB) |

A CPU-only torch wheel would be much smaller; it was not installed or measured
here. With either wheel, the transformers path adds gigabytes to the PyInstaller
onedir bundle and a second inference stack. The sherpa path adds no package:
`packaging/stenographer.spec` already runs `collect_all("sherpa_onnx")`.

**GPU on the sherpa path:** the PyPI `sherpa-onnx` 1.13.8 wheel is CPU-only
(bundled onnxruntime 1.28.2, CPU provider). GPU use would need sherpa-onnx's
CUDA build. That was not installed or measured.

### Vetting of the third-party Clean export (summary)

Files were downloaded into a new, empty `.scratch/vet-velddev-clean/`. Nothing
from the repo was executed. All 12 sha256 values match the repo README.

- `convert-bark.py` is a build script. It creates a venv under
  `~/.cache/pond-miki`, installs from PyPI and download.pytorch.org, then runs
  `os.execv` into that venv. It downloads the pinned ConwayResearch files and
  writes under `~/.cache/pond-miki`. It runs `exec_module` on the downloaded
  `bark_loader.py` only with `--check-loader`, and on `bark-card.py` only with
  `--card`. It uses no pickle, no eval or exec strings, and no `torch.load`.
  It was not run.
- `bark-card.py` is string templating only (hashlib, pathlib).
- The ONNX files were parsed statically with onnx 1.23.2. They use opset 17 and
  the `com.microsoft` domain; the only non-standard op is `MatMulNBits`, a
  built-in onnxruntime contrib kernel. They contain no ONNX functions and no
  subgraphs. Only the fp32 encoder uses external data, all of it in
  `encoder.weights`: raw float32, no pickle or zip header, and the offsets end
  exactly at the file size.
- `tokens.txt`: 8,193 lines in `token id` form. `NOTICE` is byte-identical to
  ConwayResearch Clean's NOTICE. `LICENSE` is the CC-BY-4.0 legal code.
- With `model_type="nemo_transducer"`, sherpa-onnx reads only the three `.onnx`
  files (plus `encoder.weights` for fp32) and `tokens.txt`. Only the int8
  files and `tokens.txt` were loaded.

## 2. Fit per mode

What stenographer consumes from ASR today (`src/stenographer/lib`):

- **Live and Files:** `PhraseSegmenter` (`live/phrase_segmenter.py`) cuts
  phrases with Silero VAD, up to 25 s each. `TranscriptLine.start/end` and
  speaker assignment (`speaker_tracker.assign_embedding(...,
  duration=phrase.end - phrase.start)`) use **VAD phrase times only**
  (`live/live_session.py:519-545`, `files/engine.py:207-246`). Speaker
  relabelling (`live/relabel.py`) uses line start/end.
- **ASR timestamps** are used only by `transcribe/decode.py:_validate_output`
  (sanity check) and by the analytics word count (`transcribe/pipeline.py:85`).
- **Whisper-specific parts that a parakeet backend must replace:**
  `no_speech_prob` gating (`decode.py:75`, `live_session.py:522`), the
  faster-whisper built-in `vad_filter` used for dictation, and the
  `hotwords` and `initial_prompt` settings. TDT models have no
  `no_speech_prob`. sherpa-onnx gives `ys_log_probs` per token, which could
  serve as a confidence gate (not evaluated).

| Mode | Current turbo | Pro (sherpa int8) | Clean (sherpa int8) |
| --- | --- | --- | --- |
| Files | fits; slow on CPU (about 5.5 s per phrase, busy or quiet) | fits; best accuracy (AMI 7.8 %), RTF about 0.1 on CPU | weak fit: drops 20 % of non-filler words and some whole phrases on multi-speaker audio |
| Live phrases (2-10 s) | GPU: p50 343 ms; CPU: p50 7.3 s under load (falls behind real time) | CPU: p50 450 ms, p95 743 ms; load 1.9 s | CPU: p50 401 ms, p95 753 ms; load 2.0-2.3 s |
| Dictation | fits (current default) | fits; keeps fillers verbatim ("uh", "um"), as turbo mostly does not | designed for it; removes fillers, false starts and repeats; overlaps the refine stage. Not tested on microphone dictation |
| Diarization | unaffected (VAD times) | unaffected | unaffected |
| Timestamps given | segment and word (cross-attention alignment) | token (TDT frame of 80 ms + predicted duration), from which words are built | same as Pro. Removed fillers emit no tokens; the remaining words keep their frames. Median word-start offset to Pro is 10 ms (p90 90 ms) on 1,600+ matched words |
| Model load | 2.0-2.5 s CPU, 4.4 s GPU | 1.9-2.0 s | 2.0-2.3 s (velddev int8). With `bark_loader` + transformers: 26-27 s and about 6 GB RSS |

## 3. Accuracy and speed on this machine

**Hardware:**

- CPU: Intel Core i7-10875H, 8 cores, 16 threads.
- RAM: 31 GiB.
- GPU: NVIDIA RTX 3080 Laptop, 8 GiB, driver 595.91.07.
- OS: Ubuntu 24.04.5, kernel 7.0.0-38.

**Software:**

- Python 3.14.7.
- Production `.venv`: sherpa-onnx 1.13.8 (bundled onnxruntime 1.28.2),
  faster-whisper 1.2.1, ctranslate2 4.8.1.
- Scratch venv: torch 2.14.1+cu130 (cuDNN 9.24), transformers 5.20.2,
  constriction 0.5.0, onnx 1.23.2, onnxruntime 1.31.0.

**Models:**

- Pro `ConwayResearch/Underdog-Bark-3.0-Pro@4b5c51e04aa8d16dda9ecdff71bc29f7360149e4`.
- Clean `ConwayResearch/Underdog-Bark-3.0-Clean@6d34ed8639b2b9a33e764acf06748519bbb950cf`.
- Clean sherpa `velddev/Underdog-Bark-3.0-Clean-sherpa-onnx@bdcbdca05592e01e075a7a0179fe57ef0ccb50d5`.
- turbo: `dropbox-dash/faster-whisper-large-v3-turbo@0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`.
  This is the user's configured model and is already cached. The default
  `deepdml/faster-whisper-large-v3-turbo-ct2` is not on this machine, and
  downloading it was not authorised.

**Method:**

- Each configuration ran in a fresh process.
- Every configuration got the same 120 public clips and the same 230 private
  phrases.
- Pro was padded with 0.25 s of leading silence and Clean with none, as each
  model card states.
- turbo ran through stenographer's own `lib.transcribe.model.Model` with
  `Config.defaults().asr`: int8, beam 1, vad_filter on, word timestamps on,
  device auto.
- CPU runs used 8 threads.
- GPU runs:
  - Pro: BF16, the card's runner default.
  - Clean: FP32, the loader default.
  - turbo: int8 on CUDA.

**Workloads:**

- Corpus: `/home/penguin/source/stenographer/.cache/transcription-study-20260912`
  (read in place). 60 AMI headset turns from 2 meetings plus 30 LibriSpeech
  test-clean and 30 test-other utterances; 609 s and 1,647 reference words.
  Scored with `scripts/transcription_study/scoring.py` (lexical; ignores case
  and punctuation).
- Private excerpts: three 8-minute excerpts of
  `/tmp/system-audio-20261018-134825.wav` (system audio, 4 speakers), starting
  at 40, 160 and 280 minutes. They were downmixed and resampled to 16 kHz mono
  with soxr. Silero VAD then split them into 230 phrases with 793 s of speech
  (median 2.5 s; 107 phrases of 2-10 s). Settings: threshold 0.5, minimum
  speech 0.25 s, minimum silence 0.6 s, maximum 25 s.
- Substitution: the production `silero_vad.onnx` is not on this machine, and
  sherpa-onnx rejects faster-whisper's bundled Silero v6 ("Unsupported silero
  vad model"). The phrases were therefore cut with
  `faster_whisper.vad.get_speech_timestamps` (Silero v6) using the
  segmenter's parameters.

### 3a. Corpus WER (%) against verbatim references

| Run | AMI (695 w) | LS clean (520 w) | LS other (432 w) | All (1,647 w) | AMI, fillers removed from ref and hyp | Filler words in hyp (refs: 36) | Exact clips |
| --- | --: | --: | --: | --: | --: | --: | --: |
| turbo, CUDA | 17.12 | 2.31 | 4.63 | 9.17 | 13.18 | 2 | 58/120 |
| turbo, CPU | 17.99 | 2.69 | 4.86 | 9.71 | 14.09 | 2 | 55/120 |
| Pro, transformers CUDA BF16 | 8.35 | 1.92 | 5.32 | 5.53 | 8.48 | 29 | 71/120 |
| Pro, transformers CPU FP32 | 8.35 | 1.92 | 5.32 | 5.53 | 8.48 | 29 | 71/120 |
| **Pro, sherpa int8 CPU** | **7.77** | 1.92 | 5.56 | **5.34** | **7.73** | 32 | 70/120 |
| Clean, transformers CUDA FP32 | 14.24 | 2.31 | 6.02 | 8.32 | 9.70 | 1 | 58/120 |
| Clean, transformers CPU FP32 | 14.24 | 2.31 | 6.02 | 8.32 | 9.70 | 1 | 58/120 |
| Clean, sherpa int8 CPU | 15.25 | 2.12 | 5.79 | 8.62 | 10.91 | 1 | 52/120 |

Fillers counted: um, uh, umm, uhm, hmm, mm, mhm, er, erm, ah. The AMI
references are verbatim, so Clean pays for every filler it removes in the AMI
column. The "fillers removed" column scores it more fairly but still counts
removed repeats and false starts. The corpus is small (120 clips, 2 meetings),
so only the AMI gap between Pro and turbo is large enough to be robust.
LibriSpeech differences are within a few words.

**Fidelity of the sherpa int8 exports to transformers** (normalized text):

| Pair | Corpus: same text | Corpus: WER of B vs A | Excerpts: same text | Excerpts: WER of B vs A |
| --- | --: | --: | --: | --: |
| Pro transformers CPU → Pro sherpa int8 | 101/120 | 1.53 % | 131/230 | 12.09 % |
| Clean transformers CPU → Clean sherpa int8 | 98/120 | 2.08 % | 142/230 | 12.58 % |
| Pro transformers CUDA BF16 → CPU FP32 | 120/120 | 0.00 % | 218/230 | 1.15 % |
| turbo CUDA → turbo CPU | 105/120 | 1.20 % | 182/230 | 7.28 % |

The fp32 ONNX graphs reproduce PyTorch: maximum relative difference 3e-5 on
the encoder, with identical joiner argmax. The remaining text differences come
from int8 weights and from sherpa-onnx's own kaldi-fbank approximation of the
NeMo front end. On clean speech they are small and do not raise WER. On noisy
multi-speaker audio the two front ends diverge more (12 %). Without references
for that audio, it is unknown which side is more often right.

### 3b. Speed and memory (full workload)

| Run | Load s | First decode s | RTF corpus | RTF excerpts | Phrase 2-10 s p50 / p95 ms | Phrase < 2 s p50 ms | Peak RSS MB | Peak GPU MB |
| --- | --: | --: | --: | --: | --: | --: | --: | --: |
| turbo, CUDA | 4.4 | 0.65 | 0.065 | 0.102 | 343 / 680 | 311 | 1,820 | 1,394 |
| turbo, CPU | 2.3 | 6.89 | 1.424 | 2.264 | 7,324 / 15,394 | 7,094 | 2,157 | - |
| Pro, transformers CUDA BF16 | 3.5 | 0.98 | 0.040 | 0.052 | 193 / 353 | 81 | 2,317 | 1,692 |
| Pro, transformers CPU FP32 | 3.2 | 0.70 | 0.128 | 0.152 | 578 / 990 | 263 | 4,935 | - |
| Pro, sherpa int8 CPU | 1.9 | 0.48 | 0.091 | 0.118 | 450 / 743 | 216 | 1,421 | - |
| Clean, transformers CUDA FP32 | 27.1 | 0.42 | 0.038 | 0.039 | 156 / 310 | 69 | 6,216 | 3,292 |
| Clean, transformers CPU FP32 | 25.8 | 0.67 | 0.141 | 0.136 | 523 / 986 | 230 | 6,082 | - |
| Clean, sherpa int8 CPU | 2.3 | 0.52 | 0.100 | 0.102 | 401 / 753 | 174 | 1,426 | - |

RTF is the sum of decode times divided by the sum of audio durations. "Load"
runs from the start of model construction to ready, with files in the page
cache. Peak GPU memory is this process's maximum `nvidia-smi` used_memory,
sampled every 0.2 s. The load average at the start of each step ran from 3.8
to 15.4 (`run_all.log`).

### 3c. CPU latency, repeated (median of 10 after 1 warm-up)

Clips: `ami-ES2002a-D-29` (2.99 s) and `libri-clean-1580-141084-0041` (7.99 s).
Two rounds, each in a fresh process.

| Run | Load s | 3 s clip ms | 8 s clip ms | Load average during run | Peak RSS MB |
| --- | --: | --: | --: | --: | --: |
| turbo CPU, round 1 / 2 | 2.5 / 2.0 | 5,587 / 5,329 | 5,959 / 5,545 | 4.9-9.3 | 2,056-2,072 |
| Pro sherpa int8, round 1 / 2 | 2.0 / 1.9 | 304 / 291 | 602 / 697 | 8.2-9.3 | 1,255-1,262 |
| Clean sherpa int8, round 1 / 2 | 2.0 / 4.4 | 261 / 502 | 581 / 977 | 9.3-11.9 | 1,246-1,252 |
| Pro transformers FP32, round 1 / 2 | 3.0 / 3.9 | 319 / 436 | 923 / 1,087 | 9.4-11.5 | 4,622-4,642 |
| **Quiet machine** (no other heavy process; the load average comes from the run's own threads): turbo CPU | 4.0 | 5,558 | 5,492 | 2.3 → 8.0 | 2,070 |
| Quiet machine: Pro sherpa int8 | 1.8 | 292 | 637 | 8.0 | 1,249 |
| Quiet machine: Clean sherpa int8 | 2.2 | 307 | 629 | 7.6-9.5 | 1,252 |

The turbo CPU latency is about 5.5 s per clip whether or not the machine is
busy, so contention does not explain it. Settings did not change it either: a
direct check gave 5.1-5.5 s for a 6.17 s clip with or without `vad_filter` and
`word_timestamps`. The system was on AC power with the `balanced` profile at
about 4 GHz.

This is about 3 times the project's earlier screen
(`docs/transcription-experiments.md`, CPU screen 2026-10-20: large-v3-turbo-ct2
at 1.66 s for a 6.49 s clip, int8, 8 threads). The cause of the gap is
**unresolved**. That screen used the deepdml snapshot, which is no longer on
this machine; this run used the dropbox-dash snapshot. Whisper encodes a fixed
30 s window, so its CPU cost hardly depends on the clip length (5.6 s for 3 s,
5.5 s for 8 s here). Bark's cost scales with the audio. Even against the
earlier 1.66 s figure, Bark sherpa int8 is 3-6 times faster per phrase on this
CPU.

### 3d. Private excerpts: agreement and output behaviour

WER of each column, using the row as reference (230 phrases, no reference
text):

| Reference \ hypothesis | turbo CUDA | Pro transformers CUDA | Pro sherpa | Clean transformers CUDA | Clean sherpa |
| --- | --: | --: | --: | --: | --: |
| turbo CUDA | - | 34.9 | 35.1 | 39.8 | 38.1 |
| Pro transformers CUDA | 34.0 | - | 12.2 | 29.6 | 29.3 |
| Clean transformers CUDA | 44.6 | 34.5 | 34.0 | - | 12.0 |

- Words, filler words and empty phrases out of 230:

  | Run | Words | Filler words | Empty phrases |
  | --- | --: | --: | --: |
  | turbo | 2,197 | 4 | 13 |
  | Pro transformers | 2,260 | 32 | 8 |
  | Pro sherpa | 2,275 | 33 | 10 |
  | Clean transformers | 1,773 | 0 | 18 |
  | Clean sherpa | 1,784 | 0 | 13 |

- Clean keeps 80 % of Pro's non-filler words on the excerpts, against 98 % on
  the corpus. It returns empty text for 8 phrases (transformers) or 5 phrases
  (sherpa) where Pro has 3 or more words. On this audio it appears to treat
  overlapping or repeated speech as disfluency.
- The low agreement between turbo and Bark (about 35 %) reflects hard
  multi-speaker system audio. Without references, it is unknown which model is
  more often right. The output samples (sent to the manager only) show turbo
  extending phrases with words that are not there; that is a qualitative
  observation.

### 3e. Timestamps on the excerpt phrases

| Run | Phrases with text | With word times | Invalid (outside phrase ±1 s, or end < start) | Non-monotonic | Median word length |
| --- | --: | --: | --: | --: | --: |
| turbo (CUDA, CPU) | 217 | 217 | 0 | 0 | 240 ms |
| Pro (transformers ×2, sherpa) | 220-223 | all | 0 | 0 | 160 ms |
| Clean (transformers ×2, sherpa) | 212-217 | all | 0 | 0 | 160 ms |

Median absolute word-start difference on matched words:

| Pair | Median | p90 |
| --- | --: | --: |
| Pro vs Clean | 10 ms | 90 ms |
| Pro transformers vs Pro sherpa | 0 ms | 80 ms |
| turbo vs Pro or Clean | 80-90 ms | 270-320 ms |

## 4. License attribution

| Component | License | Attribution parties (NOTICE) |
| --- | --- | --- |
| Underdog Bark 3.0 Pro / Clean (Conway Research) | CC-BY-4.0 | Conway Research; derives from nvidia/parakeet-tdt-0.6b-v3, (c) NVIDIA Corporation, CC-BY-4.0; and moondream/parakeet-ultra, (c) Moondream, CC-BY-4.0. "Changes: post-trained and compressed by Conway Research." |
| Base nvidia/parakeet-tdt-0.6b-v3 | CC-BY-4.0 | NVIDIA Corporation |
| Third-party sherpa export (velddev, unofficial) | CC-BY-4.0 | Adds "converted to ONNX for sherpa-onnx; int8 quantization" |
| Current, for comparison: Silero VAD | MIT | Not attributed in the repo today |
| Current, for comparison: NeMo TitaNet-small (live speakers) | Apache-2.0 per the NeMo license note in `recordings/.models/diarization/` | Not attributed in the repo today |

**What CC-BY-4.0 §3(a) requires when stenographer shares the model** (hosts,
mirrors or bundles weights, or publishes its own ONNX export, which is Adapted
Material):

- Keep the creator identification and attribution parties: Conway Research,
  NVIDIA Corporation and Moondream, as in the NOTICE.
- Keep the copyright notices, a notice that refers to the license, and the
  disclaimer of warranties.
- Give a URI or hyperlink to the licensed material.
- State that the material is licensed under CC BY 4.0, with the license text
  or a link to it.
- For an export, state the modifications ("converted to ONNX; int8
  weight-only quantization") and keep Conway Research's earlier modification
  notice.

If stenographer only downloads from the original Hugging Face repo when the
user asks for it, it does not share the weights. Attribution is then good
practice, not a license condition. A stenographer-hosted Pro export would be
sharing. This is a plain reading of the license text, not legal advice.

**Where it would go:**

1. `src/stenographer/assets/licenses/underdog-bark-3.0-NOTICE.txt`: the NOTICE
   verbatim, the CC-BY-4.0 link and stenographer's modification statement.
   Add it to the `.gitignore` and `pyproject.toml` allowlists; the
   `assets/licenses/*.txt` wheel include already covers it (see
   docs/building.md).
2. Any hosted model repo: `NOTICE` and `LICENSE` (the CC-BY-4.0 legal code)
   beside the weights.
3. README: a "Third-party models" subsection under "License" naming each model,
   its authors, its license and a link.
4. Site (`site/index.html`): one fine-print line next to the existing Caveat
   OFL credit.
5. `stenographer model download --asr` output and the model docs
   (`docs/live.md` "Prepare the models"; `docs/usage.md`): the model name, the
   authors and "CC BY 4.0".

stenographer has no "about" command or screen. If one is added, it should list
the same entries. The same pass should credit Silero VAD (MIT) and TitaNet,
which are not credited today.

## 5. Recommendation and integration size

**Recommendation:**

1. **Files and live: Bark 3.0 Pro, int8, through sherpa-onnx.**
   - Best accuracy on meeting speech: AMI 7.8 % against 17.1 %.
   - 10-20 times faster than turbo on CPU under the same load.
   - About 0.8 GB less RSS.
   - No new runtime dependency.
   - Diarization unaffected.
   - On this machine turbo uses CUDA. A CPU sherpa backend is about 100 ms
     slower per 2-10 s phrase than turbo on CUDA (p50 450 ms against 343 ms).
     It frees about 1.4 GB VRAM, which matters for the local Ollama refine
     model.
2. **Dictation: Pro is the candidate, with one model shared across modes.**
   Clean should be an opt-in option, after a microphone dictation trial with
   the user's consent. Clean's filler removal is real and its timestamps are
   fine. Its content loss on crosstalk (20 % of words, some whole phrases) is
   a risk that single-speaker dictation may or may not trigger. This report
   did not measure that. If Clean is adopted, its overlap with the refine
   stage (docs/refine.md) needs a decision.
3. **Do not adopt the transformers + torch path.** It adds about 5-6 GB of
   install with CUDA wheels and a second stack. Clean also needs 26 s and
   about 6 GB to unpack on every load.

**Integration work** (sherpa path; files from `dev` at the base commit):

| Area | Files | Work |
| --- | --- | --- |
| Backend | new `lib/transcribe/<parakeet>_model.py` (class), `lib/platform/asr.py` (selection), `lib/transcribe/model.py` (unchanged contract) | `OfflineRecognizer.from_transducer(model_type="nemo_transducer")`. Map sherpa tokens, timestamps and durations to `SegmentInfo` and `WordInfo` (one segment; words grouped from tokens). Apply Pro's 0.25 s pad. |
| Silence gating | `lib/transcribe/decode.py`, `lib/live/live_session.py:522` | Replace `no_speech_prob`: VAD before the decode for dictation (sherpa Silero VAD, already used by live), with optional `ys_log_probs` confidence. Keep `_validate_output`. |
| Config | `lib/config/models.py`, `assets/default_config.toml.in`, preservation layer | Backend or model id. `hotwords` and `initial_prompt` have no TDT equivalent: document as Whisper-only, or test sherpa hotwords with `modified_beam_search` (not verified for NeMo TDT). |
| Download | `lib/transcribe/download.py` (CT2 allow-list today), `cli/model/*`, doctor | Pinned files with sha256, like `lib/live/download.py`. A hosting decision is needed: Pro has no published sherpa export, so stenographer must host its own (sharing, so attribution is required) or depend on a third-party repo (Clean: velddev, unofficial, created 2026-10-21; pin by revision and sha256). Converting on the user's machine would require torch. |
| Packaging | `packaging/stenographer.spec` | No change (`collect_all("sherpa_onnx")`). The bundle size does not change. The model download is 655 MB int8, against turbo's about 1.6 GB. |
| Licenses and docs | assets/licenses, `.gitignore`, `pyproject.toml`, README, `docs/live.md`, `docs/usage.md`, `docs/transcription-experiments.md`, `site/` | See item 4. |
| Tests | unit tests for token→word grouping, result mapping, the gate, download pins | Pure-logic unit tests, plus a native acceptance run per packaging/NATIVE-ACCEPTANCE.md. |

Estimate: about 10-15 production files plus docs and tests, and no new Python
dependency. The open product decisions are hosting the Pro export, replacing
the silence gate, and the fate of `hotwords` and `initial_prompt`.

## Limits

- One machine and one day. The full-workload CPU numbers were taken under
  contention from other agents (load average 4-15). The repeated latency
  checks include a quiet-machine round.
- turbo CPU latency here (about 5.5 s per phrase, busy or quiet) is about 3
  times the 2026-10-20 screen (1.66 s); the cause is unresolved (§3c).
- The private excerpts have no reference text, so agreement does not show
  which model is right.
- No microphone dictation audio was used (not authorised). Dictation fit is
  inferred from the corpus.
- The production `silero_vad.onnx` and the default deepdml turbo were not
  available. Substitutes are named in §3.
- sherpa-onnx on GPU was not measured (the CPU wheel is installed).
- Clean through transformers used Pro's processor and generation config
  instead of `nvidia/parakeet-tdt-0.6b-v3`, which is not authorised. Clean's
  embedded config equals Pro's `config.json` apart from dtype.

## Reproduce one measurement

Scripts are in `bench/` beside this report. Results go to `.scratch/results/`
(not committed; they contain transcripts). From the worktree root:

```sh
# Pro sherpa-onnx export (scratch venv: torch 2.14.1, transformers 5.20.2, onnx 1.23.2, onnxruntime 1.31.0, onnx_ir)
.scratch/venv/bin/python -I .hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/export_pro_sherpa.py \
  .scratch/models/bark-pro .scratch/models/bark-pro-sherpa

# Pro int8 in sherpa-onnx, CPU, repeated latency only (any production .venv with sherpa-onnx 1.13.8)
BENCH_MICRO=1 /home/penguin/source/stenographer/.venv/bin/python -I \
  .hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_sherpa.py \
  pro-sherpa-int8-cpu .scratch/models/bark-pro-sherpa 0.25 .scratch/results/micro/pro-sherpa-check.json

# Full workload and tables (needs .scratch/audio and .scratch/phrases; see §3 for how they were cut)
/home/penguin/source/stenographer/.venv/bin/python -I .hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_sherpa.py \
  pro-sherpa-int8-cpu .scratch/models/bark-pro-sherpa 0.25 .scratch/results/pro-sherpa-int8-cpu.json
cd .scratch/results && python3 -I ../../.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/analyze.py \
  turbo-ct2-cuda.json turbo-ct2-cpu.json pro-hf-cuda.json pro-hf-cpu.json pro-sherpa-int8-cpu.json \
  clean-hf-cuda.json clean-hf-cpu.json clean-sherpa-int8-cpu.json   # this order reproduces raw/analysis.md
```

Other runners:

- `run_hf.py pro|clean cpu|cuda OUT` (scratch venv).
- `run_whisper.py cpu|cuda MODEL_DIR OUT` (production `.venv`).
- `run_all.sh` is the exact sequence used, in `bench/run_all.sh`.

Without `BENCH_MICRO`, a run needs the private excerpts. With it, a run needs
only the public corpus.
