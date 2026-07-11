---
id: FTHR-002
title: Config surface for prompt mode
plumage: PLM-002
status: hatching
priority: P1
depends_on: []
authored: 2026-07-11T05:51:00Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# FTHR-002: Config surface for prompt mode

## Description
Add the two pieces of configuration every other prompt-mode feather depends on: a `hotkey.prompt_binding` key (the Right Shift trigger) on the existing `HotkeyConfig`, and a new top-level `LlmConfig` section (`[stenographer.llm]`) carrying the local-LLM connection settings (base_url, model, system_prompt, timeout_seconds, temperature, max_tokens), each with a working default. No hotkey listener, session routing, or LLM call happens in this feather — it only makes the values loadable, validated, and defaulted. Satisfies PLM-002 FC-3 (partially — the config half; FC-1/FC-2 are delivered by later feathers that consume these values).

## Affected Modules
Per `.fledge/nest/data-model.md` (`Config`/nested dataclass shapes) and `.fledge/nest/conventions.md` (config loading/validation conventions):
- `src/stenographer/config.py` — add `prompt_binding: str` to `HotkeyConfig`; add new `LlmConfig` frozen dataclass; add `llm: LlmConfig` field to `Config`; extend `Config.defaults()`, `_build_hotkey()` (parse/validate `prompt_binding` as a `HotkeyBinding`, mirroring how `cancel_binding` is validated and checked for chord overlap with `binding`), a new `_build_llm()` validator (mirroring `_build_update()`'s URL/timeout validation style), `Config._from_dict()` wiring, and `_format_default_toml()`'s default-TOML text generation.
- `tests/test_config.py` — new tests for the added fields; existing hotkey-parsing tests are the pattern to follow.

## Approach
- `HotkeyConfig` gains `prompt_binding: str`. `Config.defaults()` sets it to `"KEY_RIGHTSHIFT"`. `_build_hotkey()` parses it via `HotkeyBinding.parse()` exactly like `cancel_binding`, and — like the existing `cancel_binding`-vs-`binding` overlap check — rejects (`ConfigError`) if `prompt_binding` shares evdev keys with `binding` (an explicit prompt_binding overlapping the main binding is always an error, since unlike `cancel_binding` there's no defaults-only leniency case to preserve — a user who hasn't touched either key gets the non-overlapping shipped defaults `KEY_RIGHTCTRL`/`KEY_RIGHTSHIFT`).
- New `LlmConfig` frozen dataclass: `base_url: str`, `model: str`, `system_prompt: str`, `timeout_seconds: float`, `temperature: float`, `max_tokens: int`.
- `Config.defaults()` sets: `base_url="http://localhost:8080"`, `model=""` (empty = let the server pick/ignore, since not every local server requires a model name), `system_prompt=` the agreed reformatting instruction, `timeout_seconds=30.0`, `temperature=0.2` (low, for deterministic reformatting), `max_tokens=512` (comfortably above a typical reformatted prompt's length).
- `_build_llm()` validates: `base_url` non-empty and starts with `http://`/`https://` (same style as `_build_update`'s `base_url` check; strip trailing `/`); `system_prompt` non-empty; `timeout_seconds` in `(0, 300]`; `temperature` in `[0, 2]`; `max_tokens` in `[1, 8192]`. `model` has no format constraint (empty string allowed).
- Wire `llm=_build_llm(table["llm"], path)` into `Config._from_dict()`, and add an `LlmConfig` section to `_format_default_toml()`'s generated default config text (following the existing `# Update` section's style, with a comment noting these values must match a locally-reachable OpenAI-compatible server).

## Tests
All in `tests/test_config.py`, following the file's existing `_build_x`/defaults/validation-range test patterns:
- `test_defaults_include_prompt_binding` — `Config.defaults().hotkey.prompt_binding == "KEY_RIGHTSHIFT"`.
- `test_prompt_binding_overlap_with_main_binding_rejected` — a config setting `hotkey.prompt_binding` to the same key as `hotkey.binding` raises `ConfigError`.
- `test_prompt_binding_invalid_key_rejected` — an unparseable `hotkey.prompt_binding` string raises `ConfigError` (mirrors the existing invalid-`binding`/`cancel_binding` tests).
- `test_defaults_include_llm_config` — `Config.defaults().llm` has the defaults listed above.
- `test_llm_base_url_must_be_http` — a non-http(s) `llm.base_url` raises `ConfigError`.
- `test_llm_timeout_out_of_range_rejected` — `llm.timeout_seconds` outside `(0, 300]` raises `ConfigError`.
- `test_llm_temperature_out_of_range_rejected` — `llm.temperature` outside `[0, 2]` raises `ConfigError`.
- `test_llm_max_tokens_out_of_range_rejected` — `llm.max_tokens` outside `[1, 8192]` raises `ConfigError`.
- `test_load_full_config_with_llm_overrides` — a TOML fixture overriding every new `[stenographer.llm]` field round-trips correctly through `Config.load()`.

Implementation order: write all tests above, run against the unchanged code and confirm every one fails for the expected reason (missing fields/`AttributeError`, or validation not yet implemented), then implement `LlmConfig`/`prompt_binding` end to end until all pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: `Config.defaults()` exposes `hotkey.prompt_binding` and a fully-defaulted `llm` section as specified (satisfies PLM-002 FC-3 for the config layer).
- [x] AC-3: Invalid values for every new field (`prompt_binding` overlap/unparseable, `llm.base_url`/`timeout_seconds`/`temperature`/`max_tokens` out of range) are rejected with `ConfigError`, matching this codebase's existing validation conventions.
- [x] AC-4: `.venv/bin/pytest -m "not integration"` passes with no regressions to existing config tests.
