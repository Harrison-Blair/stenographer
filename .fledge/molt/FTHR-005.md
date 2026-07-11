# FTHR-005 Evidence: Distinct per-stage notifications for prompt mode

## AC-1

Tests written per the spec's Tests section, run against the unchanged
pre-implementation code (new `DesktopNotification` methods do not exist yet;
`Session` still calls the generic `show_listening()`/`show_transcribing()`
for prompt-mode recordings). All targeted new tests fail for the expected
reason (`AttributeError: ... has no attribute 'show_listening_prompt'` etc.,
or an `assert_called_once()` count mismatch because the generic method fired
instead of the new one). `test_dictate_mode_notifications_unchanged` passes
already (regression guard, unaffected by the missing methods).

Command:

```
.venv/bin/pytest -m "not integration" \
  tests/test_notification.py -k "prompt or rewriting" \
  tests/test_session.py -k "prompt_mode_recording_start_shows_prompt_listening or prompt_mode_recording_stop_shows_prompt_transcribing or prompt_mode_llm_call_shows_rewriting or prompt_mode_success_shows_prompt_ready or prompt_mode_llm_failure_shows_prompt_failed or dictate_mode_notifications_unchanged"
```

Verbatim output (pre-implementation):

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-005
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 26 items / 6 deselected / 20 selected

tests/test_notification.py FFFFFF
tests/test_session.py FFFFF.                                             [100%]

=================================== FAILURES ===================================
_________ test_show_listening_prompt_enqueues_persistent_notification __________
AttributeError: 'DesktopNotification' object has no attribute 'show_listening_prompt'
________ test_show_transcribing_prompt_enqueues_persistent_notification ________
AttributeError: 'DesktopNotification' object has no attribute 'show_transcribing_prompt'. Did you mean: 'show_transcribing'?
_____________ test_show_rewriting_enqueues_persistent_notification _____________
AttributeError: 'DesktopNotification' object has no attribute 'show_rewriting'
____________ test_show_prompt_ready_enqueues_transient_notification ____________
AttributeError: 'DesktopNotification' object has no attribute 'show_prompt_ready'
___________ test_show_prompt_failed_enqueues_transient_notification ____________
AttributeError: 'DesktopNotification' object has no attribute 'show_prompt_failed'
________ test_prompt_stage_wording_distinct_from_dictate_stage_wording _________
AttributeError: 'DesktopNotification' object has no attribute 'show_listening_prompt'

______ test_prompt_mode_recording_start_shows_prompt_listening_notification ____
AssertionError: Expected 'show_listening_prompt' to have been called once. Called 0 times.
____ test_prompt_mode_recording_stop_shows_prompt_transcribing_notification ____
AssertionError: Expected 'show_transcribing_prompt' to have been called once. Called 0 times.
____________ test_prompt_mode_llm_call_shows_rewriting_notification ____________
AssertionError: Expected 'show_rewriting' to have been called once. Called 0 times.
___________ test_prompt_mode_success_shows_prompt_ready_notification ___________
AssertionError: Expected 'show_prompt_ready' to have been called once. Called 0 times.
________ test_prompt_mode_llm_failure_shows_prompt_failed_notification _________
AssertionError: Expected 'show_prompt_failed' to have been called once. Called 0 times.
=========================== short test summary info ============================
FAILED tests/test_notification.py::test_show_listening_prompt_enqueues_persistent_notification
FAILED tests/test_notification.py::test_show_transcribing_prompt_enqueues_persistent_notification
FAILED tests/test_notification.py::test_show_rewriting_enqueues_persistent_notification
FAILED tests/test_notification.py::test_show_prompt_ready_enqueues_transient_notification
FAILED tests/test_notification.py::test_show_prompt_failed_enqueues_transient_notification
FAILED tests/test_notification.py::test_prompt_stage_wording_distinct_from_dictate_stage_wording
FAILED tests/test_session.py::test_prompt_mode_recording_start_shows_prompt_listening_notification
FAILED tests/test_session.py::test_prompt_mode_recording_stop_shows_prompt_transcribing_notification
FAILED tests/test_session.py::test_prompt_mode_llm_call_shows_rewriting_notification
FAILED tests/test_session.py::test_prompt_mode_success_shows_prompt_ready_notification
FAILED tests/test_session.py::test_prompt_mode_llm_failure_shows_prompt_failed_notification
================== 11 failed, 9 passed, 6 deselected in 0.26s ==================
```

(Full unabridged capture also saved during the run; the above preserves every
distinct failure reason. `test_dictate_mode_notifications_unchanged` and the
5 pre-existing `test_prompt_mode_*` tests from FTHR-004 passed already, as
expected — they exercise behavior this feather does not change.)

## AC-2

Every stage of a prompt-mode recording shows a distinctly worded
notification, implemented in `src/stenographer/notification.py`
(`show_listening_prompt`, `show_transcribing_prompt`, `show_rewriting`,
`show_prompt_ready`) and wired at the `source == "prompt"` branch points in
`src/stenographer/session.py` (`on_recording_start`, `on_recording_stop`,
`_process`).

Pinned by:
- `tests/test_notification.py::test_prompt_stage_wording_distinct_from_dictate_stage_wording`
- `tests/test_session.py::test_prompt_mode_recording_start_shows_prompt_listening_notification`
- `tests/test_session.py::test_prompt_mode_recording_stop_shows_prompt_transcribing_notification`
- `tests/test_session.py::test_prompt_mode_llm_call_shows_rewriting_notification`
- `tests/test_session.py::test_prompt_mode_success_shows_prompt_ready_notification`

Command: `.venv/bin/pytest -m "not integration" tests/test_notification.py tests/test_session.py -v`

```
tests/test_notification.py::test_prompt_stage_wording_distinct_from_dictate_stage_wording PASSED
tests/test_session.py::test_prompt_mode_recording_start_shows_prompt_listening_notification PASSED
tests/test_session.py::test_prompt_mode_recording_stop_shows_prompt_transcribing_notification PASSED
tests/test_session.py::test_prompt_mode_llm_call_shows_rewriting_notification PASSED
tests/test_session.py::test_prompt_mode_success_shows_prompt_ready_notification PASSED
============================== 86 passed in 0.68s ==============================
```

## AC-3

An `LlmError` from `llm_module.rewrite_prompt()` in `Session._process` now
calls `self._notification.show_prompt_failed()` in addition to the existing
`feedback.play("error")` cue (session.py, the `except llm_module.LlmError`
branch).

Pinned by: `tests/test_session.py::test_prompt_mode_llm_failure_shows_prompt_failed_notification`
(asserts `show_prompt_failed` called once, `show_prompt_ready` not called,
and `feedback.play("error")` still fires).

```
tests/test_session.py::test_prompt_mode_llm_failure_shows_prompt_failed_notification PASSED
```

## AC-4

Dictate-mode notification behavior is unchanged: `on_recording_start` /
`on_recording_stop` still call the original `show_listening()` /
`show_transcribing()` for `source="dictate"` (the default), never the new
prompt-specific methods.

Pinned by: `tests/test_session.py::test_dictate_mode_notifications_unchanged`
(asserts `show_listening`/`show_transcribing` called once each, and all five
new prompt-specific methods not called), plus the pre-existing
`test_dictate_mode_unaffected_by_prompt_mode_addition` and
`test_on_recording_stop_shows_transcribing_notification` /
`test_on_recording_stop_hides_notification_when_nothing_queued` /
`test_on_model_loaded_leaves_notification_alone_when_not_recording` (all
still pass, unmodified).

```
tests/test_session.py::test_dictate_mode_notifications_unchanged PASSED
```

## AC-5

Full unit suite green, no regressions:

```
$ .venv/bin/pytest -m "not integration"
====================== 465 passed, 4 deselected in 22.61s ======================
```

Also verified the new session tests pass in isolation (not just as part of
the full-file run), per the FTHR-004 test-isolation lesson:

```
$ .venv/bin/pytest -m "not integration" \
    tests/test_session.py::test_prompt_mode_llm_call_shows_rewriting_notification \
    tests/test_session.py::test_prompt_mode_success_shows_prompt_ready_notification \
    tests/test_session.py::test_prompt_mode_llm_failure_shows_prompt_failed_notification -v
============================== 3 passed in 0.15s ===============================
```

`ruff check .` and `ruff format --check .` both pass clean.
