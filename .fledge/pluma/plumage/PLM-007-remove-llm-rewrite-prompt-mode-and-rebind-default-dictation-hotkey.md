---
id: PLM-007
title: Remove LLM rewrite (prompt) mode and rebind default dictation hotkey
status: fledged
priority: P1
authored: 2026-07-15T17:51:05Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.4
---

# PLM-007: Remove LLM rewrite (prompt) mode and rebind default dictation hotkey

## Context
The LLM rewrite ("prompt") mode is an unused/unhelpful feature: it depends on an external local LLM endpoint (`llm.base_url`, default `http://localhost:8080`) that most users don't run, and it carries its own hotkey listener, config section, notifications, and audio cues for a capability nobody exercises in practice. Removing it entirely (not just disabling it) simplifies the codebase and frees up a hotkey slot. That freed slot is used to change the default dictation binding from `KEY_RIGHTCTRL` to `KEY_RIGHTALT`, mirroring the de-facto standard push-to-talk/dictation key used by comparable tools (e.g. Typeless) so stenographer's default feels familiar to users coming from those tools.

## User Stories
- As a stenographer user, I want the LLM rewrite ("prompt") mode removed entirely, so that I don't carry unused config, a second hotkey listener, and an external-LLM dependency I never use.
- As a new user, I want the default dictation hotkey to be right-alt (`KEY_RIGHTALT`) instead of right-ctrl, so that stenographer's default matches the de-facto standard key used by comparable dictation tools, making it feel familiar out of the box.

## Functional Criteria
1. FC-1: The `stenographer.llm` module, `rewrite_prompt`, and `LlmConfig` no longer exist anywhere in the codebase.
2. FC-2: There is no second ("prompt") hotkey listener, config field, or session routing path (`source="prompt"`) — `Session` only ever handles one recording source.
3. FC-3: `hotkey.prompt_binding` is removed from the config schema entirely (not just defaulted to empty/disabled).
4. FC-4: The default `hotkey.binding` is `KEY_RIGHTALT` (was `KEY_RIGHTCTRL`); `hotkey.cancel_binding` default stays `KEY_ESC`, unchanged.
5. FC-5: The four prompt-mode audio cues (`ptt_on_prompt`, `ptt_off_prompt`, `toggle_on_prompt`, `toggle_off_prompt`) and their notification strings ("Listening (prompt)…", "Transcribing (prompt)…", prompt-ready/prompt-failed) no longer exist in code, config, or generated assets.
6. FC-6: `LlmError` is removed from `errors.py`.
7. FC-7: A freshly generated default config (`config.py:write_default` / `_format_default_toml`) contains no `[stenographer.llm]` section and no `hotkey.prompt_binding` line, and shows `hotkey.binding = "KEY_RIGHTALT"`.
8. FC-8: An old config file with a leftover `[stenographer.llm]` table and/or `hotkey.prompt_binding` key loads successfully and those keys are silently ignored, consistent with the existing (unchanged) behavior that unrecognized config keys are never rejected.
9. FC-9: The full test suite (`pytest -m "not integration"`) and `ruff check .` pass with zero references to `llm`/prompt-mode remaining in test names/fixtures for the removed behavior.

## Acceptance Criteria
- [x] AC-1: `grep -riE "llm|prompt" src/ tests/` (excluding legitimate non-feature hits: interactive-prompt usages in `live.py`/`update.py`/`_parser.py`/`packaging/install.sh`, and generic English words) returns no LLM-rewrite-feature references.
- [x] AC-2: `.venv/bin/pytest -m "not integration"` passes with zero prompt-mode/LLM tests remaining (they're deleted, not skipped).
- [x] AC-3: `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` pass.
- [x] AC-4: A fresh `stenographer` run with a fresh default config binds only one hotkey listener, on `KEY_RIGHTALT`, and pressing the old default (`KEY_RIGHTCTRL`) does nothing.
- [x] AC-5: Loading a config file containing a leftover `[stenographer.llm]` table and `hotkey.prompt_binding` key succeeds without error (keys silently ignored).

## Out of Scope
- The user's live `~/.config/stenographer/config.toml` (editing/migrating it) — outside the repo, handled by the orchestrator, not a feather.
- Version bump / commit / merge to main — the orchestrator's concern, not part of planning.
- Any new validation, warning, or migration tooling for legacy `llm`/`prompt_binding` config keys — silent-ignore is existing behavior, not new work introduced here.
- Rebinding or repurposing the freed `KEY_RIGHTCTRL` key for anything else — it simply becomes unbound.
- Any change to `cancel_binding` (`KEY_ESC`), PTT/toggle timing thresholds, or any other hotkey behavior not tied to prompt-mode removal.
- README/docs changes — no existing documentation references the LLM rewrite feature.

## Open Questions
None.
