---
generated: 2026-07-15T17:38:33Z
commit: d621b46261d9509fccbdffc4686be0b876c7951e
agent: fledge-forager
fledge_version: 0.5.4
---

# Testing

How the test suite is organized, run, and gated — frameworks, commands, marker conventions, and what's covered where.

## Framework & layout

- `pytest` (+ `pytest-asyncio` for async support), ~7,400 lines across 24 files in `tests/`, mirroring `src/stenographer/` 1:1 (`tests.md`, `root.md`).
- `tests/__init__.py` is empty (src-layout marker); `tests/fixtures/.gitkeep` is an empty placeholder — no fixture files currently in use; test data is inline or built with helper functions (`_cfg()`, `_mock_cfg()`, `_make_components()`, `_make_session()`) rather than pytest fixtures (`tests.md`).
- `pyproject.toml`: `testpaths = ["tests"]`, `addopts = "-ra"` (short summary of pass/fail/skip reasons).

## Running tests

- Unit only: `.venv/bin/pytest -m "not integration"`.
- All, including environment-touching: `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest`.
- Single test: `.venv/bin/pytest tests/test_session.py::test_name`.
- CI (`ci.yml`, `release.yml`) always runs `pytest -m "not integration"` — integration tests are never run in GitHub Actions; they require a manual/special environment (real display, audio, evdev) (`.github.md`).

## Marker & skip conventions

- `@pytest.mark.integration` gates tests that touch real clipboard, audio, display, or PortAudio; combined with manual checks like `if not os.environ.get("STENOGRAPHER_INTEGRATION"): pytest.skip(...)` (`tests.md`).
- ASR/model tests additionally skip if the model isn't locally cached (checked via `huggingface_hub.try_to_load_from_cache`); `test_transcription.py` requires `Systran/faster-whisper-large-v3` downloaded via `scripts/download_model.py` (session-scoped fixture, loads once per run) (`tests.md`).

## Mocking patterns

- `unittest.mock.MagicMock`/`patch`/`patch.dict`/`patch.object` for CLI, subprocess, HTTP, `sounddevice`, `evdev`.
- `monkeypatch` for simple swaps: env vars, `sys.exit`, filesystem paths.
- Hand-rolled fakes for scripted behavior: `_FakeEvent`/`_FakeDevice`/`_ListenerCallbacks` (hotkey tests), `_FakeRecorder`/`_FakeWorker` (live-streaming tests) — used in place of real hardware/model calls (`src-hotkey.md`, `tests.md`).
- Pure-function tests use no mocking at all: `test_bench.py`, `test_streaming.py`, `test_gen_cues.py` exercise algorithms directly (WER calculation, LocalAgreement commit logic, cue-tone generation).
- State-transition assertions: hotkey/session tests pin the exact transition sequence (e.g. `on_keydown` → `start_recording` → `RECORDING_PTT`), not just the final outcome.
- Error tests assert both exception type and message content via `pytest.raises(..., match=...)`.

## Coverage by area (file → what it covers)

- `test_session.py` (1,460 lines) — the core orchestrator: recording lifecycle, utterance queue, partial segment injection, paste mode, silence filtering, live-streaming wiring, prompt-mode LLM rewrite, dual-hotkey ownership tracking.
- `test_config.py` (885 lines, 65+ tests) — TOML parsing, schema validation (binding overlap, sample-rate/beam-size ranges, silence thresholds), defaults merging, write/load round-trip.
- `test_update.py` (593 lines) — update-check/download flow, SHA-256 verification, atomic install swap.
- `test_hotkey.py` (581 lines, 35+ tests) — binding parser, state machine (PTT/toggle/double-tap/cancel), listener event loop, stuck-key recovery.
- `test_capture.py` (558 lines) — device opening/fallback, sample accumulation, overflow handling, silence-flush, resampling (48→16 kHz), partial snapshots.
- `test_live.py` (524 lines, 35+ tests) — coalescing, tail-silence guard, window trimming, paragraph-break timing across trims, prefix-invariant typing deltas (property test tagged "M6").
- `test_cli_update.py` (292 lines), `test_lazy_model.py` (279 lines), `test_notification.py` (275 lines), `test_inject.py` (264 lines) — CLI update flow; lazy load/unload timer behavior; notification command building; text injection (truncation, unicode, leading-dash handling, paste mode).
- `test_cli.py` (221 lines), `test_clipboard.py` (178 lines), `test_feedback.py` (180 lines), `test_formatter.py` (175 lines), `test_notification.py` — subcommand dispatch; wl-copy/wl-paste round-trip; cue playback; formatting (spacing/capitalization/paragraph breaks, batch vs. incremental).
- `test_worker_cancel.py` (147 lines), `test_llm.py` (152 lines), `test_errors.py` (130 lines) — per-job ASR cancellation; LLM rewrite fallback on error; `notify_failure`/`fatal`/`degrade_capability` policy.
- `test_streaming.py` (127 lines), `test_cli_systemd.py` (99 lines), `test_transcription.py` (75 lines) — LocalAgreement-N committer (`longest_common_prefix`, agreement_n); systemd unit enable/start/stop; end-to-end batch transcription against a real model.
- `test_cli_completion.py` (59 lines), `test_bench.py` (53 lines), `test_gen_cues.py` (53 lines), `test_capabilities.py` (43 lines), `test_packaging.py` (12 lines) — argcomplete; WER/number normalization; cue-tone generation; capability probing; packaging smoke test.

## Integration tests (all gated by `STENOGRAPHER_INTEGRATION=1`)

Real PortAudio (`test_capture.py`, `test_transcription.py`), real `wtype` injection (`test_inject.py`), real `wl-copy`/`wl-paste` (`test_clipboard.py`), real `pw-play` (`test_feedback.py`), real `notify-send` (`test_notification.py`).

## Open Questions

- No project-root `conftest.py` was found in the assigned scout files — unclear if one exists and is auto-discovered by pytest (`tests.md`).
- `test_session.py` patches `sys.modules["stenographer.llm"]` as a workaround for the optional LLM feature — unclear if this indicates the real module is sometimes absent in certain build/feather states (`tests.md`).
- Which capabilities are actually exercised under `STENOGRAPHER_INTEGRATION=1` in practice (local dev only, since CI never sets it), and which remain effectively untested end-to-end? (`root.md`, `.github.md`)
