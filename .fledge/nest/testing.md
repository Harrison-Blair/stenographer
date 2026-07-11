---
generated: 2026-07-11T05:16:32Z
commit: f5694b5bffd265badb03101b726304b5e6a0efb4
agent: fledge-forager
fledge_version: 0.4.0
---

# Testing

Frameworks, how to run, and coverage patterns.

## Framework
pytest (>=8) with `pytest-asyncio` (>=0.23) support (`pyproject.toml [tool.pytest.ini_options]`). No other test framework in use.

## Running
- Unit only (default for iteration): `.venv/bin/pytest -m "not integration"`
- Full suite, including env-touching tests: `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest`
- Single test: `.venv/bin/pytest tests/test_session.py::test_name`
- CI (`release.yml` `lint-test` job) runs the unit-only subset after ruff lint/format checks.
- Never invoke the system `pytest` — always `.venv/bin/pytest` (project-wide convention, `CLAUDE.md`/`AGENTS.md`).

## `integration` marker
Tests marked `@pytest.mark.integration` touch the real Wayland clipboard, real audio devices, or real display and are skipped unless `STENOGRAPHER_INTEGRATION=1` is set. Examples: `test_clipboard.py:test_real_wl_copy_round_trip`, `test_inject.py:test_real_wtype_injects_into_focused_window`.

## Layout
`tests/` mirrors `src/stenographer/` one-to-one: `test_<module>.py` per source file (e.g. `test_capture.py` ↔ `audio/capture.py`, `test_hotkey.py` ↔ `hotkey/*.py`, `test_session.py` ↔ `session.py`). Shared fixtures under `tests/fixtures/`.

Known test files (by area):
- Hotkey: `test_hotkey.py` (binding parser, pure state machine, listener integration with a fake evdev device).
- Audio: `test_capture.py` (Recorder), `test_feedback.py` (cue playback/asset resolution/muting).
- ASR: `test_lazy_model.py` (lazy load/idle-unload lifecycle), `test_worker_cancel.py` (job cancellation), `test_streaming.py` (`StreamingTranscriber` LocalAgreement-N), `test_transcription.py`.
- Session/orchestration: `test_session.py` (876 lines, 31 tests — recording lifecycle, `_process`, async queue/processor, lazy-model callbacks, cancel/discard, live-streaming wiring), `test_live.py` (LiveStreamer integration).
- Output: `test_inject.py` (Injector — wtype subprocess success/failure/timeout/truncation/raw mode), `test_clipboard.py` (ClipboardManager — wl-copy/wl-paste success/failure), `test_formatter.py` (HeuristicFormatter — spacing, capitalization, paragraph breaks, incremental-vs-batch equivalence).
- Cross-cutting: `test_config.py`, `test_capabilities.py`, `test_errors.py`, `test_notification.py`, `test_update.py`, `test_bench.py`, `test_cli_completion.py`, `test_cli_systemd.py`, `test_cli_update.py`.

## Patterns
- Heavy `unittest.mock.MagicMock` use to isolate a component under test: `test_session.py` mocks Recorder, Worker, Injector, Clipboard, Feedback, and Listener wholesale via `_make_components()`/`_make_session()` fixture helpers.
- Naming convention for test helpers: `_make_x()` (build a fixture), `_fake_x()` (stub with canned behavior, e.g. `_fake_future()` — a worker Future that fires its callback immediately).
- Assertions via `assert_called_once_with()`, `assert_not_called()`, etc., rather than manual call inspection.
- Audio sample fixtures: `np.ndarray` shape `(N, 1)`, dtype `float32`.
- ASR result fixtures: `SegmentInfo(start, end, text, no_speech_prob)`, `TranscriptionResult(text, duration_seconds, segments)`.
- Concurrency/race tests use deferred-future patterns (e.g. threading a submit deferral, `release_second_segment` events in `test_session.py`) to exercise cancellation ordering deterministically.
- `caplog` fixture used to assert on log messages for degraded-capability / failure paths (e.g. `test_inject.py`'s `caplog.LogCaptureFixture` parameter).
- Pure state machines (`HotkeyStateMachine`, `StreamingTranscriber`) are tested with no mocking at all — direct construction and method calls, since they have no I/O.
- `HotkeyListener` integration tests fake the evdev layer entirely: `_FakeDevice` with `read_loop()`/`close()` substituting for `evdev.InputDevice`, and short-circuited retry-timing constants.

## Pre-change verification workflow (per `CLAUDE.md`/`AGENTS.md`)
Before considering a change complete: `ruff check .`, `ruff format --check .`, and `.venv/bin/pytest -m "not integration"` must all pass.
