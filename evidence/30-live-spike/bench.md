# Live CPU spike

## R1: dependencies and coexistence

Environment: Python 3.14.8 on AMD Ryzen 7 9800X3D, 8 physical cores and 16 logical threads; no CUDA. The package install resolved these versions:

| Distribution | Installed version | Wheel size |
| --- | ---: | ---: |
| `textual` | 8.2.8 | 731,418 B |
| `sherpa-onnx` | 1.13.8 | 4,403,669 B |
| `sherpa-onnx-core` | 1.13.8 | 10,642,497 B |
| `platformdirs` | 4.13.5 | 32,779 B |
| `markdown-it-py` | 4.2.0 | 91,687 B |
| `mdurl` | 0.1.2 | 9,979 B |
| `linkify-it-py` | 2.2.0 | 21,971 B |
| `rich` | 15.0.0 | 310,654 B |
| `mdit-py-plugins` | 0.6.1 | 66,663 B |

These are Linux x86-64 wheels for the package versions installed in this
worktree. `.venv` grew from 545,570,771 bytes before the two new dependencies
to 601,501,513 bytes after installation: 55,930,742 bytes (55.93 MB / 53.34
MiB).

One `.venv/bin/python` process imported `sherpa_onnx`, `faster_whisper`, and
`textual`, created a sherpa `VoiceActivityDetector`, created a sherpa
`SpeakerEmbeddingExtractor`, and created a faster-whisper `WhisperModel`.
All three objects remained alive together. `faster-whisper` was 1.2.1 and
`onnxruntime` was 1.31.0. `onnxruntime` was not imported as a Python module;
the models initialized without an ONNX Runtime conflict.

## R3: samples and measurements

The labelled speaker clips came from the public sherpa-onnx speaker
recognition test data:

- `csukuangfj/sr-data`, `test/3d-speaker/speaker1_a_en_16k.wav`
- `csukuangfj/sr-data`, `test/3d-speaker/speaker1_b_en_16k.wav`
- `csukuangfj/sr-data`, `test/3d-speaker/speaker2_a_en_16k.wav`

Source: <https://github.com/csukuangfj/sr-data/tree/main/test/3d-speaker>.
The sherpa-onnx test runner clones this data repository for speaker tests.
The two `speaker1` clips share one label; the `speaker2` clip has the other.

The VAD turn sample was the public release test file
[`1-two-speakers-en.wav`](https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/1-two-speakers-en.wav).
It is 16 kHz, mono, and 16 seconds long. No microphone or system audio was
captured. The audio files stayed in the ignored worktree `tmp/` directory.

Command:

```sh
XDG_DATA_HOME="$PWD/tmp/xdg-data" HF_HOME="$PWD/tmp/hf-home" \
  .venv/bin/python scripts/live_bench.py \
  --audio speaker1=tmp/live_audio/speaker1_a_en_16k.wav \
  --audio speaker1=tmp/live_audio/speaker1_b_en_16k.wav \
  --audio speaker2=tmp/live_audio/speaker2_a_en_16k.wav \
  --turn-sample tmp/live_audio/1-two-speakers-en.wav
```

### VAD

D6 values: 0.25 s minimum speech, 0.6 s silence, 25 s maximum phrase. VAD
used one thread. Processing 16.000 s took 0.036 s (real-time factor 0.00223).

| Phrase | Start | End | Duration |
| ---: | ---: | ---: | ---: |
| 1 | 1.638 s | 3.368 s | 1.730 s |
| 2 | 4.422 s | 6.536 s | 2.114 s |
| 3 | 9.382 s | 11.496 s | 2.114 s |
| 4 | 12.198 s | 14.696 s | 2.498 s |

The gaps between phrases were 1.054 s, 2.846 s, and 0.702 s. The 0.6 s
pause cut these four speech phrases cleanly in this short two-speaker sample.
This sample does not test turn changes with pauses shorter than 0.6 s.

### Speaker embedding latency

Each duration/thread combination has 20 measured runs after warm-up. Values
are median / p95 in milliseconds.

| Threads | 2 s phrase | 5 s phrase | 15 s phrase |
| ---: | ---: | ---: | ---: |
| 1 | 12.368 / 15.797 | 29.429 / 34.481 | 87.311 / 94.406 |
| 2 | 8.960 / 9.747 | 20.858 / 22.509 | 66.953 / 79.988 |
| 4 | 7.200 / 10.240 | 18.041 / 20.508 | 53.203 / 58.752 |

The spec gate is **PASS**: p95 is 22.509 ms for a 5 s phrase with 2 threads;
the limit is 150 ms.

### Online clustering

D7 cosine matching to running mean embeddings, in input order:

| Threshold | Clusters | Over-split | Merge |
| ---: | ---: | ---: | ---: |
| 0.30 | 2 | 0 | 0 |
| 0.35 | 2 | 0 | 0 |
| 0.40 | 2 | 0 | 0 |
| 0.45 | 2 | 0 | 0 |
| 0.50 | 2 | 0 | 0 |
| 0.55 | 2 | 0 | 0 |
| 0.60 | 2 | 0 | 0 |
| 0.65 | 2 | 0 | 0 |
| 0.70 | 2 | 0 | 0 |

Chosen threshold: **0.50**. All tested thresholds had the same result on this
three-clip sample, so the benchmark selects the central value as its tie
break. This sample does not support a decision change; broader audio could
separate the thresholds.

### Whisper decode

The model and compute type match `src/stenographer/assets/default_config.toml.in`:
`dropbox-dash/faster-whisper-large-v3-turbo`, `int8`. Decode used 8 CPU
threads. One 15 s English phrase warmed the model before measurement.

| Phrase | Decode time | Real-time factor |
| ---: | ---: | ---: |
| 2 s | 1.838 s | 0.9191 |
| 5 s | 2.154 s | 0.4308 |
| 15 s | 2.162 s | 0.1441 |

## D9: PipeWire 1.6.9 flag check

Confirmed command line:

```text
pw-record --raw --target <default sink>.monitor --rate 16000 --channels 1 --format f32 -
```

`pw-record --version` reports PipeWire 1.6.9 compiled and linked. Its
`--help` lists `--raw`, `--target`, `--rate`, `--channels`, `--format`, and
`-` as the output destination. The PipeWire 1.6.9 manual
[`pw-cat.1.md`](https://github.com/PipeWire/pipewire/blob/1.6.9/doc/dox/programs/pw-cat.1.md)
says `--raw` selects raw samples and the rate, format, and channel flags set
their raw format. It also says stdout defaults to an AU container when raw
mode is absent. This confirmed why D9 needs `--raw`. No recording command was
run.
