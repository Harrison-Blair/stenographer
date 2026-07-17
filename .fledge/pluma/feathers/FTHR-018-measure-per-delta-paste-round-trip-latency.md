---
id: FTHR-018
title: Measure per-delta paste round-trip latency
plumage: PLM-010
status: hatching
priority: P1
depends_on: [FTHR-017]
oversight: during
authored: 2026-07-17T02:36:27Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.8
---

# FTHR-018: Measure per-delta paste round-trip latency

## Description
Captures a real-hardware measurement of one delta's full paste round-trip cost (`wl-copy` + `wl-copy --primary` if the universal-chord branch shipped, or just `wl-copy` for the fallback branch + `wtype` paste trigger) — a narrow, one-time number, not a new benchmarking subsystem. This is purely observational: it records what the cost is; it asserts nothing about whether that cost is acceptable, since the user explicitly declined a latency budget/threshold when asked (PLM-010 FC-7/AC-7 — "measures and reports; does not gate pass/fail on a latency threshold"). Do not invent a pass/fail bound.

## Affected Modules
- New: an `integration`-marked test (matching this repo's existing convention for tests that touch real system tools — `wl-copy`/`wtype` — and are skipped unless `STENOGRAPHER_INTEGRATION=1`), living alongside `test_live.py` or `test_inject.py`.
- Reads (does not modify): `output/clipboard.py::ClipboardManager`, `output/inject.py::Injector` as shipped by FTHR-016/FTHR-017.
- See `.fledge/nest/entry-points.md` for the existing `integration`-marker convention and `bench.py` for this repo's existing (unrelated, ASR-focused) benchmark-harness precedent — this feather does not extend `bench.py`; it's deliberately smaller in scope than that harness.

## Approach
Add one `@pytest.mark.integration` test that: constructs a real `ClipboardManager` and `Injector` (not mocked — this measurement is meaningless against a mocked `subprocess.run`), runs the actual delta round-trip (`copy()` then `paste()`) some small fixed number of times (e.g. 10) against a short representative delta string, records each iteration's wall-clock duration (`time.monotonic()` before/after), and logs the resulting numbers (min/median/max, or the raw list) via the standard `logging` module at INFO level so `pytest -s` or CI log capture surfaces them for a human to read. No assertion compares the measured time against any constant — the only assertions are basic sanity (the calls complete without raising, return `True`) matching the pattern other integration tests in this repo already use for real-tool round-trips.

## Tests
- `test_inject.py::test_paste_round_trip_latency` (`@pytest.mark.integration`) — runs 10 real copy+paste round-trips, logs each duration and a summary (min/median/max), asserts each call returns `True` (or degrades gracefully if `wtype`/`wl-copy` are unavailable in the test environment, matching existing integration-test skip conventions) — no latency-threshold assertion.
- Implementation order is fixed: (1) write the test; (2) run it against the unchanged code and confirm it fails for the expected reason (the measurement helper/test doesn't exist yet); (3) implement until it passes and produces real logged numbers.

## Acceptance Criteria
- [x] AC-1: The test listed above was observed failing before implementation (test/helper did not exist) and passes after.
- [x] AC-2: Running `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest tests/test_inject.py::test_paste_round_trip_latency -s` on real hardware produces a logged real measurement (min/median/max or raw per-iteration durations) for the delta round-trip — satisfies PLM-010 FC-7/AC-7.
- [x] AC-3: No assertion in the test compares the measured latency against a threshold or budget — the test cannot fail due to slowness, only due to the calls themselves failing.
- [x] AC-4: The measured result is recorded in `.fledge/molt/FTHR-018.md` (the actual numbers observed on the user's hardware, not just "test passed") so it's available to a future reader without re-running the measurement.
- [x] AC-5: The full unit test suite (`.venv/bin/pytest -m "not integration"`) still passes with no regressions (the new test is integration-only and excluded from that run).
