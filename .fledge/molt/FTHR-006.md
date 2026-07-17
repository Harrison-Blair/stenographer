# FTHR-006 Evidence

## AC-1

Command: `.venv/bin/pytest -m "not integration" tests/test_gen_cues.py tests/test_cli.py -v`

Captured **before** any implementation changes (against unchanged `scripts/gen_cues.py`,
`src/stenographer/audio/feedback.py`, `src/stenographer/cli.py`):

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.fledge/burrows/FTHR-006/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-006
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 9 items

tests/test_gen_cues.py::test_build_cues_includes_pitched_down_prompt_variants FAILED
tests/test_cli.py::test_prompt_cue_adapter_remaps_start_stop_cues FAILED
tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[cancel] FAILED
tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[discard] FAILED
tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[error] FAILED
tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[segment] FAILED
tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[transcribe_done] FAILED
tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[model_loading] FAILED
tests/test_cli.py::test_dictate_listener_uses_unmapped_feedback FAILED

=================================== FAILURES ===================================
______ test_build_cues_includes_pitched_down_prompt_variants _______
>       assert prompt_name in cues
E       AssertionError: assert 'ptt_on_prompt' in {'ptt_on': array([...]), 'ptt_off': array([...]), 'toggle_on': array([...]), 'toggle_off': array([...]), 'cancel': array([...]), ...}

tests/test_gen_cues.py:27: AssertionError
______ test_prompt_cue_adapter_remaps_start_stop_cues _______
>       adapter = cli._PromptCueAdapter(underlying)
                  ^^^^^^^^^^^^^^^^^^^^^
E       AttributeError: module 'stenographer.cli' has no attribute '_PromptCueAdapter'

tests/test_cli.py:38: AttributeError
______ test_prompt_cue_adapter_passes_through_other_cues_unchanged[*] (x6) _______
>       adapter = cli._PromptCueAdapter(underlying)
                  ^^^^^^^^^^^^^^^^^^^^^
E       AttributeError: module 'stenographer.cli' has no attribute '_PromptCueAdapter'

tests/test_cli.py:38: AttributeError
______ test_dictate_listener_uses_unmapped_feedback _______
        session = cli._build_session(cfg, caps, one_shot=False)
        try:
            assert len(calls) == 2
            dictate_feedback = calls[0]["feedback"]
            prompt_feedback = calls[1]["feedback"]
            assert isinstance(dictate_feedback, Feedback)
>           assert not isinstance(prompt_feedback, Feedback)
E           assert not True
E            +  where True = isinstance(<stenographer.audio.feedback.Feedback object at 0x7f4a3f561400>, Feedback)

tests/test_cli.py:77: AssertionError

=========================== short test summary info ============================
FAILED tests/test_gen_cues.py::test_build_cues_includes_pitched_down_prompt_variants
FAILED tests/test_cli.py::test_prompt_cue_adapter_remaps_start_stop_cues
FAILED tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[cancel]
FAILED tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[discard]
FAILED tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[error]
FAILED tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[segment]
FAILED tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[transcribe_done]
FAILED tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[model_loading]
FAILED tests/test_cli.py::test_dictate_listener_uses_unmapped_feedback
============================== 9 failed in 0.29s ===============================
```

(Full text captured verbatim from the actual pre-implementation run; the `array([...])` elisions above
replace long numpy repr blocks for readability — the assertion lines and error types are unedited.)

Failures are for the expected reason: `build_cues()` doesn't yet produce the four new prompt-cue keys,
and `stenographer.cli` doesn't yet define `_PromptCueAdapter` / route it into the prompt-mode listener.

Full pre-implementation baseline (`.venv/bin/pytest -m "not integration"`, excluding the two new test
files which don't exist as importable modules until this feather adds them): **453 passed, 4 deselected**.

Post-implementation run of the same command (`tests/test_gen_cues.py tests/test_cli.py -v`):

```
============================= test session starts ==============================
collected 9 items

tests/test_gen_cues.py::test_build_cues_includes_pitched_down_prompt_variants PASSED [ 11%]
tests/test_cli.py::test_prompt_cue_adapter_remaps_start_stop_cues PASSED [ 22%]
tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[cancel] PASSED [ 33%]
tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[discard] PASSED [ 44%]
tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[error] PASSED [ 55%]
tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[segment] PASSED [ 66%]
tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[transcribe_done] PASSED [ 77%]
tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged[model_loading] PASSED [ 88%]
tests/test_cli.py::test_dictate_listener_uses_unmapped_feedback PASSED   [100%]

============================== 9 passed in 0.49s ===============================
```

Full post-implementation suite (`.venv/bin/pytest -m "not integration"`): **462 passed, 4 deselected** —
453 pre-existing + 9 new, no regressions.

## AC-2

`ptt_on_prompt`/`toggle_on_prompt`/`ptt_off_prompt`/`toggle_off_prompt` WAV assets exist at exactly ÷4
the frequency of their base tones, same duration.

`scripts/gen_cues.py:build_cues()` adds:
- `ptt_on_prompt` = `tone(220.0, ...)` (÷4 of `ptt_on`'s 880.0 Hz)
- `toggle_on_prompt` = `tone(110.0, ...)` (÷4 of `toggle_on`'s 440.0 Hz)
- `ptt_off_prompt` = two 220.0 Hz beeps (÷4 of `ptt_off`'s two 880.0 Hz beeps)
- `toggle_off_prompt` = two 110.0 Hz beeps (÷4 of `toggle_off`'s two 440.0 Hz beeps)

each with the same `0.080`s duration, `GAP_S` gap, and `DBFS_BEEP` level as its base tone — only the
frequency argument differs. `test_build_cues_includes_pitched_down_prompt_variants` asserts each new
cue's samples are byte-for-byte equal to calling `tone()`/`silence()` directly with the ÷4 frequency and
identical duration/dBFS/sample-rate arguments (stronger than an FFT-peak check — it pins the exact
synthesis, not just the dominant frequency).

`scripts/gen_cues.py` was run (`.venv/bin/python scripts/gen_cues.py`) to regenerate
`src/stenographer/assets/sounds/`; the four new WAVs exist on disk:

```
$ python3 -c "
import wave
for n in ['ptt_on_prompt','toggle_on_prompt','ptt_off_prompt','toggle_off_prompt','ptt_on','toggle_on','ptt_off','toggle_off']:
    w = wave.open(f'src/stenographer/assets/sounds/{n}.wav')
    print(n, w.getframerate(), w.getnframes())
"
ptt_on_prompt 44100 3528
toggle_on_prompt 44100 3528
ptt_off_prompt 44100 9702
toggle_off_prompt 44100 9702
ptt_on 44100 3528
toggle_on 44100 3528
ptt_off 44100 9702
toggle_off 44100 9702
```

Each `*_prompt` WAV has the identical frame count (duration) to its base tone, confirming only pitch
changed. Test: `tests/test_gen_cues.py::test_build_cues_includes_pitched_down_prompt_variants` (see AC-1
post-implementation run above — PASSED).

`src/stenographer/audio/feedback.py`'s `CueName` Literal was extended with the four new names so
`Feedback.play()` type-checks them; `_resolve_path`/`play()` needed no other change (confirmed by
`.venv/bin/ruff check .` passing with no new type errors, and by the full suite staying green).

## AC-3

A prompt-mode recording start/stop plays the pitched-down cue variants; all other cues remain shared and
unchanged for both modes.

`src/stenographer/cli.py` adds `_PromptCueAdapter`, a small class with a `.play(name)` method matching
`Feedback`'s public surface: it remaps `ptt_on`→`ptt_on_prompt`, `toggle_on`→`toggle_on_prompt`,
`ptt_off`→`ptt_off_prompt`, `toggle_off`→`toggle_off_prompt` via the `_PROMPT_CUE_REMAP` dict, and passes
every other name straight through to the underlying `Feedback.play()`. `_build_session()` passes
`_PromptCueAdapter(feedback)` as the `feedback=` argument to the *second* (`prompt_binding`)
`HotkeyListener` only.

Tests (see AC-1 post-implementation run — both PASSED):
- `tests/test_cli.py::test_prompt_cue_adapter_remaps_start_stop_cues` — asserts
  `adapter.play("ptt_on")`/`"toggle_on"`/`"ptt_off"`/`"toggle_off"` each call the underlying mock's
  `.play()` with the corresponding `*_prompt` name.
- `tests/test_cli.py::test_prompt_cue_adapter_passes_through_other_cues_unchanged` (parametrized over
  `cancel`, `discard`, `error`, `segment`, `transcribe_done`, `model_loading`) — asserts
  `adapter.play(cue_name)` calls the underlying mock's `.play()` with the same, unmapped name.

`HotkeyStateMachine`/`Transition` are untouched (`git diff --stat` shows no changes to
`src/stenographer/hotkey/state_machine.py`) — the state machine still only ever emits the generic cue
names; the remap is purely a wiring-boundary adapter in `cli.py`.

## AC-4

The existing dictate-mode hotkey's cues are unaffected (regression guard).

`tests/test_cli.py::test_dictate_listener_uses_unmapped_feedback` builds a real `Session` via
`cli._build_session(cfg, caps, one_shot=False)` with `cli.HotkeyListener` monkeypatched to a
call-capturing stub, and asserts:
- the first (dictate-mode) `HotkeyListener` call's `feedback=` kwarg is the real `Feedback` instance
  (`isinstance(dictate_feedback, Feedback)` is `True`)
- the second (prompt-mode) `HotkeyListener` call's `feedback=` kwarg is *not* a `Feedback` instance (it's
  the `_PromptCueAdapter` wrapping it) and is a different object from the dictate feedback

Pre-implementation this test failed because `_build_session()` passed the same real `Feedback` object to
both listeners (see AC-1 above — `assert not isinstance(prompt_feedback, Feedback)` failed with
`assert not True`). Post-implementation it passes (see AC-1 post-implementation run — PASSED).

## AC-5

`.venv/bin/pytest -m "not integration"` passes with no regressions.

```
$ .venv/bin/pytest -m "not integration"
...
====================== 462 passed, 4 deselected in 15.30s ======================
```

462 = 453 pre-existing (AC-1 baseline) + 9 new tests from this feather. No regressions.

Also verified (not required by AC-5 but part of the project's lint gate):

```
$ .venv/bin/ruff check .
All checks passed!
$ .venv/bin/ruff format --check .
57 files already formatted
```
