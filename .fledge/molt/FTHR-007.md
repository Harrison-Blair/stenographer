# FTHR-007 evidence: Bump version to 0.8.0

## AC-1

Test added: `tests/test_packaging.py::test_pyproject_version_is_0_8_0`.

Command: `.venv/bin/pytest tests/test_packaging.py -v`

Pre-implementation (unchanged `pyproject.toml`, version = "0.7.7") — FAILING output, captured verbatim:

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-007
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 1 item

tests/test_packaging.py::test_pyproject_version_is_0_8_0 FAILED          [100%]

=================================== FAILURES ===================================
_______________________ test_pyproject_version_is_0_8_0 ________________________

    def test_pyproject_version_is_0_8_0():
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text())
>       assert data["project"]["version"] == "0.8.0"
E       AssertionError: assert '0.7.7' == '0.8.0'
E         
E         - 0.8.0
E         + 0.7.7

tests/test_packaging.py:11: AssertionError
=========================== short test summary info ============================
FAILED tests/test_packaging.py::test_pyproject_version_is_0_8_0 - AssertionEr...
============================== 1 failed in 0.02s ===============================
```

Post-implementation (after changing `pyproject.toml`'s version to "0.8.0") — PASSING output: see AC-2 below.

## AC-2

Change: `pyproject.toml` line 3, `version = "0.7.7"` → `version = "0.8.0"`. No other files in `src/` reference the version literal (confirmed by grep below).

```
$ grep -rn "0.7.7" pyproject.toml src/
(no matches after change)
```

Command: `.venv/bin/pytest tests/test_packaging.py -v`

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-007
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 1 item

tests/test_packaging.py::test_pyproject_version_is_0_8_0 PASSED          [100%]

============================== 1 passed in 0.02s ===============================
```

## AC-3

Command: `.venv/bin/pytest -m "not integration"`

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-007
configfile: pyproject.toml
testpaths: tests
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 429 items / 4 deselected / 425 selected

tests/test_bench.py ........                                             [  1%]
tests/test_capabilities.py ..                                            [  2%]
tests/test_capture.py ..................................                 [ 10%]
tests/test_cli_completion.py ...                                         [ 11%]
tests/test_cli_systemd.py ......                                         [ 12%]
tests/test_cli_update.py .........                                       [ 14%]
tests/test_clipboard.py ..........                                       [ 16%]
tests/test_config.py ................................................... [ 28%]
......................................                                   [ 37%]
tests/test_errors.py .................                                   [ 41%]
tests/test_feedback.py .........                                         [ 44%]
tests/test_formatter.py ..................                               [ 48%]
tests/test_hotkey.py ..................................                  [ 56%]
tests/test_inject.py ....................                                [ 60%]
tests/test_lazy_model.py ........................                        [ 66%]
tests/test_live.py ....................                                  [ 71%]
tests/test_notification.py ..............                                [ 74%]
tests/test_packaging.py .                                                [ 74%]
tests/test_session.py .................................................. [ 86%]
..                                                                       [ 87%]
tests/test_streaming.py ...........                                      [ 89%]
tests/test_transcription.py ....                                         [ 90%]
tests/test_update.py ...................................                 [ 98%]
tests/test_worker_cancel.py .....                                        [100%]

====================== 425 passed, 4 deselected in 16.46s ======================
```
