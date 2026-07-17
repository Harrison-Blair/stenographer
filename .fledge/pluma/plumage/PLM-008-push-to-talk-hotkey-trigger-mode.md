---
id: PLM-008
title: Push-to-talk hotkey trigger mode
status: fledged
priority: P1
authored: 2026-07-17T02:03:34Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.8
---

# PLM-008: Push-to-talk hotkey trigger mode

## Context
`hotkey/state_machine.py::HotkeyStateMachine` today implements two trigger modes (`config.py::ALLOWED_TRIGGER_MODES = {"hybrid", "toggle"}`). In `hybrid` mode (the current default), a press held ≥ `toggle_threshold_seconds` (default 0.5s) is treated as push-to-talk (record while held, stop on release) — but a *short* tap instead opens a `double_tap_window_seconds` grace period during which a second tap latches the recording into hands-free toggle mode instead of stopping it. There is no mode where every press unconditionally means "record only while held" with no duration threshold and no toggle fallback.

The user wants an unambiguous push-to-talk mode: a short accidental tap must never open a toggle-latch window or start a hands-free background recording. This plumage adds a third trigger mode, `"ptt"`, and makes it the configured default — without touching the existing `hybrid`/`toggle` modes, which stay available unchanged for anyone relying on them.

## User Stories
- As a user, I want a dedicated push-to-talk hotkey mode where holding the key records and releasing it always stops, regardless of how briefly I pressed it, so that a short or accidental tap never opens a toggle window or starts a hands-free recording I have to notice and stop separately.
- As a user who wants to keep using hybrid or toggle mode, I want those modes to keep working exactly as they do today, so that adding push-to-talk doesn't change behavior I already rely on.

## Functional Criteria
1. FC-1: `config.py::ALLOWED_TRIGGER_MODES` gains a third value, `"ptt"`; `hotkey.trigger_mode = "ptt"` is a valid config value and becomes the value returned by `Config.defaults()` (replacing today's `"hybrid"` default). `"hybrid"` and `"toggle"` remain valid, unmodified values.
2. FC-2: In `"ptt"` mode, every keydown on the bound hotkey unconditionally starts recording, and the matching keyup unconditionally stops it — no `toggle_threshold_seconds` duration check, no `double_tap_window_seconds` grace period, no toggle-latching, regardless of how short the press was.
3. FC-3: `toggle_threshold_seconds` and `double_tap_window_seconds` remain present and validated in `HotkeyConfig` (still meaningful for `hybrid` mode) but are not read by the `"ptt"` branch of `HotkeyStateMachine` — the same precedent `"toggle"` mode already sets today.
4. FC-4: The cancel hotkey (`hotkey.cancel_binding`) continues to abort an in-progress `"ptt"` recording exactly as it does in `hybrid`/`toggle` mode today — already-typed/pasted text is never retroactively undone.
5. FC-5: `"hybrid"` and `"toggle"` mode behavior is unchanged by this plumage — same states, transitions, and timing as before.

## Acceptance Criteria
- [x] AC-1: A test demonstrates that in `"ptt"` mode, `HotkeyStateMachine.on_keydown` always transitions to a recording state and `on_keyup` always transitions back to idle and stops recording, for both a very short (e.g. 10ms) and a long (e.g. 5s) simulated press duration — no threshold branching.
- [x] AC-2: A test demonstrates that in `"ptt"` mode, a short tap does NOT open a pending-double-tap state and a second rapid tap does NOT latch a toggle recording — i.e. the `PENDING_TAP`/`TOGGLE_LATCHED` states are unreachable from `"ptt"` mode.
- [x] AC-3: A test demonstrates `config.py` accepts `hotkey.trigger_mode = "ptt"` and rejects an unknown value with the existing `ConfigError` shape/message pattern.
- [x] AC-4: A test demonstrates `Config.defaults()` now returns `trigger_mode == "ptt"`.
- [x] AC-5: A test demonstrates the cancel binding still aborts an active `"ptt"` recording without emitting any recording-stop/output side effect.
- [x] AC-6: The existing `"hybrid"` and `"toggle"` mode test suites still pass unmodified, confirming no regression to those modes.
- [x] AC-7: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions.

## Out of Scope
- Removing or deprecating `"hybrid"` or `"toggle"` trigger modes — both stay in the codebase, unchanged, as configurable alternatives.
- Any change to `hotkey.binding` / `hotkey.cancel_binding` parsing (`hotkey/binding.py`).
- Any change to `hybrid` mode's double-tap timing behavior.
- Behavior of `audio.silence_detection` / `silence_rms_threshold` in `"ptt"` mode — silence detection only governs mid-recording chunk-flush segmentation (used by paste-mode chunk aggregation and streaming), never recording start/stop in any trigger mode, so it is unaffected by and out of scope for this plumage. The related quiet-mic RMS-threshold concern is deferred to the live-streaming plumage (PLM for plumage 3), where chunk-flush quality actually affects live output.
- A minimum press-duration guard against stray/accidental keypresses — release always stops recording in `"ptt"` mode, unconditionally, per FC-2.

## Open Questions
None — interrogation fully resolved this plumage's scope.
