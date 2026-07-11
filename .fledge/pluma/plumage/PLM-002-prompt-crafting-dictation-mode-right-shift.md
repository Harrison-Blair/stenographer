---
id: PLM-002
title: Prompt-crafting dictation mode (Right Shift)
status: fledged
priority: P1
authored: 2026-07-11T05:44:03Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# PLM-002: Prompt-crafting dictation mode (Right Shift)

## Context
Stenographer's existing dictation mode types the user's speech verbatim at the cursor. This plumage adds a second, independent dictation mode bound to Right Shift: instead of typing the raw transcript, it sends the transcribed speech to a locally-running large language model (reachable over HTTP, OpenAI-compatible chat-completions API) with a reformatting instruction, and types/copies the model's rewritten result instead. The intended use is turning a rambling spoken thought into a clean, well-structured prompt ready to hand to an AI assistant. This mode has no live/streaming feedback (unlike the existing mode's optional streaming), so desktop notifications carry the entire "what is the daemon doing right now" signal for the user. Ships as part of version 0.8.0.

## User Stories
- As a user talking through an idea out loud, I want to hold/tap Right Shift to have my speech turned into a clean, well-formed prompt (instead of the literal transcript), so I can hand it straight to an AI assistant without editing it myself.
- As a user relying on notifications instead of live typing feedback, I want a distinct notification at each stage (listening, transcribing, rewriting with the local LLM, done, or failed), so I always know what the daemon is doing and whether it's this mode or the normal one that's active.
- As a user whose local LLM server is temporarily unreachable, I want my dictated speech to still end up typed/copied (as the raw transcript) rather than lost, so a backend outage never costs me the utterance.
- As a user with both dictation modes configured, I want the Right Shift trigger to behave exactly like Right Control (hold ≥ threshold = push-to-talk, double-tap = latched toggle), so the two modes feel consistent and I don't have to learn new timing.
- As a user who wants to recognize which mode just fired by sound alone, I want the Right Shift mode's start and stop cues pitched two octaves lower than Right Control's, so I can tell the modes apart without looking at a notification.

## Functional Criteria
1. FC-1: A configurable hotkey (default Right Shift) triggers a second, independent dictation mode with the same push-to-talk/toggle/double-tap trigger rules as the existing dictation hotkey, usable concurrently with (and independently of) the existing hotkey.
2. FC-2: On completing a recording in this mode, the transcribed speech is sent to a configured local LLM endpoint (an OpenAI-compatible chat-completions HTTP API) together with a configurable reformatting system prompt, and the model's response is what gets typed/copied — not the raw transcript.
3. FC-3: The system prompt, the LLM endpoint location, the model name, request timeout, and sampling parameters (temperature, max output tokens) are all user-configurable, each with a working built-in default.
4. FC-4: If the LLM call fails for any reason (unreachable, timeout, bad/empty response), the raw transcript is typed/copied instead (the utterance is never silently dropped), and an error notification is shown.
5. FC-5: A distinct desktop notification is shown for each stage of this mode's pipeline (listening, transcribing, rewriting via the local LLM, success, and failure), worded so the user can tell this mode apart from the existing dictation mode's notifications.
6. FC-6: This mode never uses the live/streaming typing path — output is only produced once, after the full pipeline (transcribe → LLM rewrite) completes for the utterance.
7. FC-7: The audio cues played on entering and leaving a recording in this mode are pitched two octaves lower than the equivalent cues in the existing dictation mode; all other cues (cancel, discard, error, etc.) are unchanged and shared between modes.
8. FC-8: The project version is bumped to 0.8.0 as part of shipping this plumage.

## Acceptance Criteria
- [x] AC-1: A test demonstrates that completing a recording on the new hotkey results in the (mocked) LLM's response being typed/copied, not the raw transcript.
- [x] AC-2: A test demonstrates that when the LLM call fails, the raw transcript is typed/copied instead and an error notification fires.
- [x] AC-3: A test demonstrates that the new hotkey's push-to-talk, toggle, and double-tap-discard behaviors match the existing hotkey's behavior (same trigger rules, independently triggerable).
- [x] AC-4: A test demonstrates that a distinct notification is shown at each pipeline stage for this mode, and that it is distinguishable from the existing mode's notifications.
- [x] AC-5: A test demonstrates that this mode's start/stop audio cues are the pitched-down (÷4 frequency) assets, while other cues remain the shared/unchanged ones.
- [x] AC-6: `pyproject.toml`'s `[project].version` reads `0.8.0`.
- [x] AC-7: The full unit test suite passes with no regressions to the existing dictation mode's behavior.

## Out of Scope
- Any live/streaming typing feedback for this mode (explicitly excluded per the original request).
- Support for remote/cloud-hosted LLM providers — only a locally-reachable, OpenAI-compatible HTTP endpoint is supported.
- Retry logic for failed LLM calls (a single attempt; failure falls back to the raw transcript per FC-4).
- Multi-turn conversation or any memory of prior utterances — each utterance is a single, independent LLM request.
- Any UI/mechanism for the user to review or edit the LLM's rewritten output before it is typed/copied.
- Changes to the existing dictation mode's own behavior beyond what's needed to share its trigger-rule implementation (i.e., no feature changes to the Right-Control mode itself).

## Open Questions
None — resolved during interrogation: HTTP/OpenAI-compatible transport, shared-Session dual-listener architecture, configurable system prompt (default text agreed), fallback-to-raw-transcript on failure, distinct per-stage notification wording, pitched-down start+stop cues via pre-generated ÷4-frequency assets, new `hotkey.prompt_binding` config key sharing existing timing fields, six-field LLM config block, priority P1.
