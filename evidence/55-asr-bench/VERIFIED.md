# 55-asr-bench verification

Verifier: independent re-run on 2026-10-20 against `413bd24` (base `13d95fd`).
The worktree has no `.venv`, so `/home/penguin/source/stenographer/.venv` was
used with `PYTHONPATH=src`. The loaded package was this worktree's
`src/stenographer`. All verifier outputs were written to the session scratchpad,
outside the repository, and removed after this file was written.

| Item | Result | Re-run and observation |
| --- | --- | --- |
| V1 corpus and cached models | pass | User consent to the one 1.08 GB public-corpus download is recorded (manager inbox seq 67). `corpus --root .../transcription-study-20260912` (no `--download`) reported 120 clips and 1,084,310,342 bytes; 60 dev and 60 held-out clips. Manifest SHA-256 `4b3d215b…49ecc` matches. All seven model repositories resolved with `HF_HUB_OFFLINE=1` and `local_files_only=True`. |
| V2 test-first regressions | pass | At base `13d95fd` the new test file fails to collect (`No module named 'transcription_study.asr_grid'`). At HEAD: `26 passed`. In a scratch copy, eight mutations each failed at least one test: own reference added to the prompt (2 failed), recording sort dropped (1), decoded mode reads references (1), four prior clips (1), beam 5 removed (2), repeat counter returns 0 (2), decoder overrides dropped (2), "upper bound" label removed (2). |
| V3 grid and context behaviour | pass | Code read: 12 int8 settings per model; prompts use at most the 3 preceding clips of the same recording, reject the target clip and foreign recordings; offline/CUDA-disabled environment set; overrides passed per call only. Re-run rows: 0 `own_reference_in_prompt`; row keys contain no text/transcript/hypothesis field. |
| V4 public WER/latency/RSS grid | pass | Re-ran the grid for `medium.en` and `large-v3-turbo-ct2` (24 of 72 settings; full 2-hour re-run not repeated; the worker's JSONL files were deleted, so the V4 SHA-256 values could not be re-checked). WER errors/N matched the committed table exactly in 24/24 rows. Validation errors: 6 `PathologicalOutputError`, all medium.en, matching the docs. 24/24 latency rows ok. Default baseline 84/741 (11.34%) reproduced. Latencies were 1–32% lower than committed (ratio 0.68–0.99; default median 1.457 s vs 1.870 s), so absolute latency depends on host load. RSS matched (1.47–1.48 GiB vs 1.45–1.46; turbo 2.27 vs 2.28 GiB). |
| V5 known output patterns | pass | Long-recording re-run (medium.en, 8 settings): repeated-phrase count 0 in every setting; `sample_candidate_lines_written` 0. `bench-samples.md` is outside the repository, untracked, and its SHA-256 was unchanged by the re-run. |
| V6 report and recommendation | pass | Dated section `CPU model and context screen: 2026-10-20` exists. Its 72 table rows equal `report.md`'s 72 rows exactly. `report.md` SHA-256 `61d079d1…c97dd` matches. Reference context labelled as an upper bound; no entity labels stated; no production default changed (no `src/` change in the commit). |
| V7 user recording | pass | Re-ran the real-audio pass for medium.en from the original absolute path. Metadata matched: 3,904,141,356 bytes, 48 kHz, 2 channels, 20,334.07 s, first 20 live-VAD phrases. Default: 1.282 s median (committed 1.220), 2.908 s p90 (2.887), 0.158 RTF (0.157), 2.01 GiB RSS (2.01). 160 ok rows, 80 not-applicable reference rows. No text fields in rows. |
| V8 compute budget and cuts | pass | All runs use `nice -n 10`. Float32 cut first, then large-v3 (slowest), as the brief orders. The verifier's two-model public re-run took 40.2 min, consistent with the 106.1 min six-model claim. |
| V9 gate | pass | `ruff check .`: All checks passed. `ruff format --check .`: 573 files already formatted. `pytest -m "not integration"`: 2546 passed, 2 skipped, 6 deselected. `stenographer --help`: exit 0. `git diff --check 13d95fd 413bd24`: clean. |

## Notes for the user

- The recommended candidate (turbo, beam 1, hotwords on, context off) is not
  the best turbo row: turbo beam 1 with hotwords off scored 75/741 (10.12%)
  and was faster in both runs. The latency comparison uses one 6.49 s clip and
  moves with host load (the turbo-vs-default delta was +0.113 s in the
  worker's run and −0.006 s in the verifier's run).
- A `VERIFIED.md` from task 54 sits at the checkout root (commit `5a6174b`).
  It predates this task and was not changed here.
