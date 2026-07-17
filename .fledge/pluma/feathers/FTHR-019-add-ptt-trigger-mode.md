---
id: FTHR-019
title: Add ptt trigger mode
plumage: PLM-008
status: fledged
priority: P1
depends_on: []
authored: 2026-07-17T02:37:02Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.8
---

# FTHR-019: Add ptt trigger mode

## Description
Adds `trigger_mode = "ptt"` as a third value in `hotkey/state_machine.py::HotkeyStateMachine` and `config.py::ALLOWED_TRIGGER_MODES`, and makes it `Config.defaults()`'s new default. Every keydown in `ptt` mode unconditionally starts recording; every matching keyup unconditionally stops it — no `toggle_threshold_seconds` duration check, no `double_tap_window_seconds` grace period, no toggle-latching, regardless of press length. `hybrid` and `toggle` modes are untouched, retained exactly as they work today. This feather is entirely disjoint from `output/`, `live.py`, and `session.py` — it never touches `session.py` (verified: `trigger_mode` only appears in `config.py` and as a generic pass-through at `cli.py:222`) — so it has no `depends_on` and can run in parallel with the PLM-009/PLM-010 chain from the start.

## Affected Modules
- `hotkey/state_machine.py::HotkeyStateMachine` — new `"ptt"` mode branch in `__init__`'s mode validation, `on_keydown`, and `on_keyup`.
- `config.py` — `ALLOWED_TRIGGER_MODES` gains `"ptt"`; `Config.defaults()`'s `HotkeyConfig.trigger_mode` changes from `"hybrid"` to `"ptt"`.
- `cli.py:222` — no code change expected (generic pass-through of `cfg.hotkey.trigger_mode` into `HotkeyStateMachine`'s constructor); confirm this during implementation rather than assume.
- See `.fledge/nest/modules.md` → `hotkey/` and `.fledge/nest/domain.md` (trigger-mode glossary) for existing conventions; `tests/test_hotkey.py` for the existing `hybrid`/`toggle` state-machine test patterns to follow.

## Approach
Follow `toggle` mode's existing precedent for ignoring duration/timing fields: `HotkeyStateMachine.__init__` already validates `mode in ("hybrid", "toggle")` — extend to include `"ptt"`. In `on_keydown`, `ptt` mode should behave like today's `IDLE` → `hybrid`'s `RECORDING_PTT` transition but unconditionally (no distinction based on later duration): keydown always starts recording and transitions to a recording state. In `on_keyup`, `ptt` mode should always stop recording and return to `IDLE` — never entering `PENDING_TAP`, `TOGGLE_LATCHED`, or `TOGGLE_STOPPING` (those states become unreachable when `mode == "ptt"`). `toggle_threshold_seconds`/`double_tap_window_seconds` stay in the `HotkeyConfig` dataclass (still needed for `hybrid`) but the `ptt` branch never reads them, matching how `toggle` mode already ignores `threshold_seconds` today (per the existing docstring: "press duration never matters" in `toggle` mode). The cancel binding's existing behavior (`on_cancel()`) needs no `ptt`-specific change — it already operates on `_chord_active`/`_state` generically, independent of `mode`.

## Tests
- `tests/test_hotkey.py::test_ptt_mode_keydown_always_starts_recording` — asserts `HotkeyStateMachine(mode="ptt").on_keydown(...)` always returns a `start_recording` transition, for both a would-be-short and would-be-long subsequent hold (duration is irrelevant at keydown time regardless of mode, but confirms `ptt` doesn't special-case it either).
- `tests/test_hotkey.py::test_ptt_mode_keyup_always_stops_unconditionally` — asserts `on_keyup` after both a very short (e.g. 10ms) and a long (e.g. 5s) simulated hold always returns a `stop_recording_ptt`-shaped transition back to `IDLE`, never `await_double_tap`/`PENDING_TAP`.
- `tests/test_hotkey.py::test_ptt_mode_short_tap_does_not_enter_pending_tap` — asserts a short tap in `ptt` mode never produces a `PENDING_TAP` state, and a rapid second tap does not latch toggle (i.e. `PENDING_TAP`/`TOGGLE_LATCHED` are unreachable from `ptt`).
- `tests/test_hotkey.py::test_ptt_mode_cancel_aborts_recording` — asserts `on_cancel()` still aborts an active `ptt` recording with no recording-stop/output side effect, matching `hybrid`/`toggle` behavior.
- `tests/test_config.py::test_trigger_mode_accepts_ptt` — asserts config parsing accepts `hotkey.trigger_mode = "ptt"` and rejects an unknown value with the existing `ConfigError` shape.
- `tests/test_config.py::test_defaults_trigger_mode_is_ptt` — asserts `Config.defaults().hotkey.trigger_mode == "ptt"`.
- Existing `tests/test_hotkey.py` tests for `hybrid` and `toggle` (e.g. `test_ptt_path_keydown_then_long_keyup`, `test_double_tap_toggle_full_cycle`) — run unmodified to confirm no regression.
- Implementation order is fixed: (1) write the new tests above; (2) run them against the unchanged code and confirm they FAIL for the expected reason (`"ptt"` not a valid mode yet); (3) implement until they pass, then re-run the full existing `hybrid`/`toggle` suite to confirm no regressions.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: `HotkeyStateMachine(mode="ptt")` always starts recording on keydown and always stops on keyup, for both very short and long press durations — satisfies PLM-008 FC-2/AC-1.
- [x] AC-3: `PENDING_TAP`/`TOGGLE_LATCHED` states are unreachable in `ptt` mode — a short tap never opens a toggle window — satisfies PLM-008 FC-2/AC-2.
- [x] AC-4: `config.py` accepts `hotkey.trigger_mode = "ptt"` and rejects unknown values with the existing error shape — satisfies PLM-008 FC-1/AC-3.
- [x] AC-5: `Config.defaults()` returns `trigger_mode == "ptt"` — satisfies PLM-008 FC-1/AC-4.
- [x] AC-6: The cancel binding still aborts an active `ptt` recording with no output side effect — satisfies PLM-008 FC-4/AC-5.
- [x] AC-7: Existing `hybrid` and `toggle` mode tests pass unmodified — satisfies PLM-008 FC-5/AC-6.
- [x] AC-8: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions — satisfies PLM-008 AC-7.
