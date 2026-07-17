# FTHR-009 Evidence

## AC-1

Both new tests, run against unchanged code (before implementing F7/F8), failing for the expected reason.

Command:
```
.venv/bin/pytest tests/test_session.py::test_prompt_mode_lazy_model_load_shows_prompt_listening_notification tests/test_session.py::test_prompt_mode_llm_failure_plays_only_error_cue_not_transcribe_done -v
```

Output (pre-implementation):
```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.fledge/burrows/FTHR-009/.venv/bin/python3
collecting ... collected 2 items

tests/test_session.py::test_prompt_mode_lazy_model_load_shows_prompt_listening_notification FAILED [ 50%]
tests/test_session.py::test_prompt_mode_llm_failure_plays_only_error_cue_not_transcribe_done FAILED [100%]

=================================== FAILURES ===================================
_____ test_prompt_mode_lazy_model_load_shows_prompt_listening_notification _____

    def test_prompt_mode_lazy_model_load_shows_prompt_listening_notification() -> None:
        notif = MagicMock()
        session, _m = _make_session(notification=notif)
        c = _components(session)
        c["cfg"].asr.mode = "lazy"
        c["worker"].is_model_loaded.return_value = False
        session.on_recording_start(source="prompt")
        session._on_model_loaded()
>       notif.show_listening_prompt.assert_called_once()

tests/test_session.py:743:
...
E           AssertionError: Expected 'show_listening_prompt' to have been called once. Called 0 times.

/usr/lib/python3.14/unittest/mock.py:965: AssertionError
____ test_prompt_mode_llm_failure_plays_only_error_cue_not_transcribe_done _____

    def test_prompt_mode_llm_failure_plays_only_error_cue_not_transcribe_done() -> None:
        session, _m = _make_session()
        c = _components(session)
        _process_prompt(session, c, text="hello world", raise_error=True)
        c["feedback"].play.assert_any_call("error")
        played_cues = [call.args[0] for call in c["feedback"].play.call_args_list]
>       assert "transcribe_done" not in played_cues
E       AssertionError: assert 'transcribe_done' not in ['error', 'transcribe_done']

tests/test_session.py:1147: AssertionError
------------------------------ Captured log call -------------------------------
ERROR    stenographer.session:session.py:696 session: rewrite_prompt failed: llm call failed
=========================== short test summary info ============================
FAILED tests/test_session.py::test_prompt_mode_lazy_model_load_shows_prompt_listening_notification
FAILED tests/test_session.py::test_prompt_mode_llm_failure_plays_only_error_cue_not_transcribe_done
============================== 2 failed in 0.20s ===============================
```

Each failed for the reason predicted by the spec: the first because `show_listening_prompt` was never called (0 times) — `_on_model_loaded` was calling `show_listening()` unconditionally; the second because `transcribe_done` WAS present in the play call list alongside `error`.

Post-implementation (both fixes applied):
```
============================= test session starts ==============================
collecting ... collected 2 items

tests/test_session.py::test_prompt_mode_lazy_model_load_shows_prompt_listening_notification PASSED [ 50%]
tests/test_session.py::test_prompt_mode_llm_failure_plays_only_error_cue_not_transcribe_done PASSED [100%]

============================== 2 passed in 0.13s ===============================
```

## AC-2

`_on_model_loaded` now branches on `self._recording_source` exactly as `on_recording_start` does, calling `show_listening_prompt()` when the source is `"prompt"` and `show_listening()` otherwise. Verified by `test_prompt_mode_lazy_model_load_shows_prompt_listening_notification`, which drives the real flow: `on_recording_start(source="prompt")` sets `_recording_source = "prompt"` and `_recording = True`, then `_on_model_loaded()` (the lazy-load-complete callback) is invoked directly, and asserts `show_listening_prompt` was called once and `show_listening` was not called.

```
.venv/bin/pytest tests/test_session.py::test_prompt_mode_lazy_model_load_shows_prompt_listening_notification -v
```
```
tests/test_session.py::test_prompt_mode_lazy_model_load_shows_prompt_listening_notification PASSED [100%]
============================== 1 passed in 0.03s ===============================
```

## AC-3

`_process` now tracks a local `prompt_llm_failed` flag, set `True` in the `except llm_module.LlmError` branch, and the function's final `transcribe_done` cue play is guarded with `and not prompt_llm_failed`. Verified by `test_prompt_mode_llm_failure_plays_only_error_cue_not_transcribe_done`, which asserts `feedback.play("error")` fires, `"transcribe_done"` is absent from the play call list, and the raw transcript is still typed (`injector.type_text("hello world")`) and clipboarded (`clipboard.copy("hello world")`).

```
.venv/bin/pytest tests/test_session.py::test_prompt_mode_llm_failure_plays_only_error_cue_not_transcribe_done -v
```
```
tests/test_session.py::test_prompt_mode_llm_failure_plays_only_error_cue_not_transcribe_done PASSED [100%]
============================== 1 passed in 0.03s ===============================
```

## AC-4

```
.venv/bin/pytest -m "not integration"
```
```
tests/test_bench.py ........                                             [  1%]
tests/test_capabilities.py ..                                            [  2%]
tests/test_capture.py ..................................                 [  9%]
tests/test_cli.py ..........                                             [ 11%]
tests/test_cli_completion.py ...                                         [ 11%]
tests/test_cli_systemd.py ......                                         [ 12%]
tests/test_cli_update.py .........                                       [ 14%]
tests/test_clipboard.py ..........                                       [ 16%]
tests/test_config.py ................................................... [ 27%]
..................................................                       [ 37%]
tests/test_errors.py .................                                   [ 41%]
tests/test_feedback.py .........                                         [ 42%]
tests/test_formatter.py ....................                             [ 47%]
tests/test_gen_cues.py .                                                 [ 47%]
tests/test_hotkey.py ..................................                  [ 54%]
tests/test_inject.py ....................                                [ 58%]
tests/test_lazy_model.py ........................                        [ 63%]
tests/test_live.py ....................                                  [ 67%]
tests/test_llm.py ........                                               [ 68%]
tests/test_notification.py ....................                          [ 73%]
tests/test_packaging.py .                                                [ 73%]
tests/test_session.py .................................................. [ 83%]
.........................                                                [ 88%]
tests/test_streaming.py ...........                                      [ 90%]
tests/test_transcription.py ....                                         [ 91%]
tests/test_update.py ...................................                 [ 98%]
tests/test_worker_cancel.py .....                                        [100%]

====================== 487 passed, 4 deselected in 20.46s ======================
```

Lint/format also clean:
```
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```
```
All checks passed!
57 files already formatted
```
