# 30-live-spike verification

| Item | Value |
| --- | --- |
| Task | 30-live-spike |
| Commit verified | 017e09a (merge of `origin/dev` 5e5409d at eef6243) |
| Date | 2026-10-19 |
| Agent | verifier, claude-code, claude-opus-5-5 |
| Environment | Worktree `.venv` (`stenographer.__file__` resolves to this worktree). Python 3.14, 8 physical cores / 16 threads, no CUDA. Models, audio, and wheels downloaded fresh into the ignored worktree `tmp/`; `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, and `HF_HOME` pointed into `tmp/`. |

| Item | Proves | Result | Observation |
| --- | --- | --- | --- |
| V1 dependencies + coexistence | R1 | pass | Installed: textual 8.2.8, sherpa-onnx 1.13.8, sherpa-onnx-core 1.13.8, faster-whisper 1.2.1, onnxruntime 1.31.0. `pip download` of the nine wheels gives sizes identical to `bench.md` byte for byte. Installed files of the nine new distributions sum to 55,930,676 B (reported `.venv` growth 55,930,742 B). One process imported `sherpa_onnx`, `faster_whisper`, `textual`; created `VoiceActivityDetector`, `SpeakerEmbeddingExtractor` (computed a 192-dim embedding), and `WhisperModel` (large-v3-turbo int8, ran one transcribe); all alive together, exit 0; `onnxruntime` Python module not imported. |
| V2 download + parser | R2, R4, AC2 | pass | `stenographer model download --live` (isolated XDG): first run downloaded both files to `tmp/xdg-data/stenographer/models/live/`, second run reported both `already present`, exit 0 both. `sha256sum` matches the pinned values (`9e2449e1…1fd6`, `ad4a1802…789e`). A present file with a wrong hash: exit 1, `Live model silero_vad.onnx is present with an incorrect SHA-256 hash. Remove it and retry.`, no file changed. `--help` lists `--live`. Red/green by deliberate breaks: no download hash check → bad-hash test fails; no temp cleanup → both cleanup tests fail; no skip of a present file → skip test fails; restored → 4 passed. Parser flag renamed → parser test fails; `--live` falling through to legacy selection → legacy test fails; restored → 18 passed. `data_dir` fallback changed → fallback test fails; restored → 23 passed (dirs + platform). |
| V3 bench | R3, AC3 | pass | Same command and public samples as `bench.md`; exit 0, valid JSON. VAD 1 thread: 0.036 s for 16.0 s, RTF 0.00223, the same four phrase cuts. Clustering: 2 clusters, 0 over-split, 0 merge for every threshold 0.30–0.70; chosen 0.50. Embedding median/p95 ms, 20 runs: 1 thread 12.7/16.8, 28.4/30.9, 86.7/93.6; 2 threads 9.4/10.7, 20.0/21.5, 63.4/75.9; 4 threads 6.5/7.5, 15.7/17.3, 51.8/58.6. Gate p95 5 s / 2 threads = 21.487 ms ≤ 150 ms: **PASS**. Whisper `dropbox-dash/faster-whisper-large-v3-turbo` int8, 8 threads: RTF 0.8615 / 0.356 / 0.1343 for 2 / 5 / 15 s. All within run-to-run noise of `bench.md`. D9: `pw-record` 1.6.9 `--help` lists `--raw`, `--target`, `--rate`, `--channels`, `--format`, `[<file>|-]`; `--list-formats` includes `f32`; `pw-cat.1.md` at tag 1.6.9 says `--raw` sets raw samples and STDOUT without a container uses AU. No recording run. |
| V4 tests + completions | R4 | pass | Base (5e5409d) completion assets → `test_completion_assets_cover_every_public_parser_token` fails for bash, zsh, fish; restored → 3 passed. `scripts/check-completions.sh`: bash passed, zsh and fish skipped (not installed). Bench clustering `len(members) + 1` → both bench tests fail; restored → 2 passed. |
| V5 gate | AC1 | pass | `ruff check .`: All checks passed (exit 0). `ruff format --check .`: 561 files already formatted (exit 0). `pytest -m "not integration"`: 2505 passed, 5 deselected (exit 0). `stenographer --help`: exit 0. |
| AC4 spec changes | AC4 | pass | `bench.md` proposes no spec change; the measured values do not contradict a spec decision. It notes the three-clip sample cannot separate thresholds and the turn sample has no pauses below 0.6 s. |

No microphone, no system audio capture, and no integration tests were run.

## Observations (not failures)

- One "green" dirs run first failed after a same-size, same-second mutation
  restore: stale `.pyc`. After removing `__pycache__`, 23 passed. Source was
  unchanged (`git status` clean).
- Downloaded live models get mode `0600` (from `NamedTemporaryFile`). Not
  covered by the brief.
- `.venv` growth was re-derived from installed file sizes, not from a fresh
  before/after install.
