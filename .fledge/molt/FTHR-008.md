# FTHR-008 Evidence — Classify connection-level failures as LlmError

## AC-1

### Pre-implementation (unchanged `llm.py`): tests fail for the expected reason

Command:
```
.venv/bin/pytest -m "not integration" tests/test_llm.py::test_rewrite_prompt_connection_reset_raises_llm_error tests/test_llm.py::test_rewrite_prompt_incomplete_read_raises_llm_error tests/test_session.py::test_session_processor_survives_llm_connection_failure -v
```

Captured output (verbatim, truncated to the failure summaries — full tracebacks below):
```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- .../\.venv/bin/python3
collected 3 items

tests/test_llm.py::test_rewrite_prompt_connection_reset_raises_llm_error FAILED
tests/test_llm.py::test_rewrite_prompt_incomplete_read_raises_llm_error FAILED
tests/test_session.py::test_session_processor_survives_llm_connection_failure FAILED

=================================== FAILURES ====================================
_______ test_rewrite_prompt_connection_reset_raises_llm_error _______
    def _execute_mock_call(self, /, *args, **kwargs):
        effect = self.side_effect
        if effect is not None:
            if _is_exception(effect):
>               raise effect
E               ConnectionResetError: connection reset by peer
/usr/lib/python3.14/unittest/mock.py:1241: ConnectionResetError

_______ test_rewrite_prompt_incomplete_read_raises_llm_error _______
    def _execute_mock_call(self, /, *args, **kwargs):
        effect = self.side_effect
        if effect is not None:
            if _is_exception(effect):
>               raise effect
E               http.client.IncompleteRead: IncompleteRead(7 bytes read)
/usr/lib/python3.14/unittest/mock.py:1241: IncompleteRead

_______ test_session_processor_survives_llm_connection_failure _______
    src/stenographer/session.py:215: in _process_utterance_queue
        self._process(samples, mode, abort, source)
    src/stenographer/session.py:692: in _process
        text = llm_module.rewrite_prompt(self._cfg.llm, text)
    src/stenographer/llm.py:53: in rewrite_prompt
        with urllib.request.urlopen(request, timeout=cfg.timeout_seconds) as resp:
    /usr/lib/python3.14/unittest/mock.py:1245: in _execute_mock_call
        raise result
E   ConnectionResetError: connection reset by peer

=========================== short test summary info ============================
FAILED tests/test_llm.py::test_rewrite_prompt_connection_reset_raises_llm_error
FAILED tests/test_llm.py::test_rewrite_prompt_incomplete_read_raises_llm_error
FAILED tests/test_session.py::test_session_processor_survives_llm_connection_failure
============================== 3 failed in 0.31s ===============================
```

All three fail for the expected reason: the raw `ConnectionResetError` /
`http.client.IncompleteRead` propagates uncaught out of `rewrite_prompt`
(`test_llm.py`, no `LlmError` raised — `pytest.raises(LlmError)` never
matches, the raw exception surfaces instead), and out of
`Session._process_utterance_queue` itself in the `test_session.py` case
(proving the processor thread's run loop would die on this failure class,
never reaching the second queued utterance).

### Post-implementation: same tests pass

Command:
```
.venv/bin/pytest -m "not integration" tests/test_llm.py tests/test_session.py -v
```

Captured output (relevant lines):
```
tests/test_llm.py::test_rewrite_prompt_success_returns_content PASSED
tests/test_llm.py::test_rewrite_prompt_sends_expected_request_body PASSED
tests/test_llm.py::test_rewrite_prompt_connection_error_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_timeout_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_http_error_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_connection_reset_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_incomplete_read_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_malformed_json_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_missing_content_key_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_empty_content_raises_llm_error PASSED
...
tests/test_session.py::test_session_processor_survives_llm_connection_failure PASSED
...
============================== 84 passed in 0.55s ==============================
```

## AC-2

`src/stenographer/llm.py` now catches `(ConnectionError, http.client.IncompleteRead)`
in the same `try` statement as the existing `HTTPError`/`URLError`/`TimeoutError`
branches, wrapping `urlopen(...)` and `resp.read()`, and raises
`LlmError(f"llm: connection error calling {url}: {exc}") from exc` (ERROR-logged
first), matching the existing per-branch message style. `ConnectionError` is the
builtin base class covering `ConnectionResetError`, `ConnectionAbortedError`,
`BrokenPipeError`, etc.

Evidence: `tests/test_llm.py::test_rewrite_prompt_connection_reset_raises_llm_error`
and `tests/test_llm.py::test_rewrite_prompt_incomplete_read_raises_llm_error` both
pass post-implementation (see AC-1's post-implementation run above).

Command:
```
.venv/bin/pytest -m "not integration" tests/test_llm.py -v
```
Output:
```
tests/test_llm.py::test_rewrite_prompt_success_returns_content PASSED
tests/test_llm.py::test_rewrite_prompt_sends_expected_request_body PASSED
tests/test_llm.py::test_rewrite_prompt_connection_error_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_timeout_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_http_error_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_connection_reset_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_incomplete_read_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_malformed_json_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_missing_content_key_raises_llm_error PASSED
tests/test_llm.py::test_rewrite_prompt_empty_content_raises_llm_error PASSED
========================== 10 passed in 0.06s ==========================
```

## AC-3

`tests/test_session.py::test_session_processor_survives_llm_connection_failure`
exercises the real `stenographer.llm` module (not the `sys.modules` fake used
elsewhere in the file) with `urllib.request.urlopen` mocked to raise
`ConnectionResetError` on the first prompt-mode utterance and return a valid
response on the second. This ties the test's pass/fail outcome directly to the
`llm.py` fix (AC-2): pre-fix, the raw `ConnectionResetError` is not an
`LlmError`, so `Session._process`'s `except llm_module.LlmError` does not catch
it, and it kills `_process_utterance_queue`'s run loop before the second
utterance is dequeued (see AC-1's pre-implementation capture). Post-fix,
`rewrite_prompt` raises `LlmError`, which `_process` already catches (existing
code, unchanged) — falling back to the first utterance's raw transcript and
continuing the loop, so the second utterance is fully processed
(`injector.type_text("second utterance")` / `clipboard.copy("second
utterance")`, asserted via `assert_any_call` plus a `call_count == 2` check
proving both utterances were typed, not just one).

Command:
```
.venv/bin/pytest -m "not integration" tests/test_session.py::test_session_processor_survives_llm_connection_failure -v
```
Output:
```
tests/test_session.py::test_session_processor_survives_llm_connection_failure PASSED
========================== 1 passed in 0.06s ==========================
```

No change was made to `session.py` (per the spec's Approach) — `_process`'s
existing `except llm_module.LlmError` handling already covers the now-widened
`LlmError`.

## AC-4

Command:
```
.venv/bin/pytest -m "not integration"
```
Output (tail):
```
..................................................                       [ 37%]
tests/test_errors.py .................                                   [ 40%]
tests/test_feedback.py .........                                         [ 42%]
tests/test_formatter.py ....................                             [ 46%]
tests/test_gen_cues.py .                                                 [ 47%]
tests/test_hotkey.py ..................................                  [ 54%]
tests/test_inject.py ....................                                [ 58%]
tests/test_lazy_model.py ........................                        [ 63%]
tests/test_live.py ....................                                  [ 67%]
tests/test_llm.py ..........                                             [ 69%]
tests/test_notification.py ....................                          [ 73%]
tests/test_packaging.py .                                                [ 73%]
tests/test_session.py .................................................. [ 83%]
........................                                                 [ 88%]
tests/test_streaming.py ...........                                      [ 90%]
tests/test_transcription.py ....                                         [ 91%]
tests/test_update.py ...................................                 [ 98%]
tests/test_worker_cancel.py .....                                        [100%]

====================== 488 passed, 4 deselected in 20.15s ======================
```

Lint and format also clean:
```
.venv/bin/ruff check .
All checks passed!

.venv/bin/ruff format --check .
57 files already formatted
```
