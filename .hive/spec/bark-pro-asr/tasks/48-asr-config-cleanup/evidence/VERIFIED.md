# Independent verification — task 48

Code reviewed: `abec65e` on `task/48-asr-config-cleanup`.
Base for red runs: `9f77deb`. Platform: Linux, worktree `.venv`, Python 3.14.7.

## Verdict: fail

Requirement 8 requires zero dependency-grep matches. The exact grep returns:

```text
src/stenographer/assets/convert/constraints.txt:14:huggingface_hub==2.2.0
```

V8 records a manager-approved exception, but the brief and spec do not name
that exception. During this verification, the manager confirmed that this
must be recorded as a failure. The manager will update the brief and assign
a worker to update the spec's task C gate. No source repair is claimed here.

## Verification items

| Item | Result | Independent observation |
| --- | --- | --- |
| V1 / requirement 1: config schema, ranges, template | pass | Reviewed models, validation, constants and template. Only `idle_unload_seconds` and `cpu_threads` remain. Ranges remain 0–86400 and 0–64. Config tests pass; `ALLOWED_COMPUTE_TYPES` grep has no matches. |
| V2 / requirement 2: old config load and preservation | pass | Both named old-config tests fail against base and pass against task code. A separate save check using an old accepted `compute_type` fails against base because it adds `hotwords`; it passes against task code and preserves the existing ASR bytes except the requested CPU change. |
| V3 / requirement 3: removed-key surfaces | pass | Reran hub Config, Setup, Doctor, banner, diagnostics, live-session and download-plan tests. Ten surface regressions fail against base and pass against task code. Source grep finds no removed keys. Completion matches are only the unrelated `stats --model` filter. |
| V4 / requirement 4: dependencies and packaging | pass | `pyproject.toml` drops both application dependencies. Packaging removes the old ONNX collection. No CTranslate2 handling remains. Installed package grep has no matches. The converter lock exception fails V8 separately. |
| V5 / requirement 5: old downloader | pass | Old downloader and its unit test are absent. `transcribe.download` / `transcribe import download` grep finds no remaining caller. |
| V6 / requirement 6: scripts and retained modules | pass | All named obsolete scripts are absent, including the already-absent transcription benchmark. Retained script tests: 50 passed. Moonshine and `select_clips` import successfully; Moonshine `--help` succeeds. Collection: 2778 tests, no errors. |
| V7 / requirement 7: 10 GiB floor | pass | Threshold and plan regressions fail against base (8 GiB), then pass against task code (10 GiB). Spec Download section and initial download step require 10 GiB; 8 GiB remains only as history. |
| V8 / requirement 8: zero-match greps | fail | Dependency grep returns the converter lock pin shown above. Removed-key grep over source returns nothing; test source matches occur only in the two old-config regression tests. Binary cache matches also refer to those tests. |
| V9 / requirement 9: build allowlists | pass | No dedicated allowlist checker is documented. Compared Git rules with Hatch excludes: only the four documented repository-only `.hive/` rules differ. Remaining rules have identical order. No policy changes on branch. No PyInstaller build was run. |
| V10: repository gate | pass | Ruff check passes; format check reports 813 files formatted; pytest reports 2770 passed, 1 skipped, 7 deselected; CLI help succeeds. Neither named timing flake failed. |

## Red and green runs

Used `git archive 9f77deb src` in a scratch directory, with
`PYTHONPATH=<scratch>/src .venv/bin/python -m pytest -q --tb=short` and current
tests. All 14 selected tests failed for the intended changed behavior:

- `tests/lib/config/test_models.py::test_an_old_whisper_config_loads_without_error_or_warning`
- `tests/lib/config/test_document.py::test_save_keeps_removed_whisper_keys_byte_for_byte`
- `tests/lib/diagnostics/test_collection.py::test_technical_context_names_the_bark_model_and_no_whisper_setting`
- `tests/lib/diagnostics/test_session.py::test_an_enabled_session_records_the_host_context_it_was_given`
- `tests/cli/doctor/test_report.py::test_render_names_the_bark_model`
- `tests/cli/hub/test_setup_doctor.py::test_the_models_step_names_the_bark_model_and_no_config_key`
- `tests/cli/hub/test_setup_doctor.py::test_build_report_groups_fake_host_checks_and_counts_warnings`
- `tests/cli/run/test_banner.py::test_banner_asr_line_reports_exactly_the_model_and_the_two_asr_keys`
- `tests/cli/setup/test_workflow.py::test_edit_asr_asks_only_the_two_recognition_keys_in_order`
- `tests/lib/live/test_live_session.py::test_live_session_queues_sources_in_order_filters_d12_and_drains_on_stop`
- `tests/cli/hub/test_config.py::test_config_settings_use_one_compact_name_value_row_per_key`
- `tests/cli/hub/test_config.py::test_config_board_layout_has_group_selector_settings_and_help_panels`
- `tests/lib/transcribe/test_bark_download.py::test_free_space_rule_needs_at_least_ten_gib`
- `tests/cli/model/download/test_handler.py::test_the_confirmation_states_both_models_their_sizes_and_the_host`

The base no longer has faster-whisper installed, so the diagnostic session
regression fails with missing `runtime_version`, rather than the worker's
old version-string difference. The old backend looks up the removed runtime.

Green command, using the task source and full modules containing those tests:

```sh
.venv/bin/pytest -q tests/lib/config/test_models.py tests/lib/config/test_document.py tests/lib/diagnostics/test_collection.py tests/lib/diagnostics/test_session.py tests/cli/doctor/test_report.py tests/cli/hub/test_setup_doctor.py tests/cli/run/test_banner.py tests/cli/setup/test_workflow.py tests/lib/live/test_live_session.py tests/cli/hub/test_config.py tests/lib/transcribe/test_bark_download.py tests/cli/model/download/test_handler.py
```

Result: **419 passed in 28.29s**.

## Exact gate rerun

```text
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
813 files already formatted
.venv/bin/pytest -m "not integration"
2770 passed, 1 skipped, 7 deselected in 108.62s
.venv/bin/stenographer --help
Successful usage output and command list; exit 0.
```

The skip is the existing speaker-tracker test whose public clips are absent.
The project is Python; the brief's four-command gate applies, not the Hive Go gate.

## Static checks and bundle analysis

Reran the required commands:

```sh
grep -rn "faster_whisper\|faster-whisper\|ctranslate2\|huggingface_hub" src/ tests/ scripts/ packaging/ pyproject.toml
grep -rn "compute_type\|beam_size\|hotwords\|initial_prompt\|vad_filter\|silence_threshold" src/
grep -rn "compute_type\|beam_size\|hotwords\|initial_prompt\|vad_filter\|silence_threshold" tests/
grep -rni silero packaging/ pyproject.toml
find src -name '*.onnx'
grep -rn 'silero_vad.onnx' src/
grep -rn 'transcribe.download\|transcribe import download\|ALLOWED_COMPUTE_TYPES' src/ tests/ scripts/
```

No Silero packaging reference or source ONNX file remains. The download handler
and hub select the pinned `LIVE_MODELS` entry. The daemon opens
`<data_dir>/models/live/silero_vad.onnx`. No remaining application reference
requires the removed bundled Whisper Silero asset. A frozen bundle was not
built or tested.

The spec's Boards decision waives approved boards for these text-only changes.
Headless hub tests check the rendered text and selection glyphs. No PNG visual
comparison was performed. The current text retains selection and change glyphs;
colour is not their sole signal. No native-platform acceptance is claimed.

No microphone, real model decode, download, integration test, `live`, or `run`
command was used. Scratch source archives and the temporary preservation check
were removed, and their absence was checked. No existing user data was removed.
No implementation file or worker evidence file was edited.
