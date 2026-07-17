---
id: FTHR-016
title: Implement validated paste injection mechanism and has_paste_trigger capability
plumage: PLM-009
status: egg
priority: P0
depends_on: [FTHR-015]
authored: 2026-07-17T02:33:52Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.8
---

# FTHR-016: Implement validated paste injection mechanism and has_paste_trigger capability

## Description
Implements PLM-009's injection mechanism per FTHR-015's recorded `RESULT:` line — the brooder reads `.fledge/molt/FTHR-015.md` first and implements exactly one of the two branches below, not both speculatively:

- **Branch 1 (3/3 pass — universal chord):** `ClipboardManager.copy()` populates both the regular clipboard and the primary selection; `Injector.paste()` fires Shift+Insert instead of Ctrl+V. Satisfies PLM-009 FC-1/FC-2.
- **Branch 2 (any failure — static fallback):** add `output.paste_chord` config (default `"ctrl+v"`); `Injector.paste()` fires that configured chord instead of a hardcoded one; `ClipboardManager.copy()` stays single-clipboard (no primary-selection population — that was only needed for the Shift+Insert design). Satisfies PLM-009 FC-5.

Either branch also: renames the `Session`-level capability gate from `has_wtype` to `has_paste_trigger` (FC-6) and keeps `Capabilities.probe()` presence-only (FC-7). `Injector.paste()`'s public signature/call contract (`paste() -> bool`, called with no arguments) is unchanged by either branch — this is the seam FTHR-017 (PLM-010) is written against, so `LiveStreamer` never needs to know which branch shipped.

## Affected Modules
- `output/inject.py::Injector.paste()` — chord change (Branch 1: hardcoded Shift+Insert; Branch 2: reads `cfg.output.paste_chord`).
- `output/clipboard.py::ClipboardManager.copy()` — Branch 1 only: add `wl-copy --primary` alongside the existing `wl-copy` call.
- `config.py::OutputConfig` — Branch 2 only: new `paste_chord: str` field, TOML parsing/validation, default `"ctrl+v"`.
- `capabilities.py::Capabilities` — rename `has_wtype` → `has_paste_trigger` (dataclass field + `probe()`).
- `session.py:831` — update the `self._caps.has_wtype` gate on `injector.paste()` to read `has_paste_trigger`.
- See `.fledge/nest/modules.md` → `output/`, `.fledge/nest/architecture.md` (capability-degradation pattern) for existing conventions to match.

## Approach
Keep the branch chosen by FTHR-015's `RESULT:` line as the only code path built — do not build both branches "to be safe." `Injector.paste()` stays a stateless thin wrapper around `subprocess.run`, matching its existing style (see `type_text()` for the established error-handling/logging pattern: `CalledProcessError`/`TimeoutExpired`/`FileNotFoundError` caught, logged, return `False`). For the Shift+Insert branch, the `wtype` invocation is `["wtype", "-M", "shift", "-k", "Insert", "-m", "shift"]` (verified against the `wtype` man page during FTHR-015's review — named keys need `-k`, not the bare-text form used for `ctrl`+`v` today). For the fallback branch, parse `cfg.output.paste_chord` (a simple string like `"ctrl+v"` or `"ctrl+shift+v"`) into the equivalent `-M`/`-k`/`-m` sequence — a small, explicit parser (split on `+`, last token is the key via `-k`, preceding tokens are modifiers via `-M`/`-m`) is sufficient; no need for a general hotkey-binding parser (that's `hotkey/binding.py`'s job for a different config surface, not reusable here since it targets `evdev` key names, not `wtype` modifier/key names).

`has_paste_trigger` should be computed the same way `has_wtype` is today (`shutil.which("wtype") is not None`) — the underlying binary doesn't change, only the capability's name and what it's understood to mean (presence-only, per PLM-009 FC-7 — no delivery-verification).

## Tests
- `test_clipboard.py::test_copy_populates_primary_selection` (Branch 1 only) — asserts `ClipboardManager.copy()` invokes `wl-copy` and `wl-copy --primary` (via a mocked/captured `subprocess.run`), both with the same input text.
- `test_inject.py::test_paste_fires_shift_insert` (Branch 1) — asserts `Injector.paste()` invokes `wtype` with `-M shift -k Insert -m shift`, not `ctrl`/`v`.
- `test_inject.py::test_paste_uses_configured_chord` (Branch 2) — asserts `Injector.paste()` invokes `wtype` with the modifier/key sequence derived from `cfg.output.paste_chord`, for at least two distinct chord values (e.g. `"ctrl+v"` and `"ctrl+shift+v"`).
- `test_config.py::test_paste_chord_default_and_override` (Branch 2) — asserts `Config.defaults().output.paste_chord == "ctrl+v"` and that a TOML override is honored.
- `test_capabilities.py::test_has_paste_trigger` — asserts `Capabilities` exposes `has_paste_trigger` (not `has_wtype`) and it reflects `wtype`'s presence via `shutil.which`.
- `test_session.py::test_paste_gated_on_has_paste_trigger` — asserts `session.py`'s paste call-site checks `caps.has_paste_trigger`.
- Implementation order is fixed: (1) write the tests above (only for the branch FTHR-015 selected); (2) run them against the unchanged code and confirm they FAIL for the expected reason (e.g. old tests referencing `has_wtype` or the hardcoded Ctrl+V chord); (3) implement until they pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: If FTHR-015's `RESULT:` was 3/3 pass: `ClipboardManager.copy()` populates both clipboard and primary selection, and `Injector.paste()` fires Shift+Insert — satisfies PLM-009 FC-1/FC-2/AC-4.
- [x] AC-3: If FTHR-015's `RESULT:` was a fallback: `output.paste_chord` exists (default `"ctrl+v"`, configurable), `Injector.paste()` uses it, and no primary-selection population is added — satisfies PLM-009 FC-5/AC-5.
- [x] AC-4: `Capabilities.has_paste_trigger` exists (replacing `has_wtype`), and `session.py`'s paste-gate reads it — satisfies PLM-009 FC-6/AC-6.
- [x] AC-5: `Capabilities.probe()` remains presence-only for the paste-trigger capability (no delivery-verification) — satisfies PLM-009 FC-7/AC-7.
- [x] AC-6: Existing `output/` and `session.py` unit tests unrelated to this change pass with no regressions.
- [x] AC-7: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions.
