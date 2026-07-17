---
generated: 2026-07-17T01:39:59Z
commit: 939420f205b102d61ab3d7ed257a1680a61483dc
agent: fledge-forager
fledge_version: 0.5.8
---

# Testing

Test framework, how to run tests, and coverage patterns for stenographer's `tests/` suite (26 files, mirrors `src/stenographer/` 1:1).

## Framework & execution

- **pytest** (`>=8`), with `pytest-mock`/`unittest.mock` for stubbing, `pytest-asyncio` available but largely unused (tests are synchronous).
- Run unit tests only: `.venv/bin/pytest -m "not integration"`.
- Run everything (incl. env-touching): `STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest`.
- Run a single test: `.venv/bin/pytest tests/test_session.py::test_name`.
- Integration-only: `pytest -m integration`.
- Total: **~360+ test functions** across 26 files (grep on `def test_`, including parametrize expansions; per-file counts in tests.md).

## Integration marker

Exactly **4** tests are marked `@pytest.mark.integration` (verified via grep in scout pass) and touch real system state; each additionally self-skips if its dependency is unavailable (no `WAYLAND_DISPLAY`, tool missing from `PATH`, etc.), independent of the env-var gate:

- `test_capture.py::test_real_audio_recording_returns_well_shaped_buffer` — real PortAudio stream.
- `test_feedback.py::test_real_pw_play_invocation` — spawns real `pw-play`.
- `test_clipboard.py::test_real_wl_copy_round_trip` — real Wayland clipboard round-trip (saves/restores actual clipboard state).
- `test_inject.py::test_real_wtype_injects_into_focused_window` — real `wtype` into focused window.

All four are skipped unless `STENOGRAPHER_INTEGRATION=1` is set (pyproject.toml marker config, CLAUDE.md).

## Coverage by module

| Test file | Covers | Notable patterns |
|---|---|---|
| `test_hotkey.py` (36 tests) | `HotkeyBinding` parser, `HotkeyStateMachine` (hybrid PTT/double-tap-toggle/cancel, toggle-only mode), `HotkeyListener` (evdev loop via fake events + threaded callbacks) | Generation-check test for stale double-tap timer race |
| `test_capture.py` (23 tests, 1 integration) | `Recorder` device fallback, polyphase resampling (48k→16k, energy preservation), silence detection/flush, `on_partial` streaming, `snapshot()` | `PortAudioError` code `-9997` fallback simulation |
| `test_config.py` (72 tests) | `Config.load()` validation for every sub-config, defaults, `load_or_default()`, XDG/env precedence | Largest test file; extensive `@pytest.mark.parametrize` for boundary/enum values |
| `test_session.py` (1256 lines, 70+ tests) | Lifecycle, batch/paste/streaming pipeline routing, cancellation+generation tracking, lazy-model callbacks | Mocked components throughout (`MagicMock`) |
| `test_live.py` (524 lines, 24+ tests) | `LiveStreamer` coalescing, tail-silence guard, trim/rebase, **prefix invariant** (`test_prefix_invariant_M6`: every intermediate typed state is a prefix of the final transcript), beam-size fallback | `_fake_future()`, `_FakeRecorder`/`_FakeWorker` for scripted decode sequences |
| `test_streaming.py` (9 tests) | `longest_common_prefix()`, `_agreement_key()`, `StreamingTranscriber` commit/flush/rebase/reset, punctuation-sensitive agreement | No model/audio needed — pure-function tests |
| `test_worker_cancel.py` (6 tests) | `Worker` per-job `cancel_event`, pre-pickup cancellation, `submit_words()` cancellation | Stub `Model`, no real ASR weights |
| `test_lazy_model.py` (27 tests) | `LazyModel` thread-safe load/unload, idle timer, load-generation token, worker-thread integration | |
| `test_formatter.py` (14 tests) | `HeuristicFormatter` spacing, paragraph breaks, capitalisation, finalize/batch equivalence | `test_incremental_feed_equals_format_batch` cross-checks streaming vs. batch paths |
| `test_inject.py` (14 tests, 1 integration) | `Injector.type_text()` truncation/raw-mode/unicode, `.paste()` | No dedicated unit test mocks the raw wtype subprocess interaction depth; relies on subprocess.run mocking |
| `test_clipboard.py` (9 tests, 1 integration) | `ClipboardManager.copy()`/`.read()`, exception handling (`CalledProcessError`/`TimeoutExpired`/`FileNotFoundError`) | |
| `test_feedback.py` (8 tests, 1 integration) | Asset override resolution, pw-play/paplay volume scaling, subprocess `Popen` args | |
| `test_cli*.py` (4 files, ~32 tests) | Subcommand dispatch, systemd unit lifecycle, update flow, argcomplete | |
| `test_bench.py` (9 tests) | WER calculation, number-word normalization | |
| `test_errors.py` (7 tests) | `StenographerError` hierarchy, `fatal`/`notify_failure`/`degrade_capability`, import isolation | |
| `test_capabilities.py` (2 tests) | `Capabilities` frozen-dataclass round-trip | |
| `test_notification.py` (20 tests) | `DesktopNotification` notify-send commands, replacement-by-ID, hide/expiry | |
| `test_transcription.py`, `test_streaming.py` real-model path | Require the cached ASR model; session-scoped fixture skips if uncached | Only test files that touch real faster-whisper weights |
| `test_packaging.py` (1 test) | Version string matches `pyproject.toml` | |
| `test_gen_cues.py` (1 test) | Prompt-variant cue exclusion from build | |

## Conventions

- Helper naming: `_make_*` (build components), `_cfg(**overrides)` (config with overrides), `_fake_*`/`_Fake*` (fakes, e.g. `_FakeRecorder`, `_FakeDevice`), `_completed()` (mock `subprocess.CompletedProcess`).
- `caplog` fixture with `at_level()` to assert on ERROR/WARNING log messages.
- `tmp_path` for isolated file I/O (config TOML, WAV files).
- `monkeypatch` for env vars, `sys.exit`, `shutil.which`.
- Flat file layout (no subdirectories); classes group related tests where useful (e.g. `TestEnsureLoaded`, `TestTranscribe`, `TestIdleUnload` in `test_lazy_model.py`).

## Open Questions

- `test_session.py` and `test_live.py` were only partially read by their scout (offset-limited); the full extent of their edge-case coverage is not exhaustively catalogued here — read the files directly before relying on "no test exists for X."
- Whether `test_transcription.py` (and other real-model tests) actually run in CI depends on a model-download step not observed in `.github/workflows/*.yml` (github.md doesn't show a model-cache step) — likely skipped in CI, unconfirmed.
- The exact values of `streaming.min_chunk_seconds` / `streaming.agreement_n` / `streaming.max_buffer_seconds` used on the live path (vs. their parametrized test ranges) were not traced end-to-end.
