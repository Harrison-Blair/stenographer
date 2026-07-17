---
id: PLM-004
title: "Prompt-mode config validation & registration"
status: fledged
priority: P1
authored: 2026-07-15T04:58:14Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# PLM-004: Prompt-mode config validation & registration

## Context
PLM-002 added prompt mode's config surface: a `hotkey.prompt_binding` key and four new feedback cue names (`ptt_on_prompt`, `ptt_off_prompt`, `toggle_on_prompt`, `toggle_off_prompt`). A code review of the current `dev` branch found two config-loading validation bugs in that surface:

1. `_build_hotkey` (config.py) checks `hotkey.prompt_binding` for key overlap against `hotkey.binding`, but not against `hotkey.cancel_binding`. Setting `prompt_binding` to the same keys as `cancel_binding` (e.g. its default `KEY_ESC`) loads with no error; at runtime the prompt listener then arms the cancel chord on every prompt-mode press, so prompt mode silently self-cancels with no diagnostic pointing at the cause.
2. The four new prompt cue names exist in `feedback.py`'s `CueName` Literal (the type the feedback player actually accepts) but were never added to `config.py`'s separately hand-maintained `CUE_NAMES` tuple (the list `_build_cues` validates `feedback.cues.*` overrides against). A user who overrides `feedback.cues.ptt_on_prompt` (or any of the other three) gets `ConfigError('unknown cue name...')` and the daemon refuses to start, even though the code plays these exact cues from bundled default assets when left un-overridden.

This plumage closes the `prompt_binding`/`cancel_binding` overlap gap and fixes the cue-name registration by making `CUE_NAMES` derived from `CueName` (single source of truth), so this class of drift can't recur as new cues are added.

## User Stories
- As a user configuring `hotkey.prompt_binding`, I want config loading to reject a binding that collides with `hotkey.cancel_binding`, with a clear error naming the conflict, so prompt mode never silently self-cancels.
- As a user who wants to customize a prompt-mode audio cue (e.g. `feedback.cues.ptt_on_prompt`), I want that override to be accepted at config-load time, so I don't hit a startup failure for a cue name the daemon already plays by default.

## Functional Criteria
1. FC-1: `_build_hotkey` raises `ConfigError` when `hotkey.prompt_binding`'s keys overlap with `hotkey.cancel_binding`'s keys, unconditionally (no defaults-vs-explicit distinction — same hard-error shape as the existing `prompt_binding` vs `binding` check).
2. FC-2: `config.py`'s `CUE_NAMES` is derived from `feedback.py`'s `CueName` Literal (e.g. via `typing.get_args`) rather than hand-maintained separately, so the two can never drift apart again.
3. FC-3: All four prompt-mode cue names (`ptt_on_prompt`, `ptt_off_prompt`, `toggle_on_prompt`, `toggle_off_prompt`) are accepted as valid `feedback.cues.*` override keys.
4. FC-4: A genuinely unknown cue name in `feedback.cues.*` still raises `ConfigError` exactly as before — the derivation does not loosen validation.

## Acceptance Criteria
- [x] AC-1: A test demonstrates that a config with `hotkey.prompt_binding` set to the same key(s) as `hotkey.cancel_binding` raises `ConfigError` on load.
- [x] AC-2: A test demonstrates that a config overriding `feedback.cues.ptt_on_prompt` (and the other three prompt cue names) loads without error.
- [x] AC-3: A test demonstrates that a config with an unrecognized `feedback.cues.<bogus-name>` key still raises `ConfigError`.
- [x] AC-4: A test demonstrates that `CUE_NAMES` (config.py) is exactly the set of `CueName`'s Literal args (feedback.py) — guarding against future divergence between the two.
- [x] AC-5: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions to existing config-loading behavior.

## Out of Scope
- Any change to `hotkey.binding` vs `hotkey.cancel_binding`'s existing defaults-vs-explicit warn/disable behavior — untouched; only the new `prompt_binding` vs `cancel_binding` check is added, as a hard `ConfigError`.
- Any change to how cue files are resolved or played (`feedback.py`'s `_resolve_path`/`play`) — only the config-time name-validation source of truth changes.
- Renaming or restructuring `CueName` itself — it stays the source of truth; `CUE_NAMES` becomes derived from it, not the reverse.
- Any other config validation gaps not named in F5/F6.

## Open Questions
None — resolved during interrogation: `prompt_binding`/`cancel_binding` overlap is an unconditional `ConfigError`, matching the existing `prompt_binding`/`binding` check; `CUE_NAMES` is derived from `CueName` via `typing.get_args` rather than hand-synced; priority P1.
