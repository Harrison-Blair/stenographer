---
id: FTHR-001
title: Default paragraph-pause to 0
plumage: PLM-001
status: fledged
priority: P0
depends_on: []
authored: 2026-07-11T05:49:15Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# FTHR-001: Default paragraph-pause to 0

## Description
Change the built-in default of `FormattingConfig.paragraph_pause_seconds` from `2.0` to `0.0`, so a fresh install (and any existing user config that doesn't explicitly set this key) no longer inserts a pause-triggered paragraph break into typed/pasted dictation output. The break-insertion code path itself, and the ability to re-enable it via config, are unchanged. Satisfies PLM-001 FC-1 and FC-2.

## Affected Modules
Per `.fledge/nest/data-model.md` and `.fledge/nest/testing.md`:
- `src/stenographer/config.py` — `FormattingConfig` dataclass and `Config.defaults()` (the default-value call site), and `_build_formatting()` (validation range `0 <= x <= 10`, unaffected).
- `tests/test_config.py` — existing test hardcodes the old default value and must be updated to expect `0.0`.
- `src/stenographer/output/formatter.py` — `HeuristicFormatter._feed_token`'s paragraph-break condition (`pause > 0 and (start - self._prev_end) >= pause`) is the mechanism being exercised; no code change needed here, only its default-driven behavior changes.
- `tests/test_formatter.py` — existing paragraph-break tests already construct `FormattingConfig` with an explicit `paragraph_pause_seconds` value (not the default), so they are unaffected; new tests for this feather live here.

## Approach
Single-line change: in `Config.defaults()`, change `paragraph_pause_seconds=2.0` to `paragraph_pause_seconds=0.0`. No other production code changes. The existing `_build_formatting()` validation (`0 <= x <= 10`) already accepts `0.0`, and `HeuristicFormatter`'s `pause > 0` guard already treats `0.0` as "disabled" — both are pre-existing behaviors this feather relies on rather than modifies.

## Tests
- `test_default_paragraph_pause_seconds_is_zero` (`tests/test_config.py`, replaces the existing assertion currently checking `== 2.0`) — loading `Config.defaults()` yields `paragraph_pause_seconds == 0.0`.
- `test_no_paragraph_break_with_default_config` (`tests/test_formatter.py`) — using `Config.defaults().formatting` (not an explicit override), feed tokens separated by a long pause (e.g. 5s) through `HeuristicFormatter`; assert no `"\n\n"` appears in the output.
- `test_paragraph_break_still_available_via_explicit_config` (`tests/test_formatter.py`) — construct `FormattingConfig` with `paragraph_pause_seconds` explicitly set to the old value (2.0); assert the paragraph-break behavior still fires exactly as it did before this feather (this pins down FC-2 — the escape hatch keeps working).

Implementation order: write these three tests, run them against the unchanged code and confirm the first two FAIL for the expected reason (default is still 2.0; a 5s pause under the old default would insert a break), then change the one default value line until all three pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: `Config.defaults().formatting.paragraph_pause_seconds == 0.0` (satisfies PLM-001 FC-1).
- [x] AC-3: Explicitly configuring `paragraph_pause_seconds` to a positive value still reproduces the old paragraph-break behavior (satisfies PLM-001 FC-2).
- [x] AC-4: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions (satisfies PLM-001 FC-4/AC-7 at the plumage level).
