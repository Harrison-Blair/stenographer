# FTHR-003 Evidence: Local LLM HTTP client

## AC-1: Tests observed failing before implementation and passing after

All new tests live in `tests/test_llm.py`:

- `test_rewrite_prompt_success_returns_content`
- `test_rewrite_prompt_sends_expected_request_body`
- `test_rewrite_prompt_connection_error_raises_llm_error`
- `test_rewrite_prompt_timeout_raises_llm_error`
- `test_rewrite_prompt_http_error_raises_llm_error`
- `test_rewrite_prompt_malformed_json_raises_llm_error`
- `test_rewrite_prompt_missing_content_key_raises_llm_error`
- `test_rewrite_prompt_empty_content_raises_llm_error`

### Pre-implementation (FAILING) run

Command: `tests/test_llm.py` added, with `src/stenographer/llm.py` not yet
existing and `LlmError` not yet added to `src/stenographer/errors.py`:

```
$ .venv/bin/pytest tests/test_llm.py -v
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.fledge/burrows/FTHR-003/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-003
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
______________________ ERROR collecting tests/test_llm.py ______________________
ImportError while importing test module '/home/penguin/source/stenographer/.fledge/burrows/FTHR-003/tests/test_llm.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_llm.py:12: in <module>
    from stenographer.errors import LlmError
E   ImportError: cannot import name 'LlmError' from 'stenographer.errors' (/home/penguin/source/stenographer/.fledge/burrows/FTHR-003/src/stenographer/errors.py)
=========================== short test summary info ============================
ERROR tests/test_llm.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.05s ===============================
```

Fails for the expected reason: `LlmError` (and the `llm` module importing it) do
not exist yet.

### Post-implementation (PASSING) run

```
$ .venv/bin/pytest tests/test_llm.py -v
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.fledge/burrows/FTHR-003/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-003
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 8 items

tests/test_llm.py::test_rewrite_prompt_success_returns_content PASSED    [ 12%]
tests/test_llm.py::test_rewrite_prompt_sends_expected_request_body PASSED [ 25%]
tests/test_llm.py::test_rewrite_prompt_connection_error_raises_llm_error PASSED [ 37%]
tests/test_llm.py::test_rewrite_prompt_timeout_raises_llm_error PASSED   [ 50%]
tests/test_llm.py::test_rewrite_prompt_http_error_raises_llm_error PASSED [ 62%]
tests/test_llm.py::test_rewrite_prompt_malformed_json_raises_llm_error PASSED [ 75%]
tests/test_llm.py::test_rewrite_prompt_missing_content_key_raises_llm_error PASSED [ 87%]
tests/test_llm.py::test_rewrite_prompt_empty_content_raises_llm_error PASSED [100%]

============================== 8 passed in 0.02s ===============================
```

## AC-2: Spec-conformant OpenAI-compatible chat-completions request

`rewrite_prompt()` (in `src/stenographer/llm.py`) POSTs to
`f"{cfg.base_url}/v1/chat/completions"` via `urllib.request.Request`/`urlopen`
with `timeout=cfg.timeout_seconds`, sending a JSON body of the shape
`{"model": cfg.model, "messages": [{"role": "system", "content": cfg.system_prompt}, {"role": "user", "content": transcript}], "temperature": cfg.temperature, "max_tokens": cfg.max_tokens}`.

`test_rewrite_prompt_sends_expected_request_body` asserts the exact posted body
(model, messages, temperature, max_tokens) matches the passed `LlmConfig` and
transcript; `test_rewrite_prompt_success_returns_content` asserts the
extracted, stripped `choices[0].message.content` is returned. Both pass (see
AC-1 post-implementation run above).

## AC-3: Every failure mode raises `LlmError`

`rewrite_prompt()` catches `urllib.error.HTTPError` (non-2xx),
`urllib.error.URLError` (unreachable/DNS), `TimeoutError` (covers
`socket.timeout`, its alias since Python 3.10), `json.JSONDecodeError`
(malformed body), and missing/empty `choices[0].message.content`
(`KeyError`/`IndexError`/`TypeError`, or blank/whitespace-only string) —
re-raising each as `LlmError` rather than propagating the raw stdlib
exception or returning a partial result.

Covered by:
- `test_rewrite_prompt_connection_error_raises_llm_error` (URLError)
- `test_rewrite_prompt_timeout_raises_llm_error` (TimeoutError)
- `test_rewrite_prompt_http_error_raises_llm_error` (HTTPError, 500)
- `test_rewrite_prompt_malformed_json_raises_llm_error` (invalid JSON body)
- `test_rewrite_prompt_missing_content_key_raises_llm_error` (missing `content` key)
- `test_rewrite_prompt_empty_content_raises_llm_error` (whitespace-only `content`)

All pass (see AC-1 post-implementation run above).

## AC-4: Full suite passes, no real network access

```
$ .venv/bin/pytest -m "not integration"
...
collected 446 items / 4 deselected / 442 selected
...
tests/test_llm.py ........                                               [ 72%]
...
====================== 442 passed, 4 deselected in 14.86s ======================
```

No regressions (442 passed, the pre-existing 4 integration-marked tests
deselected as before FTHR-003). `tests/test_llm.py` mocks
`stenographer.llm.urllib.request.urlopen` in every test via
`unittest.mock.patch` — no real network call is made.

Also clean:
```
$ .venv/bin/ruff check .
All checks passed!
$ .venv/bin/ruff format --check .
55 files already formatted
```
