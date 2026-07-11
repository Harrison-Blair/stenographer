# FTHR-004 Evidence

## AC-1

Command: `.venv/bin/pytest -m "not integration" tests/test_session.py -k "prompt_mode or dictate_mode_unaffected" -v`

Captured **before** any implementation changes (against unchanged `session.py`/`cli.py`):

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.fledge/burrows/FTHR-004/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-004
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 59 items / 52 deselected / 7 selected

tests/test_session.py::test_prompt_mode_recording_calls_rewrite_prompt FAILED [ 14%]
tests/test_session.py::test_prompt_mode_types_rewritten_text_not_raw_transcript FAILED [ 28%]
tests/test_session.py::test_prompt_mode_falls_back_to_raw_transcript_on_llm_error FAILED [ 42%]
tests/test_session.py::test_dictate_mode_unaffected_by_prompt_mode_addition PASSED [ 57%]
tests/test_session.py::test_prompt_mode_hotkey_independent_trigger_rules FAILED [ 71%]
tests/test_session.py::test_prompt_mode_never_streams FAILED             [ 85%]
tests/test_session.py::test_prompt_mode_disables_silence_flush_segments FAILED [100%]

=================================== FAILURES ===================================
_______________ test_prompt_mode_recording_calls_rewrite_prompt ________________
...
        with patch.dict(sys.modules, {"stenographer.llm": llm_mod}):
>           session._process(samples, "ptt", threading.Event(), source="prompt")
E           TypeError: Session._process() got an unexpected keyword argument 'source'

tests/test_session.py:1021: TypeError
___________ test_prompt_mode_types_rewritten_text_not_raw_transcript ___________
...
E           TypeError: Session._process() got an unexpected keyword argument 'source'
__________ test_prompt_mode_falls_back_to_raw_transcript_on_llm_error __________
...
E           TypeError: Session._process() got an unexpected keyword argument 'source'
______________ test_prompt_mode_hotkey_independent_trigger_rules _______________
...
>       session.attach_prompt_listener(prompt_listener)
E       AttributeError: 'Session' object has no attribute 'attach_prompt_listener'
________________________ test_prompt_mode_never_streams ________________________
...
>       session.on_recording_start(source="prompt")
E       TypeError: Session.on_recording_start() got an unexpected keyword argument 'source'
_______________ test_prompt_mode_disables_silence_flush_segments _______________
...
>       session.on_recording_start(source="prompt")
E       TypeError: Session.on_recording_start() got an unexpected keyword argument 'source'

=========================== short test summary info ============================
FAILED tests/test_session.py::test_prompt_mode_recording_calls_rewrite_prompt
FAILED tests/test_session.py::test_prompt_mode_types_rewritten_text_not_raw_transcript
FAILED tests/test_session.py::test_prompt_mode_falls_back_to_raw_transcript_on_llm_error
FAILED tests/test_session.py::test_prompt_mode_hotkey_independent_trigger_rules
FAILED tests/test_session.py::test_prompt_mode_never_streams
FAILED tests/test_session.py::test_prompt_mode_disables_silence_flush_segments
================= 6 failed, 1 passed, 6 deselected in ... ==================
```

(`test_dictate_mode_unaffected_by_prompt_mode_addition` passes already since it exercises only the
existing default-`source` code path — it is a regression guard, not new-behavior evidence.)

Full pre-implementation baseline (`.venv/bin/pytest -m "not integration"`): **6 failed, 435 passed, 4
deselected** — the 6 failures are exactly the 6 new-behavior tests above; the existing 435 all still pass
unchanged.

Failures are for the expected reason: `source` parameter does not yet exist on `on_recording_start`/
`_process`, and `attach_prompt_listener` does not yet exist on `Session`.

Post-implementation run of the same command:

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.fledge/burrows/FTHR-004/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-004
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 59 items / 52 deselected / 7 selected

tests/test_session.py::test_prompt_mode_recording_calls_rewrite_prompt PASSED [ 14%]
tests/test_session.py::test_prompt_mode_types_rewritten_text_not_raw_transcript PASSED [ 28%]
tests/test_session.py::test_prompt_mode_falls_back_to_raw_transcript_on_llm_error PASSED [ 42%]
tests/test_session.py::test_dictate_mode_unaffected_by_prompt_mode_addition PASSED [ 57%]
tests/test_session.py::test_prompt_mode_hotkey_independent_trigger_rules PASSED [ 71%]
tests/test_session.py::test_prompt_mode_never_streams PASSED             [ 85%]
tests/test_session.py::test_prompt_mode_disables_silence_flush_segments PASSED [100%]

======================= 7 passed, 52 deselected in 0.15s =======================
```

Full post-implementation suite (`.venv/bin/pytest -m "not integration"`): **441 passed, 4 deselected** —
435 pre-existing + 6 new (the 7th new test, `test_dictate_mode_unaffected_by_prompt_mode_addition`, was
already counted in the 435 pre-implementation baseline since it needed no new behavior).

## AC-2

"A prompt-mode recording's typed/copied output is the (mocked) LLM's rewritten text, not the raw
transcript."

Covered by `test_prompt_mode_types_rewritten_text_not_raw_transcript` (see AC-1 run above — PASSED):
asserts `injector.type_text` and `clipboard.copy` are each called once with `"Hello, world!"` (the mocked
`rewrite_prompt`'s return value), never with the raw `"hello world"` transcript.

Implementation: `session.py:_process` calls `llm.rewrite_prompt(self._cfg.llm, text)` and reassigns
`text` to the result before the existing paste/text output logic runs (`session.py`, `_process`, the
`if source == "prompt":` block right after the empty-transcript guard). Also guarded the paste-mode
`HeuristicFormatter.format_batch` re-formatting step to skip when `source == "prompt"` (it would
otherwise silently discard the LLM's rewritten text and reconstruct from raw ASR segments instead —
this matters because `output.injection_method` defaults to `"paste"`).

## AC-3

"On an LLM-call failure, the raw transcript is typed/copied instead and the existing error cue plays."

Covered by `test_prompt_mode_falls_back_to_raw_transcript_on_llm_error` (see AC-1 run above — PASSED):
mocked `rewrite_prompt` raises the mocked `LlmError`; asserts `injector.type_text` and `clipboard.copy`
are each called with the original raw `"hello world"` transcript, and `feedback.play("error")` was
called.

Implementation: `session.py:_process`, `except llm_module.LlmError as exc:` branch — logs at ERROR,
plays the `"error"` feedback cue, and leaves `text` unmodified (the raw transcript), so the unchanged
output logic below types/copies it.

## AC-4

"The prompt-mode hotkey's PTT/toggle/double-tap-discard behavior matches the dictate hotkey's, and the
two hotkeys operate independently."

- PTT/toggle/double-tap-discard mechanics themselves are the pre-existing, already-tested
  `HotkeyStateMachine` (pure, `tests/test_hotkey.py`) — unchanged by this feather. `cli.py:_build_session`
  constructs a second `HotkeyStateMachine` for the prompt hotkey with the same
  `toggle_threshold_seconds`/`double_tap_window_seconds` as the primary one (per the spec's "shared
  timing" decision), so it exhibits identical PTT/toggle/double-tap semantics.
- Session-level independence is covered by `test_prompt_mode_hotkey_independent_trigger_rules` (see AC-1
  run above — PASSED): verifies `attach_prompt_listener`/`start_listener`/`stop` manage the second
  listener's lifecycle alongside the first, that a dictate-hotkey recording is queued tagged `"dictate"`
  (or untagged, defaulting to `"dictate"`), that a prompt-hotkey recording immediately afterward is
  queued tagged `"prompt"` with its own `mode` ("toggle" in the test) unaffected by the prior dictate
  recording, and that `session.stop()` stops both listeners.

Implementation: `session.py` adds `attach_prompt_listener()`, and `start_listener()`/`stop()` now
start/stop both listeners when present. `cli.py:_build_session` wires the second `HotkeyListener`'s
`on_start`/`on_stop`/`on_toggle_off` via `functools.partial(..., source="prompt")`, while the primary
listener's callbacks are unchanged (implicit `source="dictate"` default).

## AC-5

"Prompt-mode recordings never use the live/streaming path and never emit mid-recording silence-flush
segments, regardless of global streaming/silence-detection config."

Covered by `test_prompt_mode_never_streams` and `test_prompt_mode_disables_silence_flush_segments` (see
AC-1 run above — both PASSED):
- `test_prompt_mode_never_streams`: with `cfg.streaming.enabled=True` and
  `cfg.output.injection_method="text"` (conditions that would normally enable streaming for a
  `source="dictate"` recording — see the pre-existing `test_streaming_recording_start_wires_on_partial_and_enqueues_live_item`),
  a `source="prompt"` recording takes the non-streaming path: `session._live_streamer is None` and
  `recorder.start()` is called without `on_partial`/`min_partial_seconds` kwargs.
- `test_prompt_mode_disables_silence_flush_segments`: with `cfg.audio.silence_detection=True`, a
  `source="prompt"` recording's `recorder.start()` call receives `on_segment=None`.

Implementation: `session.py:on_recording_start` — the streaming branch condition became
`if self._streaming and source != "prompt":`; the non-streaming branch's `on_segment` kwarg became
`self._enqueue_flush_segment if (self._silence_detection and source != "prompt") else None`. Also, within
`_process`'s per-segment partial-injection loop, `if source == "prompt": continue` skips all partial
typing/segment-cue actions (still draining the queue to observe the completion sentinel).

## AC-6

"`.venv/bin/pytest -m "not integration"` passes with no regressions to any existing
`test_session.py`/`test_hotkey.py` behavior."

Full suite run above (post-implementation): **441 passed, 4 deselected**, zero failures — the
pre-existing 435 tests (including all of `test_session.py` and `test_hotkey.py`) pass unchanged. Also
confirmed clean lint/format:

```
$ .venv/bin/ruff check .
All checks passed!
$ .venv/bin/ruff format --check .
53 files already formatted
```
