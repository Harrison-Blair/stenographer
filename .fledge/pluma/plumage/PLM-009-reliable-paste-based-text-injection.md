---
id: PLM-009
title: Reliable paste-based text injection
status: hatched
priority: P0
authored: 2026-07-17T02:19:20Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.8
---

# PLM-009: Reliable paste-based text injection

## Context
The user's hard requirement is that `wtype`-based character typing (`Injector.type_text()`) must not be the injection mechanism: it garbles text in Electron apps, its Return keystroke submits prompt/dialog boxes in terminal apps (e.g. Claude Code running in a terminal), and it can trigger unrelated keybinds. `output.injection_method = "paste"` is already the shipped default and already exists as a code path (`Injector.paste()`, `ClipboardManager.copy()`), but it is not currently wtype-free: `paste()` still shells out to `wtype -M ctrl v -m ctrl` to simulate a single Ctrl+V keystroke, and that keystroke is hardcoded — it assumes Ctrl+V is the correct paste chord everywhere, which is false for the user's own setup.

The user runs Claude Code both in **kitty** (a standalone terminal, default paste chord Ctrl+Shift+V; kitty's `paste_actions` include a `confirm` prompt on control codes or >16KB pastes) and inside **VSCodium's integrated terminal** (Electron/xterm.js), and also dictates into VSCodium's **editor pane** directly (Electron, conventional paste chord Ctrl+V). Both the integrated terminal and the editor pane are the *same* Hyprland/Wayland toplevel window and report the identical window class (`codium`) via `hyprctl activewindow` — Hyprland's window-class introspection reports only the toplevel window, not which widget inside it has focus, so per-window-class chord auto-detection was investigated and found unfixable for this pairing: no automatic rule can pick Ctrl+V for the editor pane and Ctrl+Shift+V for the integrated terminal when both report as `codium`.

The design adopted instead: populate **both** the regular Wayland clipboard (`wl-copy`) and the **primary selection** (`wl-copy --primary`) with the same text, and fire a single, universal **Shift+Insert** chord — kitty's default binds Shift+Insert to paste-from-primary-selection, and GTK/Electron apps conventionally bind Shift+Insert to paste-from-clipboard, so one chord may correctly serve every target with no window introspection, no compositor tie, and no per-app config. This is unverified against the user's actual apps and is exactly what this plumage's first feather validates empirically before anything else is built on it. The user was told explicitly, and accepted, that populating the primary selection on every utterance overwrites their middle-click-paste buffer (kitty has middle-click paste enabled by default) — this is a deliberate, informed tradeoff, not an oversight, and must not be "fixed" by a future reader.

If validation fails on even one of the three targets, no automatic scheme can rescue a partial result (the `codium`-single-class finding above means a hybrid can't distinguish the failing case either), so the plumage falls back in full to a static, user-configured chord with manual override — never a hybrid.

Under the validated design, `wtype` is reduced to firing one fixed keystroke (Shift+Insert) instead of typing arbitrary characters — all three of the user's original complaints (garbled characters, Return submitting prompts, keybind collisions) attach specifically to `type_text()`'s character-by-character typing, which this path never calls again. Terminal "Return submits the prompt" additionally can't recur under paste for a structural reason: terminals implement bracketed paste, delivering pasted text to the application as a single paste event rather than as individual keystrokes, so an embedded newline in the dictated text does not act like a manually-typed Enter.

## User Stories
- As a user, I want dictated text pasted into my terminal (kitty, standalone or via Claude Code) and into VSCodium (both its editor and its integrated terminal) correctly and without side effects, so that I can rely on dictation working the same way regardless of which app I'm dictating into.
- As a user, I want the injection mechanism to never simulate arbitrary character keystrokes, so that the garbled-text, prompt-submission, and keybind-collision problems I hit with typed injection cannot recur.
- As a user, I want to know definitively, before any further streaming work is built on top of it, whether the paste mechanism actually works on my real apps — not an assumption.

## Functional Criteria
1. FC-1: `ClipboardManager.copy()` populates both the regular Wayland clipboard (`wl-copy`) and the primary selection (`wl-copy --primary`) with the same text on every call.
2. FC-2: `Injector.paste()` fires a single universal chord, Shift+Insert (via `wtype`), instead of today's hardcoded Ctrl+V.
3. FC-3: A validation feather (`oversight: during`) empirically tests the Shift+Insert + dual-population design against exactly three targets: (a) kitty running Claude Code, (b) VSCodium's integrated terminal running Claude Code, (c) VSCodium's editor pane. Pass bar per target: the pasted text lands correctly with no unintended side effect (no dialog submission, no unrelated keybind action, no mis-scoped selection semantics).
4. FC-4: The validation result is binary and pre-committed: all three targets passing means the Shift+Insert + dual-population design ships as the injection mechanism; any target failing means the plumage falls back in full to FC-5 instead — never a partial/hybrid scheme.
5. FC-5 (fallback path, built only if FC-3/FC-4 fails validation): a single configurable chord, `output.paste_chord` (default `"ctrl+v"`), fired by `Injector.paste()` instead of the hardcoded/Shift+Insert chord; the user manually edits this value and reloads config when their workflow needs a different chord. No window-class detection, no per-app table.
6. FC-6: The `Session`-level capability gate on `paste()` (currently `capabilities.has_wtype` at `session.py:831`) is generalized to `has_paste_trigger`, decoupling `Session` from knowledge of which underlying tool/mechanism performs the trigger.
7. FC-7: `capabilities.py::Capabilities.probe()` continues presence-only probing (`shutil.which(...)` on whichever binary backs the chosen mechanism) — it does not attempt to verify actual keystroke delivery, which is not reliably possible outside a real, focused window.
8. FC-8: `Injector.paste()`'s trigger mechanism stays behind its existing method-call seam (`Session`/callers only ever call `injector.paste()`) so that a future swap to an alternative delivery tool (e.g. `ydotool`, not installed today and requiring a new system dependency/daemon/uinput permissions) would be a implementation swap behind that seam, not a rewrite of calling code — built only if a future need actually arises, not built speculatively now.

## Acceptance Criteria
- [ ] AC-1: A test demonstrates `ClipboardManager.copy()` calls `wl-copy` for the regular clipboard AND `wl-copy --primary` for the primary selection, both with the same text, on a single `copy()` call.
- [ ] AC-2: A test demonstrates `Injector.paste()` invokes `wtype` with a Shift+Insert key sequence (not Ctrl+V).
- [ ] AC-3: The validation feather's human-executed steps and pass/fail bar are documented precisely enough that the user can run them against kitty/Claude Code, VSCodium's integrated terminal/Claude Code, and VSCodium's editor pane, and record a clear pass/fail per target.
- [ ] AC-4: If validation passes 3/3: `Injector.paste()` and `ClipboardManager.copy()` ship exactly as FC-1/FC-2 describe, with no fallback-path code added.
- [ ] AC-5: If validation fails on any target: `output.paste_chord` (FC-5) is implemented, defaulting to `"ctrl+v"`, configurable, and `Injector.paste()` uses it instead of a hardcoded chord; the dual clipboard/primary population from FC-1 is reverted or gated off (only needed for the Shift+Insert design).
- [ ] AC-6: A test demonstrates `capabilities.py::Capabilities` exposes `has_paste_trigger` (renamed/generalized from `has_wtype`) and `session.py`'s paste-gate at line ~831 reads that field, not a wtype-specific one.
- [ ] AC-7: A test demonstrates `Capabilities.probe()` performs presence-only checks (no runtime keystroke-delivery verification) for the paste-trigger capability.
- [ ] AC-8: The existing `output/` and `session.py` unit test suites pass with no regressions to the non-paste (`"text"`) injection method or to the always-independent clipboard fallback.
- [ ] AC-9: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions.

## Out of Scope
- Building `ydotool` (or any alternative delivery-mechanism) support unconditionally — only build it if a future need is identified; not part of this plumage regardless of validation outcome.
- Any change to `output/formatter.py`'s heuristic spacing/capitalisation/paragraph-break logic — explicitly kept as-is per the original request.
- Any change to `type_text()` or the `"text"` injection method itself — the user wants paste kept as the injection method, not typing improved.
- Per-window-class or per-widget chord auto-detection (e.g. via `hyprctl` or any compositor IPC) — investigated and found unfixable for the user's primary target (VSCodium's editor and integrated-terminal panes share one window class), so it is not pursued in any form, including as a partial/hybrid scheme.
- A configurable per-window-class chord-mapping table — superseded by the universal-chord design; only the single-value `output.paste_chord` fallback (FC-5) is in scope, and only if validation fails.
- Any change to protect the primary selection / middle-click-paste buffer from being overwritten — the user was informed of and explicitly accepted this tradeoff.
- Real-time or automated verification that a paste keystroke was actually delivered/received by the target app — `capabilities.py` stays presence-only; empirical delivery verification is the validation feather's one-time, human-executed job, not a runtime capability check.

## Open Questions
None — interrogation fully resolved this plumage's scope, including the partial-validation-failure rule (binary: any failure triggers full fallback to FC-5, no hybrid).
