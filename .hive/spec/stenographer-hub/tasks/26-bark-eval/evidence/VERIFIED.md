<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Independent verification: 26-bark-eval

Date: 2026-10-22. Verifier: `t26-verifier-2`.
Reviewed commit: `e6a9c2a`. Previous verdict: fail at `09d739e`.

## Verdict

**Pass within the manager's research-review scope.** The correction restricts
zero fillers to the private excerpts. All three Clean configurations have
one filler word on the public corpus and zero on the private excerpts.
The summary, report §3a, and `raw/analysis.md` now agree.

The manager authorised a report/raw consistency review and at most one new
measurement. I repeated Pro's public-corpus CPU micro measurement. I did not
repeat the full inference workload, GPU runs, export, or third-party vetting.
The previous verifier independently repeated the Pro/turbo CPU comparison
(Pro 358 ms; turbo 5,463 ms), and passed privacy and attribution.

| Verification item | Result | Observation |
| --- | --- | --- |
| Corrected Clean filler claim | pass | Independently counted normalized fillers from all eight existing result JSONs: each Clean corpus run has 1; each Clean private run has 0. The public references contain 36. |
| V1: runtime path | pass | Existing run log and result tables contain both sherpa and transformers paths for both Bark models. Pro's sherpa run repeated successfully using only existing files. Scratch venv is 6.1 GB. The three int8 files total about 655 MB; Pro/Clean sizes differ by 280, 1, and 1 bytes. No new dependency is required for the measured sherpa path. |
| V2: fit and timestamps | pass | Re-ran the source query below: live and Files use phrase start/end and phrase duration for lines and speaker assignment. Whisper-specific no-speech gating remains in decode and live. Raw timestamp tables support valid word times for all measured runs and the Pro/Clean 10 ms median, 90 ms p90 matched-word offset. Dictation suitability remains an inference pending consented testing. |
| V3: accuracy, speed and memory | pass | Rebuilt analysis from the eight existing scratch JSONs; output matches committed raw/analysis.md byte for byte. Compared report WER, latency, RSS/VRAM, agreement, word counts and timestamps with raw tables and run log. Compared every repeated-latency row with raw/micro JSONs. One new Pro micro run returned 304 ms for the 2.99 s clip and 593 ms for the 7.99 s clip. |
| Additional report numerical claims | pass | Independently recomputed the fidelity table, including insertions against empty reference hypotheses: 101/120, 98/120, 120/120 and 105/120 corpus exact counts; corpus WERs 1.53, 2.08, 0.00 and 1.20%; excerpt WERs 12.09, 12.58, 1.15 and 7.28%. Clean/Pro non-filler word-count ratios are 0.9832 on corpus and 0.7958 on excerpts. Clean blanks 8 transformers phrases and 5 sherpa phrases where Pro has at least 3 words. |
| V4: attribution | pass | Rechecked cached model-card license statements and NOTICE attribution to Conway Research, NVIDIA and Moondream. Clean and velddev NOTICE files are identical. License §3(a) supports the attribution checklist; proposed asset allowlists and wheel include paths exist. Qualification about Adapted Material remains below. |
| V5: recommendation and integration estimate | pass | Recommendations follow the reported CPU, corpus and content-loss observations. Packaging already collects sherpa_onnx. Hosting, silence gating and Whisper settings are identified as open decisions. The file-count estimate is a planning estimate, not an implementation acceptance result. |
| Privacy and research boundaries | pass | All 29 changed files from base f5a0fc8 are UTF-8 text under the task brief/evidence paths. No production file or binary was changed. A normalized 10-word overlap scan against private hypotheses in all eight result JSONs found zero matches in committed changes. No private transcript was printed or committed. |

## New measurement

Executed from the worktree root, using the committed runner unchanged:

```sh
BENCH_MICRO=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /home/penguin/source/stenographer/.venv/bin/python -I \
  .hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/run_sherpa.py \
  pro-sherpa-int8-cpu .scratch/models/bark-pro-sherpa 0.25 \
  .scratch/results/micro/verifier2-pro.json
```

Exit status: 0. sherpa-onnx 1.13.8, CPU, 8 threads, 0.25 s leading padding.
One warm-up followed by ten decodes per clip; medians:

| Metric | Observation |
| --- | ---: |
| Model load | 1.958 s |
| ami-ES2002a-D-29, 2.99 s | 304.399 ms |
| libri-clean-1580-141084-0041, 7.99 s | 593.217 ms |
| Peak RSS | 1,249.293 MiB |
| Load average start → end | 1.69 → 3.84 |

These observations agree with the report's CPU performance range. Performance
is not a fixed acceptance threshold.

## Analysis and source checks

```sh
cd .scratch/results
../venv/bin/python -I \
  ../../.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/analyze.py \
  turbo-ct2-cuda.json turbo-ct2-cpu.json pro-hf-cuda.json pro-hf-cpu.json \
  pro-sherpa-int8-cpu.json clean-hf-cuda.json clean-hf-cpu.json \
  clean-sherpa-int8-cpu.json | cmp - \
  ../../.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/raw/analysis.md
```

`cmp` exited 0 with no output. Python printed relative-prefix warnings but
completed the analysis. No analysis output file was created.

From the worktree root, re-ran V2's source query:

```sh
git grep -n 'no_speech_prob\|phrase.start\|phrase.end' src/stenographer/lib
```

Files lines 228 and 239–240, and live lines 534 and 542–543, confirm the
phrase-duration and line-timestamp claims. Decode line 75 and live line 522
confirm the model-specific silence gate. Also inspected the license statements,
NOTICE files, LICENSE §3(a), asset inclusion rules and packaging collection.

## Qualifications and limits

- Report §3a's fidelity table includes insertions for empty references;
  analyze.py's pooled agreement matrix excludes empty-reference pairs. Both
  sets reproduce their reported values. These are different aggregation rules.
- CC-BY-4.0 §2(a)(4) says technical format modifications alone do not produce
  Adapted Material. The report categorically calls an ONNX export Adapted
  Material. Retain this qualification when interpreting that sentence.
  Sharing either original or modified weights still triggers §3(a), so the
  practical attribution checklist is unchanged. This is not legal advice.
- The small corpus does not establish statistical significance. Private audio
  has no reference transcript; agreement does not establish correctness.
- Historical hardware, model download/401 observations, conversion internals,
  third-party static vetting and quiet-machine conditions were not recreated.
  Their report descriptions were reviewed against the available evidence and
  prior verification; this verdict makes no new live claim about them.
- No UI or production feature changed. Production gates and feature red/green
  tests do not apply to this research-only review.
- No download, new venv, microphone, daemon/settings change or velddev script
  execution occurred. No pre-existing scratch asset was deleted. The sole
  new scratch result was removed after recording its metrics here. Existing
  scratch assets remain for manager-authorised cleanup.
