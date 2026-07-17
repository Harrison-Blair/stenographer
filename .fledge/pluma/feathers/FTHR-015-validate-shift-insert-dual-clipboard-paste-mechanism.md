---
id: FTHR-015
title: "Validate Shift+Insert dual-clipboard paste mechanism"
plumage: PLM-009
status: fledged
priority: P0
depends_on: []
oversight: during
authored: 2026-07-17T02:31:41Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.8
---

# FTHR-015: Validate Shift+Insert dual-clipboard paste mechanism

## Description
**This feather is the exception to test-first.** It makes ZERO changes to `src/stenographer/`. Its entire deliverable is a human-executed experiment, run live by the user against their real desktop, that empirically settles the single highest-risk unknown in the whole request: whether a Shift+Insert keystroke (fired via `wtype`), combined with populating both the Wayland clipboard and the primary selection with the same text, correctly pastes in the three real apps/contexts the user actually dictates into. No brooder may automate, mock, simulate, or otherwise substitute for the human running these steps and observing the real result — doing so defeats the entire purpose of the feather. There is no code to write and no automated test to run; the "test" is the recorded human observation below, and AC-1's usual "tests observed failing then passing" shape does not apply here.

The result of this feather is a **binary, pre-committed decision** that PLM-009's FTHR-016 and PLM-010's FTHR-017 both branch on: **all three targets pass → build the universal Shift+Insert + dual-population design (PLM-009 FC-1/FC-2); any target fails → build the static/manual `output.paste_chord` fallback instead (PLM-009 FC-5)** — never a partial/hybrid scheme (see PLM-009 Context: a hybrid can't distinguish VSCodium's editor pane from its integrated terminal, since both report the same Hyprland window class).

## Affected Modules
None in `src/stenographer/` — this feather touches only `.fledge/molt/FTHR-015.md` (the evidence file recording the result). Relevant background: `.fledge/nest/architecture.md` (paste-mode pipeline), `output/inject.py::Injector.paste()` (today's Ctrl+V-via-wtype implementation, being tested as a hypothesis here, not modified), `output/clipboard.py::ClipboardManager` (today's single-clipboard `copy()`, not modified here). See PLM-009's Context for the full `codium`-window-class finding that ruled out per-app auto-detection.

## Approach
The user runs the following manual steps live (not in an automated harness) and records a pass/fail per target. Use the repo's real `wtype`/`wl-copy` binaries directly from a terminal — no code changes needed to run this experiment, since `Injector.paste()`/`ClipboardManager.copy()` don't need to exist in their target form yet to test the underlying primitives they'd call.

**Setup (once):**
1. Put a short, distinctive test sentence on both the clipboard and the primary selection:
   ```sh
   printf 'the quick brown fox 42' | wl-copy
   printf 'the quick brown fox 42' | wl-copy --primary
   ```

**Per target** (repeat setup before each, since some apps may consume/alter the selection):

- **(a) kitty running Claude Code** — focus a kitty window at Claude Code's prompt. Fire: `wtype -M shift -k Insert -m shift`. Record: did "the quick brown fox 42" appear at the prompt, unmangled, with no unintended side effect (no `quoted-insert`-style literal character, no visual-block-mode entry, no kitty `confirm` dialog)?
- **(b) VSCodium's integrated terminal running Claude Code** — focus VSCodium, open/focus its integrated terminal pane at Claude Code's prompt. Same `wtype` command. Record: same pass/fail bar as (a).
- **(c) VSCodium's editor pane** — focus VSCodium's editor pane (a normal text buffer, cursor in it). Same `wtype` command. Record: did the text land correctly in the editor, no unintended side effect (no unrelated command/keybind fired)?

**Recording the result:** write `.fledge/molt/FTHR-015.md` (created by `fledge molt` tooling per this repo's existing molt-evidence convention) with one line per target — `PASS`/`FAIL` plus a one-sentence observation — and a final explicit verdict line: `RESULT: 3/3 PASS — build universal chord (PLM-009 FC-1/FC-2)` or `RESULT: <N>/3 PASS — fall back to static chord (PLM-009 FC-5)`. This RESULT line is what FTHR-016 and FTHR-017 read; it must be unambiguous.

## Tests
None — see Description. This feather's evidence is the human-recorded observation in `.fledge/molt/FTHR-015.md`, not an automated pytest run. Do not write pytest tests for this feather; do not attempt to script or mock the paste behavior being validated.

## Acceptance Criteria
- [x] AC-1: `.fledge/molt/FTHR-015.md` records a pass/fail observation, with a one-sentence note, for each of the three named targets: kitty/Claude Code, VSCodium integrated terminal/Claude Code, VSCodium editor pane.
- [x] AC-2: `.fledge/molt/FTHR-015.md` ends with an unambiguous `RESULT:` line stating either 3/3 pass (build universal chord) or the fallback (build static/manual chord), per the binary rule in Description — no partial/hybrid outcome is recorded.
- [x] AC-3: No files under `src/stenographer/` or `tests/` are modified by this feather.
