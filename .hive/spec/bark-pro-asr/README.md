# Bark Pro ASR swap

This file is the design authority for the feature `bark-pro-asr`. The user
approved the plan on 2026-10-21
(`/home/penguin/source/hive/plans/stenographer/bark-pro-integration.md`).
Technical facts come from the task 26 report
(`.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/report.md`, dev
`4e419d2`). Tasks A to D read this file as their contract. When a task finds
a fact that contradicts this file, it stops and tells the manager. The
manager updates this file first.

## Goal

Underdog Bark 3.0 Pro replaces Whisper as the only speech model in
stenographer. It runs as int8 ONNX through sherpa-onnx on the CPU. It serves
dictation, `stenographer live` and Files. faster-whisper leaves the project.

## Decisions (user, 2026-10-21)

1. **Pro only.** Underdog Bark 3.0 Pro, int8, sherpa-onnx, CPU. It replaces
   Whisper in dictation, live and Files. faster-whisper leaves the project
   completely: code, `pyproject.toml`, packaging and tests. This is a
   breaking change. There is no Clean option.
2. **ASR keys.** Remove `model`, `compute_type`, `beam_size`, `hotwords`,
   `initial_prompt`, `vad_filter` and `silence_threshold`. Keep
   `idle_unload_seconds` and `cpu_threads`.
3. **Model source.** A one-time local conversion of the official
   ConwayResearch Pro weights, pinned by revision. Stenographer hosts
   nothing and publishes nothing.
4. **Download.** `stenographer model download --asr` does these steps in
   order:
   1. Check free disk space (about 4-5 GB temporary).
   2. Create a temporary venv with the system Python 3.
   3. Install pinned CPU-only torch and pinned transformers, onnx,
      onnxruntime and numpy into it.
   4. Download Pro at the pinned revision. Check the sha256 of each source
      file.
   5. Run the converter.
   6. Check the sha256 of each output file.
   7. Install the model directory.
   8. Delete the venv and the BF16 source.

   Keep only the int8 encoder, decoder and joiner, `tokens.txt`, `NOTICE`,
   `LICENSE` and `manifest.json`.
5. **Output hash mismatch.** Fail closed with a clear message. Task A
   converts twice on this machine first, to prove that the output is
   deterministic. If it is not, the manager returns to the user with a
   fallback (a functional check on a synthetic clip).
6. **Silence.** Dictation runs the live-mode Silero VAD before the decode,
   with 0.25 s pre-pad. Empty results are dropped. There is no confidence
   threshold. The `no_speech_prob` gates are removed (`decode.py`,
   `live_session.py`). `--asr` also fetches the pinned `silero_vad.onnx` (the
   existing live model entry), so dictation needs only `--asr`.
7. **Old config keys.** No automatic rewrite. The loader ignores unknown and
   removed keys.
8. **Fillers** stay in every mode. Refine cleans dictations of 10 or more
   words (unchanged).
9. **`FIX.md`** at the repo root on dev: a short handoff prompt for a coding
   agent on each machine. It says: update the config, run the model
   download, and ask the user before deleting the old turbo cache. A later
   commit deletes it when both machines are done.
10. **Bench scripts.** Delete `scripts/transcription_bench.py`,
    `scripts/live_bench.py` and their tests.
11. **Attribution.** A NOTICE in `assets/licenses/`, a README "Third-party
    models" section and a line in the download output. Credit Bark /
    ConwayResearch (CC-BY-4.0; name the int8 conversion as a modification),
    nvidia parakeet-tdt-0.6b-v3, Silero VAD and TitaNet.
12. **Landing.** Land on dev under the grant of 2026-10-21. No main PR. No
    release.
13. **Boards.** Text-only screen changes (Config rows, banner) need no
    approved board.
14. **Venv source (Q1, decided 2026-10-21).** `/usr/bin/python3 -m venv`
    fails on this machine (Ubuntu 24.04 without `python3.12-venv`, no
    `ensurepip`). The prerequisite is the Ubuntu package `python3-venv`
    (`sudo apt install python3-venv`), once on each machine. The user runs
    the apt step. Agents never run sudo.
    - `model download --asr` first checks that `python3 -m venv` works. If
      it does not, it prints that fix and stops: non-zero exit, nothing
      downloaded.
    - Doctor warns when `python3 -m venv` would fail.
    - `FIX.md` names the apt step for the user to run.

## Open questions

- **Q2: other faster-whisper users (OPEN, found by task S).**
  `scripts/transcription_study/asr_grid.py` and
  `scripts/transcription_study/download_models.py` import faster-whisper.
  Decision 10 does not name them. Decision 1 removes faster-whisper
  completely, so these scripts break. The manager asks the user: delete
  them, or keep them as study history that needs a separate environment.

## Assumptions of this spec

These follow from the decisions. The manager may override them.

- **huggingface_hub leaves too.** Its only user is
  `lib/transcribe/download.py` (the Whisper cache probe and
  `snapshot_download`). The new download fetches pinned HTTPS URLs with
  `urllib`, as `lib/live/download.py` does. Task C removes the dependency.
- **Source URLs.** Each source file comes from
  `https://huggingface.co/ConwayResearch/Underdog-Bark-3.0-Pro/resolve/<rev>/<file>`.
  No Hugging Face cache is used.
- **Python and wheels.** The temporary venv uses the system `python3`
  (3.12 on this machine), not the stenographer interpreter. The pins must
  have wheels for that Python. torch comes from the CPU index
  `https://download.pytorch.org/whl/cpu`.

## Pins

| Item | Value |
| --- | --- |
| Source repo | `ConwayResearch/Underdog-Bark-3.0-Pro` |
| Source revision | `4b5c51e04aa8d16dda9ecdff71bc29f7360149e4` |
| Source files and sha256 | Task A records them (at least `config.json`, `model.safetensors`, `tokenizer.json`, `NOTICE`, and `LICENSE` if present) |
| Converter packages | Task A picks exact versions: torch (CPU), transformers (>= 5.19, has `ParakeetForTDT`), onnx, onnxruntime, numpy. Task 26 used torch 2.14.1, transformers 5.20.2, onnx 1.23.2, onnxruntime 1.31.0 |
| Output sha256 | Task A records them after two identical conversions |
| VAD | `silero_vad.onnx`, the existing `LIVE_MODELS` entry and sha256 |

All pins live in one Python module in `lib/transcribe/` (task A names it).
The manifest repeats them.

## Contracts

### Model directory

Path: `<data_dir>/models/asr/bark-pro-int8/`. `data_dir` is
`current_platform().data_dir(...)`, the same root as `models/live/`.

| File | Content |
| --- | --- |
| `encoder.int8.onnx` | int8 encoder (about 631 MB) |
| `decoder.int8.onnx` | int8 decoder |
| `joiner.int8.onnx` | int8 joiner |
| `tokens.txt` | 8,193 lines, `token id`, last line `<blk> 8192` |
| `NOTICE` | ConwayResearch NOTICE verbatim, plus the stenographer modification line |
| `LICENSE` | CC-BY-4.0 legal code |
| `manifest.json` | See below |

`manifest.json`:

```json
{
  "schema": 1,
  "source": {"repo": "ConwayResearch/Underdog-Bark-3.0-Pro", "revision": "4b5c51e04aa8d16dda9ecdff71bc29f7360149e4"},
  "packages": {"torch": "<pin>", "transformers": "<pin>", "onnx": "<pin>", "onnxruntime": "<pin>", "numpy": "<pin>"},
  "files": {"encoder.int8.onnx": "<sha256>", "decoder.int8.onnx": "<sha256>", "joiner.int8.onnx": "<sha256>", "tokens.txt": "<sha256>", "NOTICE": "<sha256>", "LICENSE": "<sha256>"}
}
```

`is_model_cached()` takes no model id. It returns true when the directory
exists, `manifest.json` parses, its `source.revision` equals the pinned
revision, and every file listed in the manifest exists. It does not hash the
files (a probe must stay fast). The download hashes them.

Installation is atomic. The build works in
`<data_dir>/models/asr/.build-<random>/`, on the same filesystem. The final
step is `os.replace` of the finished directory into place. A failure leaves
no partial `bark-pro-int8/`.

### Converter

- Asset: `src/stenographer/assets/convert/bark_pro_to_sherpa.py`. Add it to
  the Git and build allowlists (`.gitignore`, `pyproject.toml`,
  `packaging/stenographer.spec`; see `docs/building.md`).
- Basis: `.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/bench/export_pro_sherpa.py`.
- It must not import stenographer. It imports only the standard library and
  the pinned packages.
- The download runs it as `<venv>/bin/python -I bark_pro_to_sherpa.py
  INPUT_DIR OUTPUT_DIR`.
  - `INPUT_DIR`: the downloaded source files.
  - `OUTPUT_DIR`: an empty directory. The converter writes only
    `encoder.int8.onnx`, `decoder.int8.onnx`, `joiner.int8.onnx` and
    `tokens.txt` there. It keeps fp32 intermediates in a subfolder of
    `OUTPUT_DIR` and deletes them before it exits.
- Changes from the basis:
  - Fixed seeds and a fixed thread count, so that two runs give the same
    bytes.
  - The encoder metadata `comment` names the revision and says "int8
    conversion by stenographer"; it drops "for evaluation only".
  - The graph check (ONNX against PyTorch) stays. A failed check is an
    error, not only a printed line.
- Exit codes:

  | Code | Meaning |
  | --- | --- |
  | 0 | Success. The four files are in `OUTPUT_DIR`. |
  | 1 | Unexpected error (traceback on stderr). |
  | 2 | Usage error: wrong arguments, or `OUTPUT_DIR` not empty. |
  | 3 | Input error: a source file is missing or unreadable. |
  | 4 | Graph check failed: an ONNX graph does not match PyTorch, or `tokens.txt` does not match the vocabulary. |

  The download maps each non-zero code to a clear message and deletes the
  build directory.

### Download

- `stenographer model download --asr` installs Pro and also fetches
  `silero_vad.onnx` through the existing live download path.
- Free space: before the venv, check the filesystem of
  `<data_dir>/models/asr/`. Require at least 6 GiB free (4-5 GB temporary
  plus margin). Fail before any network call when it is short.
- Order of failure checks: venv check (decision 14), free space, package
  install, source sha256, converter exit code, output sha256. The venv and
  free-space checks run before any network call. Each failure prints one
  message that names the step and the fix.
- Output sha256 mismatch: fail closed. Install nothing. Name the file.
- Cleanup: delete the venv and the BF16 source on success and on failure.
- A model that is already present with a matching manifest is not rebuilt.
- Output line on success: the model name, "Conway Research", "CC BY 4.0",
  and "converted to int8 ONNX on this machine".
- No transcript text or audio enters any log.

### Backend

- `Model(cfg: AsrConfig)` and `Model.transcribe(samples) ->
  TranscriptionResult` stay the caller seam. `Model.close()` stays.
- The backend uses `sherpa_onnx.OfflineRecognizer.from_transducer(...,
  model_type="nemo_transducer")` with the three int8 files, `tokens.txt`,
  `num_threads` from `cpu_threads` (0 means the existing auto rule), greedy
  search, provider CPU.
- It pads the samples with 0.25 s of leading silence before the decode
  (the Pro model card). Timestamps are shifted back by the pad and clamped
  at 0.
- `SegmentInfo.no_speech_prob` is removed. `_assemble` loses its
  `silence_threshold` argument. `_validate_output` stays.
- Timestamps: the result has one `SegmentInfo` per decode. Its words come
  from sherpa token timestamps and durations (TDT frame of 80 ms plus the
  predicted duration). Tokens join into words at the SentencePiece word
  marker. `WordInfo.probability` is `exp` of the mean token log-prob
  (`ys_log_probs`) when sherpa gives it, else 1.0. It is information only;
  nothing gates on it.
- Live and Files keep their VAD phrase times for `TranscriptLine.start/end`
  and speaker assignment. They do not use ASR timestamps.
- Dictation silence: the dictation path runs sherpa Silero VAD (same model
  file and parameters as `PhraseSegmenter`) over the capture first, with
  0.25 s pre-pad on each speech region. No speech means no decode and an
  empty result. `vad_seconds` reports the speech kept. An empty or
  whitespace result is dropped as today.
- Live drops a phrase only when its text is empty. The
  `no_speech_prob >= 0.6` check in `live_session.py` is removed.

### Config

New `AsrConfig`:

```python
@dataclass(frozen=True)
class AsrConfig:
    idle_unload_seconds: int
    cpu_threads: int
```

- `_build_asr` reads only these two keys, with the current ranges.
- The loader already reads named keys only. A config with `model`,
  `compute_type`, `beam_size`, `hotwords`, `initial_prompt`, `vad_filter`
  or `silence_threshold` loads without error and without a warning. A unit
  test proves it.
- `assets/default_config.toml.in` keeps `[stenographer.asr]` with the two
  keys.
- Saves go through the preservation layer. It keeps the user's old keys in
  place; no task deletes them.
- Remove `ALLOWED_COMPUTE_TYPES` and every Config, Setup and Doctor row
  that shows a removed key.

### Attribution

- `src/stenographer/assets/licenses/underdog-bark-3.0-pro-NOTICE.txt`: the
  ConwayResearch NOTICE verbatim, the CC-BY-4.0 link, and "Converted to
  ONNX and quantized to int8 (weight-only) on the user's machine by
  stenographer."
- License notes for Silero VAD (MIT) and TitaNet (per its NeMo license) in
  `assets/licenses/`.
- README "Third-party models" under "License". Each entry has the model,
  authors, license and a link: Underdog Bark 3.0 Pro (Conway Research),
  nvidia/parakeet-tdt-0.6b-v3 (NVIDIA), moondream/parakeet-ultra
  (Moondream, named in the Bark NOTICE), Silero VAD, TitaNet.
- The download output line (see Download).

## Tasks

| Task | Content | Depends on |
| --- | --- | --- |
| S (31) | This spec | none |
| A | Converter asset, pins module, download, free-space and venv checks, Doctor venv warning, manifest, `is_model_cached`. Two conversions to prove determinism; record output sha256. | S |
| B | sherpa backend, token-to-word mapping, 0.25 s pad, dictation VAD, removal of `no_speech_prob` gates | A |
| C | `AsrConfig` cleanup; remove faster-whisper, huggingface_hub, CTranslate2 handling, Whisper keys, bench scripts and their tests; packaging spec; Config, Setup and Doctor rows | B |
| D | README (usage and Third-party models), `docs/` (usage, live, building, transcription-experiments), `site/`, NOTICE files, `FIX.md` (names the `python3-venv` apt step) | A, B, C |

### Gate per task

- **S:** `git diff --name-only dev...HEAD` lists only
  `.hive/spec/bark-pro-asr/` paths.
- **A, B, C:** the AGENTS.md gate:

  ```sh
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
  .venv/bin/pytest -m "not integration"
  .venv/bin/stenographer --help
  ```

  New pure logic gets a unit test that was seen failing first. A also
  shows two converter runs with identical output sha256 and one real
  `stenographer model download --asr` run. B also shows one real decode of
  a public test clip through `Model.transcribe` (no microphone).
- **C** also shows that `grep -rn "faster_whisper\|faster-whisper\|ctranslate2\|huggingface_hub"`
  over `src/`, `tests/`, `packaging/` and `pyproject.toml` finds nothing.
- **D:** the AGENTS.md gate plus `scripts/check_site.sh`. Each removed key
  and each Whisper reference is gone from user docs, except history notes.
- No task uses the microphone. A dictation trial on the real mic happens
  only after reinstall, with the user's consent.

## Limits

- Converter reproducibility across torch versions is unknown. Task A pins
  one version set and tests on this machine only.
- sherpa-onnx on GPU is out of scope (the PyPI wheel is CPU-only).
- The report measured Pro on public speech and system audio, not on
  microphone dictation.
