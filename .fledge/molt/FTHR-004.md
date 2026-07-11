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

**Update (skua review round 1):** added `test_prompt_mode_paste_mode_uses_rewritten_text_not_reformatted`
to pin the paste-mode guard specifically, since the original test set covered only `paste_mode=False`.
Sets `cfg.output.injection_method = "paste"` with non-empty `result.segments`, mocks `rewrite_prompt` to
return `"Hello, world!"`, and asserts `session._formatter.format_batch` is never called and
`clipboard.copy`/`injector.paste` use the rewritten text. Verified test-first per the brooder protocol:
temporarily reverted the `source != "prompt"` guard (`if result.segments:` instead of
`if result.segments and source != "prompt":`) and confirmed the test FAILS —
`AssertionError: Expected 'format_batch' to not have been called. Called 1 times.` — then restored the
guard and confirmed it PASSES:

```
$ .venv/bin/pytest -m "not integration" tests/test_session.py::test_prompt_mode_paste_mode_uses_rewritten_text_not_reformatted -v
tests/test_session.py::test_prompt_mode_paste_mode_uses_rewritten_text_not_reformatted PASSED [100%]
============================== 1 passed in 0.16s ===============================
```

Full suite after this addition: **442 passed, 4 deselected**; `ruff check .` and
`ruff format --check .` both clean.

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

## Post-merge fix: test-isolation bug (sys.modules patch bypassed)

**Reported by the orchestrator:** this branch passed in isolation but the merge into `dev` went red,
because `dev` now includes FTHR-003's real `src/stenographer/llm.py` and `tests/test_llm.py` (this
worktree was branched before FTHR-003 merged, so it never had them). Rebased onto `dev` (`git rebase dev`,
clean, no conflicts) to pull in the real module and reproduce.

**Root cause:** `session.py`'s prompt-mode LLM call used `from stenographer import llm as llm_module`
inside `_process`. That import-statement form does not always consult `sys.modules`: CPython's
`from X import Y` compiles to an `IMPORT_NAME` (imports `X`) followed by an `IMPORT_FROM 'Y'`, and the
fromlist-handling step (`_handle_fromlist`) skips re-importing `X.Y` if `X` already has a `Y` attribute
— it just does `getattr(X, 'Y')`. Once `tests/test_llm.py` imports the real `stenographer.llm` anywhere
in the same pytest session, Python sets `stenographer.llm` as an attribute of the `stenographer` package
object as a side effect. From that point on, `from stenographer import llm` returns the REAL cached
module via `getattr`, silently ignoring our tests' `patch.dict(sys.modules, {"stenographer.llm": fake})`
— so `_process` called the real `rewrite_prompt`, which tried to `json.dumps` a `MagicMock` (`cfg.llm`)
and blew up with `TypeError: Object of type MagicMock is not JSON serializable`.

Reproduced verbatim before the fix:

```
$ .venv/bin/pytest tests/test_llm.py tests/test_session.py -q
...
E       TypeError: Object of type MagicMock is not JSON serializable
=========================== short test summary info ============================
FAILED tests/test_session.py::test_prompt_mode_recording_calls_rewrite_prompt
FAILED tests/test_session.py::test_prompt_mode_types_rewritten_text_not_raw_transcript
FAILED tests/test_session.py::test_prompt_mode_falls_back_to_raw_transcript_on_llm_error
FAILED tests/test_session.py::test_prompt_mode_paste_mode_uses_rewritten_text_not_reformatted
4 failed, 64 passed in 0.64s
```

**Fix:** replaced the import with `importlib.import_module("stenographer.llm")` (added `import importlib`
at module top). `importlib.import_module` resolves through `sys.modules` unconditionally (checks
`sys.modules.get(name)` before ever touching parent-package attributes), so it always honors the tests'
`patch.dict(sys.modules, ...)` stub regardless of import order or whether the real module was already
cached elsewhere. No test assertions were weakened — same mocked module, same `LlmError` fallback
behavior, same call signature.

Verified fixed:

```
$ .venv/bin/pytest tests/test_llm.py tests/test_session.py -q
....................................................................     [100%]
68 passed in 0.52s
```

Full suite after rebase + fix (`.venv/bin/pytest -m "not integration"`): **453 passed, 4 deselected**
(435 pre-existing + 7 new FTHR-004 tests + 11 new FTHR-003 `test_llm.py` tests now included via the
rebase). `ruff check .` / `ruff format --check .` both clean.
