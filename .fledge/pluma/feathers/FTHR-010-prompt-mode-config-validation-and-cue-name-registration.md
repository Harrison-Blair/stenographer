---
id: FTHR-010
title: Prompt-mode config validation and cue-name registration
plumage: PLM-004
status: pipping
priority: P1
depends_on: []
authored: 2026-07-15T05:23:29Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# FTHR-010: Prompt-mode config validation and cue-name registration

## Description
Two independent config-loading bugs in `config.py`, both in prompt mode's config surface:
- `_build_hotkey` checks `hotkey.prompt_binding` for key overlap against `hotkey.binding` but not `hotkey.cancel_binding`; setting `prompt_binding` to the same keys as `cancel_binding` (e.g. its `KEY_ESC` default) loads without error, and the prompt listener then silently arms the cancel chord on every prompt press (F5).
- `config.py`'s hand-maintained `CUE_NAMES` tuple was never updated with the four prompt cue names (`ptt_on_prompt`, `ptt_off_prompt`, `toggle_on_prompt`, `toggle_off_prompt`) that exist in `feedback.py`'s `CueName` Literal, so overriding any of them in `feedback.cues.*` raises `ConfigError` and the daemon refuses to start (F6).

Both fixes land in `config.py`; this feather ships them together rather than as two feathers touching the same file for no parallelism benefit. Satisfies PLM-004 FC-1 (prompt_binding/cancel_binding overlap), FC-2 (CUE_NAMES derived from CueName), FC-3 (prompt cue names now valid overrides), FC-4 (unknown cue names still rejected).

## Affected Modules
Per `.fledge/nest/data-model.md` (Config/HotkeyConfig/FeedbackConfig field reference) and `.fledge/nest/entry-points.md` (config load/validate entry points):
- `src/stenographer/config.py` — `_build_hotkey` (add the `prompt_binding` vs `cancel_binding` overlap check) and `CUE_NAMES` (change from a hand-written tuple to one derived from `stenographer.audio.feedback.CueName`).
- `tests/test_config.py` — new tests, following this file's existing `tmp_path`/`Config.load(p)`/`pytest.raises(ConfigError, match=...)` pattern (see e.g. `test_prompt_binding_overlap_with_main_binding_rejected`, `test_validate_cue_unreadable_file_rejected`).

## Approach
- **F5 fix** in `_build_hotkey`: immediately after the existing `prompt_binding` vs `binding` overlap check (config.py ~L336-350), add an equivalent check against `cancel_binding`'s keys — `overlap = set(prompt.keys) & set(HotkeyBinding.parse(cancel_binding).keys) if cancel_binding else set()`; if `overlap`, raise `ConfigError(path, "hotkey.prompt_binding", f"must not share keys with hotkey.cancel_binding: {shared}")`, mirroring the exact message/exception shape of the existing `prompt_binding` vs `binding` check (unconditional hard error, no defaults-vs-explicit distinction, per this plumage's interrogation). Must run after `cancel_binding`'s own defaults-vs-explicit resolution earlier in the function, so it checks against the *final* resolved `cancel_binding` value (which may have been reset to `""` by that earlier logic).
- **F6 fix**: change `CUE_NAMES` from a hand-written `tuple[str, ...]` literal to `CUE_NAMES: tuple[str, ...] = typing.get_args(CueName)`, importing `CueName` from `stenographer.audio.feedback` (add `import typing` if not already present; verify no circular import — `feedback.py` does not import `config.py`, confirmed during interrogation). `_build_cues`'s existing `if name not in CUE_NAMES: raise ConfigError(...)` logic is untouched — it now validates against the derived tuple, which is a superset of the old hand-written one (adds exactly the four prompt cue names) and nothing else, so no existing valid config becomes invalid and no existing invalid config becomes valid apart from the four intended additions.

## Tests
All in `tests/test_config.py`:
- `test_prompt_binding_overlap_with_cancel_binding_rejected` — a config with `hotkey.prompt_binding` set to `"KEY_ESC"` (the `cancel_binding` default) raises `ConfigError` matching `r"hotkey.prompt_binding"`.
- `test_prompt_binding_overlap_with_explicit_cancel_binding_rejected` — a config setting both `hotkey.cancel_binding` and `hotkey.prompt_binding` to the same explicit non-default key raises `ConfigError` matching `r"hotkey.prompt_binding"`.
- `test_prompt_cue_names_accepted_as_overrides` — for each of the four prompt cue names, a config overriding `feedback.cues.<name>` with a real readable file (mirroring `test_validate_cue_readable_file_accepted`'s tmp-file pattern) loads successfully and `Config.load(p).feedback.cues[<name>]` reflects the override.
- `test_unknown_cue_name_still_rejected` — a config with `feedback.cues.bogus_cue_name = "..."` still raises `ConfigError` matching `r"feedback.cues.bogus_cue_name"` (regression guard: the derivation doesn't loosen validation).
- `test_cue_names_matches_cue_name_literal_args` — a direct assertion that `set(CUE_NAMES) == set(typing.get_args(CueName))` (import both), guarding against future drift between the two.

Implementation order: write all five tests, run against the unchanged code and confirm they FAIL for the expected reason (the two overlap tests fail because no `ConfigError` is raised; the cue-override test fails with `ConfigError('unknown cue name...')`; the unknown-cue test currently already passes today — note this and confirm it still passes post-change, it's a regression guard not a new-behavior pin; the matches-literal test fails because `CUE_NAMES` is currently a separate hand-written tuple lacking the four prompt names), then implement both fixes until all pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after (except the pre-existing-passing unknown-cue-name regression guard, which is confirmed still passing).
- [x] AC-2: `Config.load` raises `ConfigError` when `hotkey.prompt_binding`'s keys overlap `hotkey.cancel_binding`'s keys, in both the default-cancel-binding and explicit-cancel-binding cases (satisfies PLM-004 FC-1).
- [x] AC-3: `CUE_NAMES` is derived from `feedback.CueName` via `typing.get_args`, and `set(CUE_NAMES) == set(typing.get_args(CueName))` holds (satisfies PLM-004 FC-2).
- [x] AC-4: All four prompt-mode cue names are accepted as valid `feedback.cues.*` overrides, and an unrecognized cue name is still rejected (satisfies PLM-004 FC-3 and FC-4).
- [x] AC-5: `.venv/bin/pytest -m "not integration"` passes with no regressions.
