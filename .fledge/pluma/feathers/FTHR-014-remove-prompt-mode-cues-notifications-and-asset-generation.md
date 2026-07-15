---
id: FTHR-014
title: "Remove prompt-mode cues, notifications, and asset generation"
plumage: PLM-007
status: egg
priority: P1
depends_on: [FTHR-013]
authored: 2026-07-15T17:57:35Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.4
---

# FTHR-014: Remove prompt-mode cues, notifications, and asset generation

## Description
Removes the remaining prompt-mode surface that FTHR-013 leaves orphaned but harmless once its routing/config is gone: the four pitched-down prompt audio cue names and their generation, the five prompt-related desktop-notification methods, and the cue-remapping adapter in `cli.py`. After this feather, no cue name, notification string, or generated asset anywhere in the codebase implies a "prompt" mode ever existed.

## Affected Modules
See `.fledge/nest/modules.md` → "src/stenographer/audio" (cue playback) and "scripts" (`gen_cues.py` asset generation); `.fledge/nest/architecture.md` → "Cross-cutting policies" (`notification.py`).

- `src/stenographer/audio/feedback.py` — remove `"ptt_on_prompt"`, `"ptt_off_prompt"`, `"toggle_on_prompt"`, `"toggle_off_prompt"` from the `CueName` `Literal` (leaves the other 11 cue names untouched).
- `src/stenographer/notification.py` — remove `show_listening_prompt`, `show_transcribing_prompt`, `show_rewriting`, `show_prompt_ready`, `show_prompt_failed` methods.
- `src/stenographer/cli.py` — remove `_PROMPT_CUE_REMAP` and the `_PromptCueAdapter` class (the block directly above `_build_feedback`, ~lines 122–143).
- `scripts/gen_cues.py` — remove the `"ptt_on_prompt"`, `"ptt_off_prompt"`, `"toggle_on_prompt"`, `"toggle_off_prompt"` entries from `build_cues()`.
- Delete the 4 generated assets: `src/stenographer/assets/sounds/ptt_on_prompt.wav`, `ptt_off_prompt.wav`, `toggle_on_prompt.wav`, `toggle_off_prompt.wav`.
- `tests/test_notification.py` — remove `test_show_listening_prompt_enqueues_persistent_notification`, `test_show_transcribing_prompt_enqueues_persistent_notification`, `test_show_rewriting_enqueues_persistent_notification`, `test_show_prompt_ready_enqueues_transient_notification`, `test_show_prompt_failed_enqueues_transient_notification`, `test_prompt_stage_wording_distinct_from_dictate_stage_wording`.
- `tests/test_gen_cues.py` — remove `test_build_cues_includes_pitched_down_prompt_variants`.
- `tests/test_cli.py` — remove `test_prompt_cue_adapter_remaps_start_stop_cues` and `test_prompt_cue_adapter_passes_through_other_cues_unchanged`.

## Approach
Pure subtraction, no new abstractions. `CueName`'s `Literal` shrinking to 11 entries is automatically picked up everywhere it's consumed (`typing.get_args(CueName)` in `config.py`'s `CUE_NAMES`, the `cues` dict default in `FeedbackConfig`) — no code changes needed there beyond what FTHR-013 already touched, since `config.py`'s `dict.fromkeys(CUE_NAMES, None)` derives from the `Literal` at runtime. Delete `_PromptCueAdapter` and its remap table as a single unit — nothing else references them once FTHR-013's wiring block is gone (confirmed: `_build_session` no longer constructs one after FTHR-013 merges). Delete the 4 `.wav` files with `git rm` so their removal is tracked in the commit, not left as untracked deletions.

## Tests
Adjust existing suites in place (each fails immediately once the corresponding cue/method/adapter is deleted, since the test currently asserts it exists/works):
- `tests/test_notification.py` — after removing the 6 tests above, the remaining suite (unaffected `show_startup`/`show_listening`/`show_transcribing`/`show_model_*`/`hide` tests) still passes unmodified; satisfies part of PLM-007 FC-5.
- `tests/test_gen_cues.py::test_build_cues_excludes_prompt_variants` (new) — `build_cues(44100)` returns a dict whose keys contain none of `ptt_on_prompt`, `ptt_off_prompt`, `toggle_on_prompt`, `toggle_off_prompt`; satisfies FC-5.
- `tests/test_cli.py` — after removing the 2 adapter tests, confirm `cli._PromptCueAdapter` and `cli._PROMPT_CUE_REMAP` no longer exist (`hasattr(cli, "_PromptCueAdapter")` is False) — add this as a new one-line test `test_cli_has_no_prompt_cue_adapter`; satisfies FC-5.
- Manual/scripted check (recorded as evidence, not a pytest test): running `python scripts/gen_cues.py` (or its `build_cues`) and listing `src/stenographer/assets/sounds/` shows no `*_prompt.wav` files remain.

Implementation order: write/adjust the 2 new test cases above plus the notification/gen_cues/cli suite prunings against the unchanged (FTHR-013-merged) code, capture them FAILING (e.g. assertion mismatch, `AttributeError`) in `.fledge/molt/FTHR-014.md` under `## AC-1`, then implement the removal until they pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: `CueName` contains exactly the 11 non-prompt cue names (`ptt_on`, `ptt_off`, `toggle_on`, `toggle_off`, `cancel`, `discard`, `error`, `segment`, `transcribe_done`, `model_loading`, `model_ready`) — `typing.get_args(CueName)` confirms no `*_prompt` entries. Satisfies PLM-007 FC-5.
- [x] AC-3: `Notification` (in `notification.py`) has none of `show_listening_prompt`, `show_transcribing_prompt`, `show_rewriting`, `show_prompt_ready`, `show_prompt_failed`. Satisfies PLM-007 FC-5.
- [x] AC-4: `cli._PromptCueAdapter` and `cli._PROMPT_CUE_REMAP` do not exist. Satisfies PLM-007 FC-5.
- [x] AC-5: `scripts/gen_cues.py`'s `build_cues()` output contains no `*_prompt` keys, and none of the 4 `*_prompt.wav` files exist under `src/stenographer/assets/sounds/`. Satisfies PLM-007 FC-5.
- [x] AC-6: `.venv/bin/pytest -m "not integration"` and `.venv/bin/ruff check .` / `.venv/bin/ruff format --check .` pass for the full repo (both feathers combined). Satisfies PLM-007 FC-9 in full.
- [x] AC-7: `grep -riE "llm|prompt" src/ tests/`, excluding the known non-feature hits in `live.py`/`update.py`/`_parser.py`/`packaging/install.sh` and generic English words, returns no LLM-rewrite-feature references. Satisfies PLM-007 AC-1 (full-repo check).
