---
id: FTHR-013
title: "Remove prompt-mode routing, LLM config, and rebind default hotkey"
plumage: PLM-007
status: fledged
priority: P1
depends_on: []
authored: 2026-07-15T17:55:03Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.4
---

# FTHR-013: Remove prompt-mode routing, LLM config, and rebind default hotkey

## Description
Removes the LLM rewrite ("prompt") mode's functional core entirely — the `stenographer.llm` module, its config schema, and every routing path in `Session` and `cli.py` that feeds a recording into it — and changes the default dictation hotkey binding from `KEY_RIGHTCTRL` to `KEY_RIGHTALT`, with `hotkey.prompt_binding` removed from the schema (not merely defaulted off). After this feather the daemon has exactly one hotkey listener and no LLM dependency; the cue/notification/asset surface prompt mode used is left as unused-but-harmless code for FTHR-014 to remove.

## Affected Modules
See `.fledge/nest/modules.md` → "src/stenographer (core: cli, config, session, cross-cutting)" and `.fledge/nest/architecture.md` → "Cross-cutting policies" / "The orchestrator: Session".

- `src/stenographer/llm.py` — delete entirely (`rewrite_prompt`, module-level LLM client logic).
- `tests/test_llm.py` — delete entirely.
- `src/stenographer/config.py` — remove `LlmConfig` dataclass, the `llm: LlmConfig` field on `Config`, `_build_llm`, the `llm=_build_llm(...)` call in `_from_dict`, the `llm.*` block in `_format_default_toml`; remove `HotkeyConfig.prompt_binding`, its default, its `_build_hotkey` parsing/validation (overlap checks against `hotkey.binding`/`hotkey.cancel_binding`), and its TOML emit line; flip `HotkeyConfig.binding` default from `"KEY_RIGHTCTRL"` to `"KEY_RIGHTALT"` in `Config.defaults()`.
- `src/stenographer/session.py` — remove the deferred `importlib.import_module("stenographer.llm")` + `rewrite_prompt` block in `_process` (~lines 683–705), the `prompt_llm_failed` bookkeeping around it, every `source == "prompt"` branch (recording-start silence/streaming bypass, transcribing notification, discard/cancel-ownership checks), `attach_prompt_listener`, `_prompt_listener` attribute and its `start()`/`stop()` lifecycle calls, and narrow `Literal["dictate", "prompt"]` back to a single `"dictate"` (or drop the `source` parameter's second value — keep `source` as a parameter since `dictate` invocations still pass it, but its type no longer admits `"prompt"`).
- `src/stenographer/cli.py` — remove the prompt-hotkey listener construction/wiring block (~lines 275–294: `HotkeyBinding.parse(cfg.hotkey.prompt_binding)`, second `HotkeyStateMachine`/`HotkeyListener`, `session.attach_prompt_listener(...)`).
- `src/stenographer/errors.py` — remove `LlmError`.
- `tests/test_config.py` — remove `test_defaults_include_prompt_binding`, `test_defaults_include_llm_config`, `test_prompt_binding_overlap_with_main_binding_rejected`, `test_prompt_binding_invalid_key_rejected`, `test_prompt_binding_empty_disables_prompt_mode`, `test_prompt_binding_null_disables_prompt_mode`, `test_prompt_binding_overlap_with_cancel_binding_rejected`, `test_prompt_binding_overlap_with_explicit_cancel_binding_rejected`, `test_llm_base_url_must_be_http`, `test_llm_timeout_out_of_range_rejected`, `test_llm_temperature_out_of_range_rejected`, `test_llm_max_tokens_out_of_range_rejected`, `test_load_full_config_with_llm_overrides`; update the `LlmConfig` import and any fixture building a `Config`/`HotkeyConfig` with `prompt_binding=`/`llm=` kwargs.
- `tests/test_session.py` — remove `test_prompt_mode_lazy_model_load_shows_prompt_listening_notification`, `test_prompt_stop_during_stale_final_decode_takes_batch_path`, `_fake_llm_module`/`_process_prompt` helpers, `test_prompt_mode_recording_calls_rewrite_prompt`, `test_prompt_mode_types_rewritten_text_not_raw_transcript`, `test_prompt_mode_falls_back_to_raw_transcript_on_llm_error`, `test_prompt_mode_llm_failure_plays_only_error_cue_not_transcribe_done`, `test_prompt_mode_paste_mode_uses_rewritten_text_not_reformatted`, `test_session_processor_survives_llm_connection_failure`, `test_dictate_mode_unaffected_by_prompt_mode_addition`, `test_prompt_mode_hotkey_independent_trigger_rules`, `test_prompt_mode_never_streams`, `test_prompt_mode_disables_silence_flush_segments`, `test_prompt_stop_ignored_while_dictate_recording_active`, `test_dictate_stop_ignored_while_prompt_recording_active`, `test_prompt_tap_discard_ignored_while_dictate_recording_active`, `test_owner_discard_still_discards_prompt_recording`, `test_prompt_mode_recording_start_shows_prompt_listening_notification`, `test_prompt_mode_recording_stop_shows_prompt_transcribing_notification`, `test_prompt_mode_llm_call_shows_rewriting_notification`, `test_prompt_mode_success_shows_prompt_ready_notification`, `test_prompt_mode_llm_failure_shows_prompt_failed_notification`, and the `LlmConfig` import; in `test_dictate_mode_notifications_unchanged`, drop the `notif.show_listening_prompt.assert_not_called()` / `notif.show_transcribing_prompt.assert_not_called()` / `notif.show_rewriting.assert_not_called()` / `notif.show_prompt_ready.assert_not_called()` / `notif.show_prompt_failed.assert_not_called()` lines (the methods they reference are removed in FTHR-014; these mock-assertions don't hard-fail either way since `notif` is an unspec'd `MagicMock`, but they reference dead concepts and must go per FC-9/AC-1's no-references check) while keeping its `show_listening`/`show_transcribing` assertions; keep every other `test_dictate_*`-equivalent (non-prompt) case intact and unmodified in behavior.
- `tests/test_cli.py` — remove `test_prompt_listener_discard_is_source_tagged` and `test_empty_prompt_binding_disables_prompt_listener` (both exercise the wiring block this feather deletes); update `test_dictate_listener_uses_unmapped_feedback` — after this feather `cli._build_session` constructs exactly one `HotkeyListener`, so change its `assert len(calls) == 2` to `assert len(calls) == 1` and drop the `prompt_feedback`-related assertions, keeping only the check that `calls[0]["feedback"]` is a plain `Feedback` instance; leave `test_prompt_cue_adapter_*` tests untouched (they exercise `_PromptCueAdapter`/`_PROMPT_CUE_REMAP`, which belong to FTHR-014's removal).

## Approach
This is a subtractive change with one added behavior (the new hotkey default) and one schema simplification (removing `prompt_binding`/`llm`). No new abstractions: delete the dead branches, narrow the `Literal` type so the type checker/reader can see `source` is always `"dictate"`, and let `_merge()`'s existing lenient-unknown-key behavior in `config.py` handle stray `llm`/`prompt_binding` keys in old config files (no new validation code — confirmed no such validation exists anywhere else in the schema). Keep `hotkey.cancel_binding`'s overlap-checking logic for `hotkey.binding` untouched (only the `prompt_binding`-vs-`binding`/`cancel_binding` overlap checks are removed, since prompt_binding itself is gone). In `session.py`, deleting the `source == "prompt"` branches should leave the `dictate`-path logic exactly as it reads today — resist any temptation to refactor the surviving code along the way (surgical-changes discipline).

## Tests
Adjust the existing suites in place (all failing-then-passing, since removing config fields/functions makes the old prompt-mode tests fail to import/construct immediately once the code is deleted):
- `tests/test_config.py::test_defaults_have_no_prompt_binding_field` (new) — `Config.defaults().hotkey` has no `prompt_binding` attribute (`hasattr` is False); satisfies FC-3.
- `tests/test_config.py::test_defaults_have_no_llm_field` (new) — `Config` has no `llm` attribute; satisfies FC-1.
- `tests/test_config.py::test_default_hotkey_binding_is_right_alt` (new) — `Config.defaults().hotkey.binding == "KEY_RIGHTALT"`; satisfies FC-4, FC-7.
- `tests/test_config.py::test_legacy_llm_and_prompt_binding_keys_ignored` (new) — a config file with `[stenographer.llm]` table + `hotkey.prompt_binding = "KEY_RIGHTALT"` loads via `Config.load()` without raising; satisfies FC-8.
- `tests/test_config.py::test_format_default_toml_has_no_llm_or_prompt_binding` (new) — `_format_default_toml()`'s output contains no `llm.` or `prompt_binding` substring and does contain `hotkey.binding = "KEY_RIGHTALT"`; satisfies FC-7.
- `tests/test_session.py::test_session_has_no_attach_prompt_listener` (new) — `Session` has no `attach_prompt_listener` attribute; satisfies FC-2.
- `tests/test_cli.py` — existing non-prompt tests continue to pass unmodified after the wiring block is removed (regression guard for FC-2).
- All remaining (pruned) test files pass with the deleted tests gone, not skipped.

Implementation order: write/adjust the 6 new/changed test cases above against the unchanged code, capture them FAILING (e.g. `AttributeError`/`ImportError`/assertion mismatch) in `.fledge/molt/FTHR-013.md` under `## AC-1`, then implement the removal until they pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: `stenographer.llm` and `tests/test_llm.py` do not exist; no import of `stenographer.llm` remains anywhere in `src/` or `tests/`. Satisfies PLM-007 FC-1.
- [x] AC-3: `Session` has no `attach_prompt_listener` method, no `_prompt_listener` attribute, and no code path checks `source == "prompt"`. Satisfies PLM-007 FC-2.
- [x] AC-4: `HotkeyConfig` has no `prompt_binding` field (attribute access raises `AttributeError`) and no config-loading code references it. Satisfies PLM-007 FC-3.
- [x] AC-5: `Config.defaults().hotkey.binding == "KEY_RIGHTALT"`; `Config.defaults().hotkey.cancel_binding == "KEY_ESC"` (unchanged). Satisfies PLM-007 FC-4.
- [x] AC-6: `LlmError` does not exist in `stenographer.errors`. Satisfies PLM-007 FC-6.
- [x] AC-7: `_format_default_toml()` emits no `llm.*` lines and no `hotkey.prompt_binding` line, and does emit `hotkey.binding = "KEY_RIGHTALT"`. Satisfies PLM-007 FC-7.
- [x] AC-8: Loading a config file with a stray `[stenographer.llm]` table and `hotkey.prompt_binding` key succeeds without raising. Satisfies PLM-007 FC-8.
- [x] AC-9: `.venv/bin/pytest -m "not integration"` and `.venv/bin/ruff check .` / `.venv/bin/ruff format --check .` all pass with the changes in this feather's Affected Modules. Contributes to PLM-007 FC-9 (full FC-9 also depends on FTHR-014).
