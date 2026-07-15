# FTHR-012 evidence

## AC-1: Tests observed failing before implementation, passing after

### Pre-implementation (unchanged code)

Command:

```
.venv/bin/pytest tests/test_cli.py -k "test_run_stop_names_stop_replacement or test_run_disable_names_disable_replacement or test_run_alone_still_dispatches_normally or test_transcribe_default_output_is_formatted or test_transcribe_raw_flag_emits_verbatim_text or test_parser_accepts_transcribe_raw_flag" -v
```

Output (verbatim, captured before any implementation changes — only the six
new tests existed in `tests/test_cli.py`, `cli.py`/`_parser.py` untouched):

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.fledge/burrows/FTHR-012/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-012
configfile: pyproject.toml
plugins: anyio-4.14.2, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 16 items / 10 deselected / 6 selected

tests/test_cli.py::test_run_stop_names_stop_replacement FAILED           [ 16%]
tests/test_cli.py::test_run_disable_names_disable_replacement FAILED     [ 33%]
tests/test_cli.py::test_run_alone_still_dispatches_normally PASSED       [ 50%]
tests/test_cli.py::test_transcribe_default_output_is_formatted FAILED    [ 66%]
tests/test_cli.py::test_transcribe_raw_flag_emits_verbatim_text FAILED   [ 83%]
tests/test_cli.py::test_parser_accepts_transcribe_raw_flag FAILED        [100%]

=================================== FAILURES ===================================
_____________________ test_run_stop_names_stop_replacement _____________________
...
src/stenographer/cli.py:786: in main
    args = parser.parse_args(argv)
           ^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib/python3.14/argparse.py:2009: in parse_args
    self.error(msg)
/usr/lib/python3.14/argparse.py:2782: in error
    self.exit(2, _('%(prog)s: error: %(message)s\n') % args)
...
status = 2, message = 'stenographer: error: unrecognized arguments: stop\n'
...
E       SystemExit: 2
----------------------------- Captured stderr call -----------------------------
usage: stenographer [-h] [-c CONFIG] [-v]
                    {run,enable,disable,start,stop,transcribe,dictate,model,update,doctor,devices,bench} ...
stenographer: error: unrecognized arguments: stop
_________________ test_run_disable_names_disable_replacement ___________________
...
status = 2, message = 'stenographer: error: unrecognized arguments: disable\n'
...
E       SystemExit: 2
----------------------------- Captured stderr call -----------------------------
usage: stenographer [-h] [-c CONFIG] [-v]
                    {run,enable,disable,start,stop,transcribe,dictate,model,update,doctor,devices,bench} ...
stenographer: error: unrecognized arguments: disable
_________________ test_transcribe_default_output_is_formatted __________________
...
>       rc = cli.cmd_transcribe(Config.defaults(), path, raw=False)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       TypeError: cmd_transcribe() got an unexpected keyword argument 'raw'
_________________ test_transcribe_raw_flag_emits_verbatim_text _________________
...
>       rc = cli.cmd_transcribe(Config.defaults(), path, raw=True)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       TypeError: cmd_transcribe() got an unexpected keyword argument 'raw'
___________________ test_parser_accepts_transcribe_raw_flag ____________________
...
>       with_flag = build_parser().parse_args(["transcribe", "f.wav", "--raw"])
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
...
status = 2, message = 'stenographer: error: unrecognized arguments: --raw\n'
...
E       SystemExit: 2
----------------------------- Captured stderr call -----------------------------
usage: stenographer [-h] [-c CONFIG] [-v]
                    {run,enable,disable,start,stop,transcribe,dictate,model,update,doctor,devices,bench} ...
stenographer: error: unrecognized arguments: --raw
=========================== short test summary info ============================
FAILED tests/test_cli.py::test_run_stop_names_stop_replacement - SystemExit: 2
FAILED tests/test_cli.py::test_run_disable_names_disable_replacement - System...
FAILED tests/test_cli.py::test_transcribe_default_output_is_formatted - TypeE...
FAILED tests/test_cli.py::test_transcribe_raw_flag_emits_verbatim_text - Type...
FAILED tests/test_cli.py::test_parser_accepts_transcribe_raw_flag - SystemExi...
================== 5 failed, 1 passed, 10 deselected in 0.80s ==================
```

Each failure is for the exact expected reason: the two `run` tests hit
argparse's generic `unrecognized arguments` message at `SystemExit: 2` (no
pointed error yet); the two `transcribe`-output tests fail with
`TypeError: cmd_transcribe() got an unexpected keyword argument 'raw'` (no
`raw` param yet); the parser test fails with argparse's generic
`unrecognized arguments: --raw`. `test_run_alone_still_dispatches_normally`
already passes pre-implementation — it is a regression guard confirming bare
`run` isn't affected, both before and after F2 lands.

### Post-implementation

Command: same as above.

Output:

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.fledge/burrows/FTHR-012/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-012
configfile: pyproject.toml
plugins: anyio-4.14.2, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 16 items / 10 deselected / 6 selected

tests/test_cli.py::test_run_stop_names_stop_replacement PASSED           [ 16%]
tests/test_cli.py::test_run_disable_names_disable_replacement PASSED     [ 33%]
tests/test_cli.py::test_run_alone_still_dispatches_normally PASSED       [ 50%]
tests/test_cli.py::test_transcribe_default_output_is_formatted PASSED    [ 66%]
tests/test_cli.py::test_transcribe_raw_flag_emits_verbatim_text PASSED   [ 83%]
tests/test_cli.py::test_parser_accepts_transcribe_raw_flag PASSED        [100%]

============================== 6 passed, 10 deselected in 0.7Xs ==============================
```

(One intermediate run caught a test-expectation bug of my own: the first
draft of `test_transcribe_default_output_is_formatted` asserted
`"I think so\n"`, but `Config.defaults()` has `append_trailing_space=True`,
so `HeuristicFormatter` correctly emits `"I think so \n"`. Fixed the
assertion to match the real, correct formatter output — the test still
distinguishes formatted from raw output, since raw is `"i think so\n"`.)

## AC-2: `run stop` / `run disable` → pointed nonzero error, `run` unaffected

Implementation: `main()` in `cli.py` scans `argv` for an adjacent `"run"`
followed by `"stop"`/`"disable"` before calling `parser.parse_args`, prints a
pointed message to stderr, and returns `1`. No nested subcommand was added to
`run`'s subparser.

Command:

```
.venv/bin/python -c "import stenographer.cli as cli; import sys; sys.exit(cli.main(['run', 'stop']))"; echo "exit=$?"
.venv/bin/python -c "import stenographer.cli as cli; import sys; sys.exit(cli.main(['run', 'disable']))"; echo "exit=$?"
```

Output:

```
stenographer: `run stop` was removed; use `stenographer stop` instead.
exit=1
stenographer: `run disable` was removed; use `stenographer disable` instead.
exit=1
```

Covered by tests `test_run_stop_names_stop_replacement`,
`test_run_disable_names_disable_replacement` (assert nonzero exit, stderr
names the replacement command, and stderr does NOT contain argparse's
`"unrecognized arguments"` string) and the regression guard
`test_run_alone_still_dispatches_normally` (bare `run` still parses to
`subcommand == "run"` with no error — confirms the F2 scan doesn't
false-positive). `run`'s subparser (`_parser.py`) is unchanged — it still
takes no arguments.

## AC-3: `transcribe FILE` (no flag) still formats via HeuristicFormatter

`cmd_transcribe`'s default (`raw=False`) path is unchanged from before this
feather: `HeuristicFormatter(...).format_batch(result.segments)`.

Covered by `test_transcribe_default_output_is_formatted`: with `Model.transcribe`
stubbed to return `TranscriptionResult(text="i think so", segments=[SegmentInfo(text=" i think so", ...)])`,
`cli.cmd_transcribe(cfg, path, raw=False)` prints `"I think so \n"` —
capitalized/spaced per `HeuristicFormatter` conventions (matches the
existing `test_format_batch_accepts_segments` convention in
`tests/test_formatter.py`), not the raw `"i think so"`.

## AC-4: `transcribe FILE --raw` emits `result.text` verbatim

`cmd_transcribe`'s `raw=True` path bypasses `HeuristicFormatter` entirely and
writes `result.text` as-is.

Covered by `test_transcribe_raw_flag_emits_verbatim_text`: same fixture,
`raw=True`, asserts stdout is exactly `"i think so\n"` (the raw, lowercase,
unformatted `result.text`).

Also covered by `test_parser_accepts_transcribe_raw_flag`: `--raw` parses to
`args.raw is True`; omitting it defaults to `args.raw is False`.

## AC-5: README documents default formatted output and `--raw`

`README.md` under `## Run` now reads:

```
stenographer transcribe FILE     # batch: print formatted transcript to stdout (default)
stenographer transcribe FILE --raw # batch: print the raw, unformatted transcript verbatim
```

(previously a single line: `stenographer transcribe FILE     # batch: print transcript to stdout`).
Not test-driven per the spec; verified by reading the file.

## AC-6: Full unit suite passes with no regressions

Command:

```
.venv/bin/pytest -m "not integration"
```

Output:

```
........................................................................ [ 14%]
........................................................................ [ 29%]
........................................................................ [ 43%]
........................................................................ [ 58%]
........................................................................ [ 73%]
........................................................................ [ 87%]
...........................................................              [100%]
491 passed, 4 deselected in 19.88s
```

Lint/format also clean:

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
57 files already formatted
```
