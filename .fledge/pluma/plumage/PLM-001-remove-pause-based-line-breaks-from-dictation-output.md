---
id: PLM-001
title: Remove pause-based line breaks from dictation output
status: hatched
priority: P0
authored: 2026-07-11T05:33:12Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# PLM-001: Remove pause-based line breaks from dictation output

## Context
Stenographer currently inserts a paragraph break (blank line) into typed dictation output whenever the user pauses speaking for longer than a configured threshold. In chat-style text inputs (e.g. messaging apps, chat-based AI clients), a newline submits the message, so this heuristic is causing dictated messages to be sent prematurely, mid-thought, whenever the user pauses to think. The fix must apply uniformly to every dictation mode (the existing default mode and the new prompt-crafting mode from PLM-002) since both rely on the same output formatting behavior.

## User Stories
- As a user dictating into a chat window, I want pauses in my speech to never insert a newline into the typed text, so that my message isn't submitted before I've finished dictating it.
- As a user who prefers the old paragraph-break behavior for non-chat contexts, I want the ability to re-enable it via configuration, so that I'm not forced to lose a behavior I found useful elsewhere.

## Functional Criteria
1. FC-1: By default, dictated output never contains a pause-inserted paragraph break, regardless of how long the user pauses mid-utterance.
2. FC-2: A user may still opt back into the previous pause-based paragraph-break behavior via existing configuration, without any new configuration surface being introduced.
3. FC-3: The behavior change applies identically to every dictation mode that produces typed/pasted output.
4. FC-4: All other output formatting (spacing normalization, sentence capitalization) is unaffected.

## Acceptance Criteria
- [ ] AC-1: A test demonstrates that, with default configuration, no paragraph break is inserted even when a long pause occurs between dictated tokens (test written first, observed failing against the unchanged default, then passing after the fix).
- [ ] AC-2: A test demonstrates that explicitly configuring the old pause threshold still reproduces the previous paragraph-break behavior.
- [ ] AC-3: The full unit test suite passes with no regressions to existing spacing/capitalization formatting tests.

## Out of Scope
- Removing or redesigning the paragraph-break mechanism itself (spacing/capitalization normalization logic is untouched).
- Any new configuration key or migration tooling for existing user config files.
- Documentation updates (no current README/BUILD.md content references the changed default).

## Open Questions
None — resolved during interrogation: default value changes rather than removing the feature (per user decision), applies globally across modes, priority P0.
