<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Independent verification: 26-bark-eval

Date: 2026-10-22. Verifier: `t26-verifier-1`.
Worker commit: `1259a26`.

## Scope and verdict

**Fail:** the summary says Clean has “0 filler words in every run”.
The public-corpus table in report §3a and `raw/analysis.md` both give
**1 filler word** for each of the three Clean configurations. Restrict the
summary's zero-filler claim to the private excerpts, or correct its count.
No production change is needed.

The manager narrowed verification to one repeated measurement, privacy,
license attribution, and consistency with `raw/`. I repeated the CPU latency
comparison. I did not repeat the full workload, GPU measurements, conversion,
or public-corpus inference. No UI change or production change is present.
Production test gates and red/green feature tests do not apply to this research
report.

| Item | Result | Observation |
| --- | --- | --- |
| Repeat one measurement: Pro sherpa int8 versus turbo CPU latency | pass | Same public 2.99 s clip, 8 threads, median of 10 decodes after one warm-up: Pro 358.0 ms; turbo 5,463.5 ms; turbo/Pro 15.3. The CPU advantage repeats. Timing differs from the worker's 291–304 ms and 5,329–5,587 ms; these timings are observations, not fixed performance guarantees. |
| No committed private audio or transcript text | pass | All 28 files added since base `f5a0fc8` are UTF-8 text. No audio or binary file was added. Reviewed report, evidence notes, raw tables and logs; micro JSON files contain metrics and metadata only. A normalized 10-word overlap scan against all private hypotheses in the eight scratch result files found zero matches in the added files. This scan supplements inspection; it cannot prove absence of every possible short fragment. |
| License and attribution | pass | Both cached model cards state CC-BY-4.0. Both NOTICE files name Conway Research, NVIDIA and Moondream and retain the earlier modification statement. The cached third-party LICENSE §3(a) supports the report's attribution checklist. Its README states the ONNX/int8 modifications; its NOTICE matches Clean's. Proposed README, site, model documentation and packaged NOTICE placements address attribution. The asset allowlists and wheel inclusion patterns exist. No weights are distributed by this task. |
| Report claims match raw evidence | fail | Rebuilding the numerical analysis from the eight existing scratch result JSONs reproduced committed `raw/analysis.md` byte for byte. The detailed WER, speed, agreement and timestamp tables agree with that evidence, and the repeated-latency table agrees with the micro JSONs. The summary's unqualified zero-filler claim contradicts the public-corpus counts above. |
| Research boundaries | pass | Branch changes contain only the task brief and evidence. No download, venv creation, microphone use, model export, or script execution from the velddev repository occurred during verification. Existing model files and environments were used. Scratch assets are preserved for the manager's cleanup after landing. |

## Repeated measurement commands

Run from the worktree root. Offline environment flags were added to prevent
Hub access. These are the committed benchmark runners, without code changes.
The sherpa and turbo runners use the existing production environment, as the
report specifies. The analysis uses the existing scratch environment.

```sh
BENCH_MICRO=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /home/penguin/source/stenographer/.venv/bin/python -I \
  .hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_sherpa.py \
  pro-sherpa-int8-cpu .scratch/models/bark-pro-sherpa 0.25 \
  .scratch/results/micro/verifier-pro-sherpa.json

BENCH_MICRO=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /home/penguin/source/stenographer/.venv/bin/python -I \
  .hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_whisper.py \
  cpu /home/penguin/.cache/huggingface/hub/models--dropbox-dash--faster-whisper-large-v3-turbo/snapshots/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf/ \
  .scratch/results/micro/verifier-turbo.json

cd .scratch/results
../venv/bin/python -I \
  ../../.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/analyze.py \
  turbo-ct2-cuda.json turbo-ct2-cpu.json pro-hf-cuda.json pro-hf-cpu.json \
  pro-sherpa-int8-cpu.json clean-hf-cuda.json clean-hf-cpu.json \
  clean-sherpa-int8-cpu.json > verifier-analysis.md
cmp verifier-analysis.md \
  ../../.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/raw/analysis.md
```

Both benchmark commands exited 0. `cmp` exited 0 with no output. The scratch
Python invocation printed prefix warnings for its relative executable path;
the analysis completed successfully. An initial environment path probe used
`../../venv/bin/python --version` from the results directory and failed because
that path does not exist; the analysis command above used the correct path.

| Observation | Pro sherpa int8 | turbo CPU |
| --- | ---: | ---: |
| Model load, s | 2.491 | 3.882 |
| 2.99 s clip median, ms (`ami-ES2002a-D-29`) | 358.032 | 5,463.495 |
| 7.99 s clip median, ms (`libri-clean-1580-141084-0041`) | 754.805 | 5,429.123 |
| Peak RSS, MiB | 1,261.473 | 2,070.586 |
| Load average, start → end | 5.51 → 7.37 | 6.34 → 9.05 |

Versions reported by the runners: sherpa-onnx 1.13.8; faster-whisper 1.2.1;
CTranslate2 4.8.1. Pro uses 0.25 s leading padding. Turbo uses int8, beam 1
and VAD filtering. The benchmark also measures its standard 8 s clip; this
is part of the same micro run, not a second inference workload.

No private hypotheses were printed or copied to this evidence. Temporary
verification outputs were removed after their numerical results and exact
analysis match were recorded here. Pre-existing `.scratch` data was preserved.

## Limits and attribution qualification

This verdict does not establish statistical significance on the small corpus,
repeat GPU results, or establish microphone dictation quality. CC-BY-4.0
§2(a)(4) says that technical format modifications alone do not produce Adapted
Material. The report calls an ONNX export Adapted Material categorically;
that classification needs care. Sharing either original or modified weights
still triggers §3(a), so this qualification does not change its attribution
checklist. This verification is not legal advice.
