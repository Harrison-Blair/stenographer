# Independent verification — task 57-changelog-v0160

Date: 2026-10-22. Verdict: **pass**.

Reviewed commit: `df660183d26fc7e5c1184a5019a5fadec808060d`.
Base: `32f7806`. Branch: `task/57-changelog-v0160`.
All commands ran from the task worktree with its existing `.venv` (Python 3.14.7).
The verifier did not change production files, tests, worker evidence, or the tracker.

## Requirements

| Item | Result | Observation |
| --- | --- | --- |
| 1. Release heading and convention | pass | The entry starts with `## [v0.16.0] - 2026-10-22`. An empty `[Unreleased]` remains above it. `docs/building.md:34` permits this, and the parser and its tests accept it. Earlier release headings use the same form. |
| 2. Changes since v0.15.0 | pass | Read `git log v0.15.0..origin/dev`. The entry covers the Files start folder and fallback, optional microphone diarization, Sessions re-diarization, and Bark replacement. The later origin/dev documentation merge does not change these behaviors. Claim checks are below. |
| 3. Entry shape and content | pass | The synopsis precedes Added and Removed. There is no empty Fixed section. The parser accepts the structure. No planning list, commit list, FIX.md reference, transcript text, or recording content appears in the new entry. Links are inline; no reference definitions need an update. |
| 4. Red/green proof, release tests, and gate | pass | Independent runs are below. The base check and updated release-list assertion fail for the expected missing release. All current checks pass. |
| 5. Scope and delivery | pass | Product changes are limited to CHANGELOG.md and the necessary one-line release-list test update. Other committed files are the brief and worker evidence. Commit `121f1d1` has the required subject and no trailers. The test update is in `a045c30`. The remote task branch matched the reviewed commit. Hive reported task status `completed` before verification. |

## Claim checks

- Files: `cli/hub/services.py` supplies `<data_dir>/sessions` through
  `files_start_folder`; `app.py` passes it to `FilesPanel`; `files_view.py`
  falls back to the home folder when the start folder is absent.
  `docs/hub.md:97-102` describes this behavior.
- Microphone: `lib/config/models.py` defaults `diarize_mic` to false.
  `docs/live.md:54-77`, `docs/usage.md:251-260`, and `docs/hub.md:63-64`
  describe the flags, Config setting, Room labels, rename action, and You default.
- Sessions: `cli/hub/session_jobs.py:53-54` includes the microphone pass only
  when the saved session has microphone diarization. `docs/hub.md:150-153`
  states the same restriction. System labels remain separate.
- Bark: `lib/transcribe/model.py` loads the int8 transducer through sherpa-onnx
  with `provider="cpu"`. `lib/daemon/pipeline.py` applies the speech filter
  before decode and skips decode when no speech remains.
- Build: `bark_pins.py` pins source hashes, converter packages, and output
  hashes; `bark_download.py` checks sources and output hashes and sets
  `MIN_FREE_BYTES = 10 * 1024**3`. README.md:109-111 and docs/usage.md:31-37
  give about 1.6 GB download and about 10.2 GiB conversion RAM.
  The download handler also installs Silero. The venv preflight and Doctor
  guidance agree with the entry.
- CPU conversion: reviewed `7b4700f` and
  `assets/convert/bark_pro_to_sherpa.py`. The converter uses Decimal constants
  to remove CPU-dependent float32 rounding; `bark_pins.py` records matching
  AVX-512, AVX2, and scalar outputs. The entry describes the user-visible
  hash-check effect under Added. It does not list this as a released bug fix.
- Removal: reviewed `38e2e68` and `ecd2d5e`. AsrConfig retains only
  `idle_unload_seconds` and `cpu_threads`; the old fields and hotwords surface
  are removed. Preservation tests pass. Live/Files cards no longer expose
  compute type. The Whisper dependencies and named bench/study scripts are
  removed. Attribution files exist in `src/stenographer/assets/licenses/`.
- Fillers and refine: Bark does not apply Whisper filler cleanup;
  RefineConfig retains the default `min_words = 10`, consistent with the docs.

These are source and documentation checks. No model download, conversion,
microphone capture, or cross-CPU execution was performed for this changelog task.
No interface implementation changed, so visual-board verification does not apply.

## Independent command results

| Command or check | Result | Output |
| --- | --- | --- |
| `git show 32f7806:CHANGELOG.md > .hive/tmp/57-base-changelog.md`, then `.venv/bin/python scripts/release_notes.py check 0.16.0 .hive/tmp/57-base-changelog.md` | pass | Expected exit 1: `release notes check failed: no release entry for v0.16.0`. |
| `.venv/bin/python scripts/release_notes.py check 0.16.0 CHANGELOG.md` | pass | Exit 0: `release note found: v0.16.0 (2026-10-22)`. |
| Updated release-list test against the base changelog in an isolated scratch tree | pass | Expected exit 1: `test_repository_changelog_covers_every_authored_release_note` fails at index 0: actual `v0.15.0`, expected `v0.16.0`. The scratch tree used copies of the current test and parser, and the base changelog. No checkout file was changed. |
| `.venv/bin/pytest tests/test_release_notes.py -q` | pass | 40 passed in 0.07s; repeated after the red run: 40 passed in 0.20s. |
| `.venv/bin/ruff check .` | pass | `All checks passed!` |
| `.venv/bin/ruff format --check .` | pass | `830 files already formatted` |
| `.venv/bin/pytest -m "not integration"` | pass | 2770 passed, 1 skipped, 7 deselected in 111.96s. The skip names absent public speaker clips in tmp/live_audio. No timing flake failed; no five-run retry was needed. |
| `.venv/bin/stenographer --help` | pass | Exit 0. Help shows offline dictation and the run, live, transcribe, model, doctor, devices, setup, sounds, completion, and stats commands. |
| `git diff 32f7806 HEAD --check` | pass | No output. |

The task and repository specify the four-command Python gate above. The generic
Go gate does not apply to this Python project. Integration tests were not enabled.
All verifier scratch files were removed, and their absence was checked. The
worktree was clean before this report was written. Reinstallation was not run.
