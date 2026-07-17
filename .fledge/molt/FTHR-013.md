# FTHR-013 evidence

## AC-1

### Pre-implementation (unchanged code)

Command:

```
.venv/bin/pytest -m "not integration" \
  tests/test_config.py::test_defaults_have_no_prompt_binding_field \
  tests/test_config.py::test_defaults_have_no_llm_field \
  tests/test_config.py::test_default_hotkey_binding_is_right_alt \
  tests/test_config.py::test_legacy_llm_and_prompt_binding_keys_ignored \
  tests/test_config.py::test_format_default_toml_has_no_llm_or_prompt_binding \
  tests/test_session.py::test_session_has_no_attach_prompt_listener \
  -v
```

Output (verbatim, captured before any source changes — only the six new test
cases existed, added to `tests/test_config.py` and `tests/test_session.py`;
`config.py`/`session.py` untouched):

```
plugins: anyio-4.14.2, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 6 items

tests/test_config.py::test_defaults_have_no_prompt_binding_field FAILED  [ 16%]
tests/test_config.py::test_defaults_have_no_llm_field FAILED             [ 33%]
tests/test_config.py::test_default_hotkey_binding_is_right_alt FAILED    [ 50%]
tests/test_config.py::test_legacy_llm_and_prompt_binding_keys_ignored PASSED [ 66%]
tests/test_config.py::test_format_default_toml_has_no_llm_or_prompt_binding FAILED [ 83%]
tests/test_session.py::test_session_has_no_attach_prompt_listener FAILED [100%]

=================================== FAILURES ===================================
__________________ test_defaults_have_no_prompt_binding_field __________________

    def test_defaults_have_no_prompt_binding_field() -> None:
>       assert not hasattr(Config.defaults().hotkey, "prompt_binding")
E       AssertionError: assert not True
E        +  where True = hasattr(HotkeyConfig(binding='KEY_RIGHTCTRL', ..., prompt_binding='KEY_RIGHTALT'), 'prompt_binding')

tests/test_config.py:44: AssertionError
_______________________ test_defaults_have_no_llm_field ________________________

    def test_defaults_have_no_llm_field() -> None:
>       assert not hasattr(Config.defaults(), "llm")
E       AssertionError: assert not True
E        +  where True = hasattr(Config(..., llm=LlmConfig(base_url='http://localhost:8080', ...)), 'llm')

tests/test_config.py:48: AssertionError
____________ test_default_hotkey_binding_is_right_alt ___________________
    def test_default_hotkey_binding_is_right_alt() -> None:
>       assert Config.defaults().hotkey.binding == "KEY_RIGHTALT"
E       AssertionError: assert 'KEY_RIGHTCTRL' == 'KEY_RIGHTALT'

tests/test_config.py:52: AssertionError
____________ test_format_default_toml_has_no_llm_or_prompt_binding _____________

    def test_format_default_toml_has_no_llm_or_prompt_binding() -> None:
        from stenographer.config import _format_default_toml
        text = _format_default_toml()
>       assert "llm." not in text
E       assert 'llm.' not in '# stenograp...ready = ""\n'

tests/test_config.py:74: AssertionError
__________________ test_session_has_no_attach_prompt_listener __________________

    def test_session_has_no_attach_prompt_listener() -> None:
        session, _m = _make_session()
>       assert not hasattr(session, "attach_prompt_listener")
E       AssertionError: assert not True
E        +  where True = hasattr(<stenographer.session.Session object at 0x...>, 'attach_prompt_listener')

tests/test_session.py:711: AssertionError
=========================== short test summary info ============================
FAILED tests/test_config.py::test_defaults_have_no_prompt_binding_field
FAILED tests/test_config.py::test_defaults_have_no_llm_field
FAILED tests/test_config.py::test_default_hotkey_binding_is_right_alt
FAILED tests/test_config.py::test_format_default_toml_has_no_llm_or_prompt_binding
FAILED tests/test_session.py::test_session_has_no_attach_prompt_listener
========================= 5 failed, 1 passed in 0.23s ==========================
```

`test_legacy_llm_and_prompt_binding_keys_ignored` passes even before
implementation: it pins that `Config.load()` doesn't raise on stray
`[stenographer.llm]`/`hotkey.prompt_binding` keys, which is already true today
(those keys are still part of the current schema) and must remain true after
removal — a regression guard for AC-8, not a removal-triggered failure. The
other five fail for the expected reason: the fields/method/default still exist
on unchanged code.

### Post-implementation (all six new tests passing)

Command:

```
.venv/bin/pytest -m "not integration" \
  tests/test_config.py::test_defaults_have_no_prompt_binding_field \
  tests/test_config.py::test_defaults_have_no_llm_field \
  tests/test_config.py::test_default_hotkey_binding_is_right_alt \
  tests/test_config.py::test_legacy_llm_and_prompt_binding_keys_ignored \
  tests/test_config.py::test_format_default_toml_has_no_llm_or_prompt_binding \
  tests/test_session.py::test_session_has_no_attach_prompt_listener \
  -v
```

Output:

```
collecting ... collected 6 items

tests/test_config.py::test_defaults_have_no_prompt_binding_field PASSED  [ 16%]
tests/test_config.py::test_defaults_have_no_llm_field PASSED             [ 33%]
tests/test_config.py::test_default_hotkey_binding_is_right_alt PASSED    [ 50%]
tests/test_config.py::test_legacy_llm_and_prompt_binding_keys_ignored PASSED [ 66%]
tests/test_config.py::test_format_default_toml_has_no_llm_or_prompt_binding PASSED [ 83%]
tests/test_session.py::test_session_has_no_attach_prompt_listener PASSED [100%]

============================== 6 passed in 0.15s ===============================
```

## AC-2

`stenographer.llm` and `tests/test_llm.py` deleted (`git status` shows both as
`D`); no remaining import anywhere in `src/` or `tests/`:

```
$ test ! -f src/stenographer/llm.py && test ! -f tests/test_llm.py && echo "files absent: OK"
files absent: OK
$ grep -rn "stenographer\.llm\b" src/ tests/ | grep -v "\[stenographer.llm\]"
(no output — no import/attribute-access hits; the one surviving occurrence of
the string "stenographer.llm" is the TOML table header
`[stenographer.llm]` inside test_legacy_llm_and_prompt_binding_keys_ignored,
used deliberately to prove the loader ignores it)
```

## AC-3

```
$ grep -n "attach_prompt_listener\|_prompt_listener\|source == .prompt.\|source==.prompt." src/stenographer/session.py
(no output)
```

`Session` has no `attach_prompt_listener` method or `_prompt_listener`
attribute, and no code path checks `source == "prompt"`. Confirmed at runtime
by `tests/test_session.py::test_session_has_no_attach_prompt_listener` (passing
above).

## AC-4

```
$ .venv/bin/python -c "
from stenographer.config import Config
try:
    Config.defaults().hotkey.prompt_binding
    print('FAIL: attribute exists')
except AttributeError as e:
    print('OK:', e)
"
OK: 'HotkeyConfig' object has no attribute 'prompt_binding'
```

No config-loading code references `prompt_binding` (`_build_hotkey` in
`config.py` no longer parses or validates it — confirmed by reading the
diff and by `tests/test_config.py::test_defaults_have_no_prompt_binding_field`
passing above).

## AC-5

```
$ .venv/bin/python -c "
from stenographer.config import Config
h = Config.defaults().hotkey
print('binding=', h.binding)
print('cancel_binding=', h.cancel_binding)
assert h.binding == 'KEY_RIGHTALT'
assert h.cancel_binding == 'KEY_ESC'
print('OK')
"
binding= KEY_RIGHTALT
cancel_binding= KEY_ESC
OK
```

## AC-6

```
$ .venv/bin/python -c "
import stenographer.errors as e
try:
    e.LlmError
    print('FAIL')
except AttributeError as ex:
    print('OK:', ex)
"
OK: module 'stenographer.errors' has no attribute 'LlmError'
```

## AC-7

```
$ .venv/bin/python -c "
from stenographer.config import _format_default_toml
t = _format_default_toml()
assert 'llm.' not in t
assert 'prompt_binding' not in t
assert 'hotkey.binding = \"KEY_RIGHTALT\"' in t
print('OK')
"
OK
```

Also covered by `tests/test_config.py::test_format_default_toml_has_no_llm_or_prompt_binding`
(passing above).

## AC-8

```
$ .venv/bin/python -c "
import tempfile, pathlib
from stenographer.config import Config
with tempfile.TemporaryDirectory() as d:
    p = pathlib.Path(d) / 'config.toml'
    p.write_text('[stenographer]\nhotkey.prompt_binding = \"KEY_RIGHTALT\"\n\n[stenographer.llm]\nbase_url = \"http://localhost:9090\"\nmodel = \"qwen\"\n')
    cfg = Config.load(p)
    print('OK, loaded without raising')
"
OK, loaded without raising
```

Also covered by `tests/test_config.py::test_legacy_llm_and_prompt_binding_keys_ignored`
(passing above).

## AC-9

Command:

```
.venv/bin/pytest -m "not integration" -q
```

Output:

```
........................................................................ [ 15%]
........................................................................ [ 30%]
........................................................................ [ 46%]
........................................................................ [ 61%]
........................................................................ [ 77%]
........................................................................ [ 92%]
.................................                                        [100%]
465 passed, 4 deselected in 14.30s
```

Command:

```
.venv/bin/ruff check .
```

Output:

```
All checks passed!
```

Command:

```
.venv/bin/ruff format --check .
```

Output:

```
55 files already formatted
```

(AC-9 also contributes to PLM-007 FC-9, whose full satisfaction additionally
depends on FTHR-014, per the feather description.)
