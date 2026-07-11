# FTHR-001 Evidence: Default paragraph-pause to 0

## AC-1

Tests written first, run against unchanged code (venv built inside the
worktree via `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,build]"`):

```
$ .venv/bin/pytest tests/test_config.py::test_default_paragraph_pause_seconds_is_zero tests/test_formatter.py::test_no_paragraph_break_with_default_config tests/test_formatter.py::test_paragraph_break_still_available_via_explicit_config -v
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
collected 3 items

tests/test_config.py::test_default_paragraph_pause_seconds_is_zero FAILED [ 33%]
tests/test_formatter.py::test_no_paragraph_break_with_default_config FAILED [ 66%]
tests/test_formatter.py::test_paragraph_break_still_available_via_explicit_config PASSED [100%]

=================================== FAILURES ===================================
_________________ test_default_paragraph_pause_seconds_is_zero _________________

    def test_default_paragraph_pause_seconds_is_zero() -> None:
>       assert Config.defaults().formatting.paragraph_pause_seconds == 0.0
E       AssertionError: assert 2.0 == 0.0
E        +  where 2.0 = FormattingConfig(paragraph_pause_seconds=2.0, capitalize_sentences=True, normalize_spacing=True).paragraph_pause_seconds

tests/test_config.py:600: AssertionError
_________________ test_no_paragraph_break_with_default_config __________________

    def test_no_paragraph_break_with_default_config() -> None:
        f = HeuristicFormatter(Config.defaults().formatting, append_trailing_space=False)
        out = f.feed([_w(" one", 0.0, 0.5), _w(" two", 5.0, 5.5)])
>       assert "\n\n" not in out
E       AssertionError: assert '\n\n' not in 'One\n\nTwo'

tests/test_formatter.py:84: AssertionError
=========================== short test summary info ============================
FAILED tests/test_config.py::test_default_paragraph_pause_seconds_is_zero - A...
FAILED tests/test_formatter.py::test_no_paragraph_break_with_default_config
========================= 2 failed, 1 passed in 0.17s ==========================
```

The two new tests fail for the expected reason (default `paragraph_pause_seconds`
is still `2.0`, so a 5s pause under the old default inserts a break). The third
test, `test_paragraph_break_still_available_via_explicit_config`, already passes
against unchanged code — it pins the pre-existing explicit-override behavior
(FC-2's escape hatch) that must keep working after the default changes.

Post-implementation (after changing `Config.defaults()`'s `paragraph_pause_seconds`
from `2.0` to `0.0`), all three pass — see full-suite run captured under AC-4,
which includes these three tests.

## AC-2

`Config.defaults().formatting.paragraph_pause_seconds == 0.0` is exactly what
`test_default_paragraph_pause_seconds_is_zero` (`tests/test_config.py`) asserts.
Passing run captured under AC-4.

## AC-3

`test_paragraph_break_still_available_via_explicit_config` (`tests/test_formatter.py`)
constructs `FormattingConfig` with `paragraph_pause_seconds=2.0` explicitly and
asserts the paragraph-break still fires (`"One.\n\nTwo"`). It passed even
before implementation (unaffected by the default-value change) and continues
to pass after — see AC-4's full run.

## AC-4

Full unit suite after implementation (`src/stenographer/config.py`'s
`paragraph_pause_seconds` default changed `2.0` → `0.0`):

```
$ .venv/bin/pytest -m "not integration"
tests/test_cli_update.py .........                                       [ 14%]
tests/test_clipboard.py ..........                                       [ 16%]
tests/test_config.py ................................................... [ 28%]
.......................................                                  [ 37%]
tests/test_errors.py .................                                   [ 41%]
tests/test_feedback.py .........                                         [ 44%]
tests/test_formatter.py ....................                             [ 48%]
tests/test_hotkey.py ..................................                  [ 56%]
tests/test_inject.py ....................                                [ 61%]
tests/test_lazy_model.py ........................                        [ 66%]
tests/test_live.py ....................                                  [ 71%]
tests/test_notification.py ..............                                [ 74%]
tests/test_session.py .................................................. [ 86%]
..                                                                       [ 87%]
tests/test_streaming.py ...........                                      [ 89%]
tests/test_transcription.py ....                                         [ 90%]
tests/test_update.py ...................................                 [ 98%]
tests/test_worker_cancel.py .....                                        [100%]

====================== 427 passed, 4 deselected in 21.64s ======================
```

`ruff check .` and `ruff format --check .` both pass ("All checks passed!",
"52 files already formatted").

### Note: two unlisted tests required a matching fix

The feather's Affected Modules list didn't name `tests/test_live.py`, but two
of its tests relied on `Config.defaults()`'s `paragraph_pause_seconds` (via
the shared `_cfg()` helper) to exercise `LiveStreamer`'s paragraph-break
mechanics, not to test the default itself:
`test_paragraph_pause_straddling_trim_emits_one_break` and
`test_prefix_invariant_deltas_reconstruct_final_transcript`. Changing the
default broke them (no more break at their scripted pauses). Since AC-4
requires the full suite to pass, and their intent is unambiguous (they are
about the pause-triggered break mechanism, not the config default), each was
updated to build its `cfg` with an explicit `paragraph_pause_seconds=2.0`
override — the same pattern the spec already prescribes for
`tests/test_formatter.py`'s existing paragraph-break tests. No production
code besides the one `config.py` default line was touched.
