# FTHR-002 Evidence: Config surface for prompt mode

## AC-1: Tests observed failing before implementation, passing after

All new tests live in `tests/test_config.py`:

- `test_defaults_include_prompt_binding`
- `test_prompt_binding_overlap_with_main_binding_rejected`
- `test_prompt_binding_invalid_key_rejected`
- `test_defaults_include_llm_config`
- `test_llm_base_url_must_be_http`
- `test_llm_timeout_out_of_range_rejected`
- `test_llm_temperature_out_of_range_rejected`
- `test_llm_max_tokens_out_of_range_rejected`
- `test_load_full_config_with_llm_overrides`

(`test_defaults_hotkey` was also extended in place to assert `prompt_binding`.)

### Pre-implementation (FAILING) run

Command: with the new tests added to `tests/test_config.py` but `src/stenographer/config.py`
still at its unmodified (pre-feature) state (verified via `git stash push -- src/stenographer/config.py`):

```
$ .venv/bin/pytest tests/test_config.py -v
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.fledge/burrows/FTHR-002/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-002
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
____________________ ERROR collecting tests/test_config.py _____________________
ImportError while importing test module '/home/penguin/source/stenographer/.fledge/burrows/FTHR-002/tests/test_config.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_config.py:10: in <module>
    from stenographer.config import (
E   ImportError: cannot import name 'LlmConfig' from 'stenographer.config' (/home/penguin/source/stenographer/.fledge/burrows/FTHR-002/src/stenographer/config.py)
=========================== short test summary info ============================
ERROR tests/test_config.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.08s ===============================
```

This is the expected failure reason: `LlmConfig` (and, by extension, the `prompt_binding` field
and `llm` section) do not exist yet in `config.py`, so the whole module fails to collect. This
is the correct "fails for the expected reason" signal per the spec (missing fields/type).

### Post-implementation (PASSING) run

```
$ .venv/bin/pytest tests/test_config.py -v
...
tests/test_config.py::test_defaults_hotkey PASSED
tests/test_config.py::test_defaults_include_prompt_binding PASSED
...
tests/test_config.py::test_defaults_include_llm_config PASSED
...
tests/test_config.py::test_prompt_binding_overlap_with_main_binding_rejected PASSED
tests/test_config.py::test_prompt_binding_invalid_key_rejected PASSED
...
tests/test_config.py::test_llm_base_url_must_be_http PASSED
tests/test_config.py::test_llm_timeout_out_of_range_rejected PASSED
tests/test_config.py::test_llm_temperature_out_of_range_rejected PASSED
tests/test_config.py::test_llm_max_tokens_out_of_range_rejected PASSED
tests/test_config.py::test_load_full_config_with_llm_overrides PASSED
...
============================== 98 passed in 0.11s ==============================
```

Full output captured by running `.venv/bin/pytest tests/test_config.py -v` after implementation
(see AC-4 section for the complete-suite run, which includes all 98 `test_config.py` tests
passing).

## AC-2: `Config.defaults()` exposes `hotkey.prompt_binding` and a fully-defaulted `llm` section

Implemented in `src/stenographer/config.py`:
- `HotkeyConfig.prompt_binding: str`, defaulted in `Config.defaults()` to `"KEY_RIGHTSHIFT"`.
- New `LlmConfig` frozen dataclass (`base_url`, `model`, `system_prompt`, `timeout_seconds`,
  `temperature`, `max_tokens`), defaulted in `Config.defaults()` to:
  `base_url="http://localhost:8080"`, `model=""`, a non-empty `system_prompt`,
  `timeout_seconds=30.0`, `temperature=0.2`, `max_tokens=512`.

Verified by:
- `test_defaults_include_prompt_binding` — asserts `Config.defaults().hotkey.prompt_binding == "KEY_RIGHTSHIFT"`.
- `test_defaults_hotkey` — full-equality check on `HotkeyConfig` including the new field.
- `test_defaults_include_llm_config` — full-equality check on `LlmConfig` plus a non-empty
  `system_prompt` assertion.

```
$ .venv/bin/pytest tests/test_config.py -k "test_defaults_include_prompt_binding or test_defaults_hotkey or test_defaults_include_llm_config" -v
tests/test_config.py::test_defaults_hotkey PASSED
tests/test_config.py::test_defaults_include_prompt_binding PASSED
tests/test_config.py::test_defaults_include_llm_config PASSED
============================== 3 passed in 0.03s ==============================
```

## AC-3: Invalid values for every new field rejected with `ConfigError`

- `prompt_binding` overlapping `binding`: `_build_hotkey` now parses `prompt_binding` via
  `HotkeyBinding.parse` and unconditionally raises `ConfigError` (no defaults-only leniency,
  per spec) if it shares evdev keys with the main `binding`.
- `prompt_binding` unparseable: `HotkeyBinding.parse` failure is caught and re-raised as
  `ConfigError(path, "hotkey.prompt_binding", ...)`.
- `llm.base_url` not `http(s)://`: rejected in `_build_llm`.
- `llm.timeout_seconds` outside `(0, 300]`: rejected in `_build_llm`.
- `llm.temperature` outside `[0, 2]`: rejected in `_build_llm`.
- `llm.max_tokens` outside `[1, 8192]`: rejected in `_build_llm`.

```
$ .venv/bin/pytest tests/test_config.py -k "prompt_binding_overlap or prompt_binding_invalid or llm_base_url or llm_timeout or llm_temperature or llm_max_tokens" -v
tests/test_config.py::test_prompt_binding_overlap_with_main_binding_rejected PASSED
tests/test_config.py::test_prompt_binding_invalid_key_rejected PASSED
tests/test_config.py::test_llm_base_url_must_be_http PASSED
tests/test_config.py::test_llm_timeout_out_of_range_rejected PASSED
tests/test_config.py::test_llm_temperature_out_of_range_rejected PASSED
tests/test_config.py::test_llm_max_tokens_out_of_range_rejected PASSED
============================== 6 passed in 0.03s ==============================
```

## AC-4: `.venv/bin/pytest -m "not integration"` passes with no regressions

```
$ .venv/bin/pytest -m "not integration"
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-002
configfile: pyproject.toml
testpaths: tests
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 437 items / 4 deselected / 433 selected

tests/test_bench.py ........                                             [  1%]
tests/test_capabilities.py ..                                            [  2%]
tests/test_capture.py ..................................                 [ 10%]
tests/test_cli_completion.py ...                                         [ 10%]
tests/test_cli_systemd.py ......                                         [ 12%]
tests/test_cli_update.py .........                                       [ 14%]
tests/test_clipboard.py ..........                                       [ 16%]
tests/test_config.py ................................................... [ 28%]
...............................................                          [ 39%]
tests/test_errors.py .................                                   [ 43%]
tests/test_feedback.py .........                                         [ 45%]
tests/test_formatter.py ..................                               [ 49%]
tests/test_hotkey.py ..................................                  [ 57%]
tests/test_inject.py ....................                                [ 61%]
tests/test_lazy_model.py ........................                        [ 67%]
tests/test_live.py ....................                                  [ 72%]
tests/test_notification.py ..............                                [ 75%]
tests/test_session.py .................................................. [ 86%]
..                                                                       [ 87%]
tests/test_streaming.py ...........                                      [ 89%]
tests/test_transcription.py ....                                         [ 90%]
tests/test_update.py ...................................                 [ 98%]
tests/test_worker_cancel.py .....                                        [100%]

====================== 433 passed, 4 deselected in 18.03s ======================
```

Additionally verified:
- `.venv/bin/ruff check .` → "All checks passed!"
- `.venv/bin/ruff format --check .` → "52 files already formatted" (no reformatting needed).
