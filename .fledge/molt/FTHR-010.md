# FTHR-010 evidence

## AC-1

All five tests were added to `tests/test_config.py` first, then run against
unchanged `config.py` (before either fix landed).

Command:
```
.venv/bin/pytest -q tests/test_config.py -k "test_prompt_binding_overlap_with_cancel_binding_rejected or test_prompt_binding_overlap_with_explicit_cancel_binding_rejected or test_prompt_cue_names_accepted_as_overrides or test_unknown_cue_name_still_rejected or test_cue_names_matches_cue_name_literal_args"
```

Captured output (pre-fix):
```
F                                                                        [100%]
=================================== FAILURES ===================================
___________ test_prompt_binding_overlap_with_cancel_binding_rejected ___________

tmp_path = PosixPath('/tmp/pytest-of-penguin/pytest-4/test_prompt_binding_overlap_wi0')

    def test_prompt_binding_overlap_with_cancel_binding_rejected(tmp_path: pathlib.Path) -> None:
        p = tmp_path / "config.toml"
        p.write_text('[stenographer]\nhotkey.prompt_binding = "KEY_ESC"\n')
>       with pytest.raises(ConfigError, match=r"hotkey.prompt_binding"):
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       Failed: DID NOT RAISE ConfigError

tests/test_config.py:322: Failed
=========================== short test summary info ============================
FAILED tests/test_config.py::test_prompt_binding_overlap_with_cancel_binding_rejected
1 failed, 105 deselected in 0.03s
```

```
    def test_prompt_binding_overlap_with_explicit_cancel_binding_rejected(
        tmp_path: pathlib.Path,
    ) -> None:
        p = tmp_path / "config.toml"
        p.write_text(
            '[stenographer]\nhotkey.cancel_binding = "KEY_F9"\nhotkey.prompt_binding = "KEY_F9"\n'
        )
>       with pytest.raises(ConfigError, match=r"hotkey.prompt_binding"):
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       Failed: DID NOT RAISE ConfigError

tests/test_config.py:333: Failed
```

```
_________________ test_prompt_cue_names_accepted_as_overrides __________________

tmp_path = PosixPath('/tmp/pytest-of-penguin/pytest-3/test_prompt_cue_names_accepted0')

    def test_prompt_cue_names_accepted_as_overrides(tmp_path: pathlib.Path) -> None:
        for name in ("ptt_on_prompt", "ptt_off_prompt", "toggle_on_prompt", "toggle_off_prompt"):
            cue = tmp_path / f"{name}.wav"
            cue.write_text("data")
            p = tmp_path / "config.toml"
            p.write_text(f'[stenographer.feedback.cues]\n{name} = "{cue}"\n')
>           assert Config.load(p).feedback.cues[name] == str(cue)
                   ^^^^^^^^^^^^^^
...
E               stenographer.config.ConfigError: /tmp/.../config.toml: feedback.cues.ptt_on_prompt: unknown cue name; must be one of ptt_on, ptt_off, toggle_on, toggle_off, cancel, discard, error, segment, transcribe_done, model_loading, model_ready

src/stenographer/config.py:449: ConfigError
```

```
_________________ test_cue_names_matches_cue_name_literal_args _________________

    def test_cue_names_matches_cue_name_literal_args() -> None:
        import typing

        from stenographer.audio.feedback import CueName

>       assert set(CUE_NAMES) == set(typing.get_args(CueName))
E       AssertionError: assert {'cancel', 'd...ptt_off', ...} == {'cancel', 'd...ptt_off', ...}
E
E         Extra items in the right set:
E         'toggle_off_prompt'
E         'toggle_on_prompt'
E         'ptt_off_prompt'
E         'ptt_on_prompt'
E         Use -v to get more diff

tests/test_config.py:671: AssertionError
=========================== short test summary info ============================
FAILED tests/test_config.py::test_prompt_binding_overlap_with_cancel_binding_rejected
FAILED tests/test_config.py::test_prompt_binding_overlap_with_explicit_cancel_binding_rejected
FAILED tests/test_config.py::test_prompt_cue_names_accepted_as_overrides - st...
FAILED tests/test_config.py::test_cue_names_matches_cue_name_literal_args - A...
4 failed, 1 passed, 101 deselected in 0.09s
```

The 5th test, `test_unknown_cue_name_still_rejected`, is the pre-existing-passing
regression guard named in the spec — confirmed passing pre-fix:
```
.venv/bin/pytest -q tests/test_config.py -k "test_unknown_cue_name_still_rejected"
.                                                                        [100%]
1 passed, 105 deselected in 0.02s
```

Post-fix (both fixes implemented in `config.py`), all five pass:
```
.venv/bin/pytest -q tests/test_config.py -k "test_prompt_binding_overlap_with_cancel_binding_rejected or test_prompt_binding_overlap_with_explicit_cancel_binding_rejected or test_prompt_cue_names_accepted_as_overrides or test_unknown_cue_name_still_rejected or test_cue_names_matches_cue_name_literal_args" -v
...
collected 106 items / 101 deselected / 5 selected

tests/test_config.py .....                                               [100%]

====================== 5 passed, 101 deselected in 0.03s =======================
```

## AC-2

`_build_hotkey` in `src/stenographer/config.py` now checks `prompt_binding`'s
keys against the *resolved* `cancel_binding` (after its own defaults-vs-explicit
logic has already run/possibly reset it to `""`), raising `ConfigError` on
overlap in both the default-cancel-binding case
(`test_prompt_binding_overlap_with_cancel_binding_rejected`, prompt_binding =
`"KEY_ESC"` = the `cancel_binding` default) and the explicit-cancel-binding case
(`test_prompt_binding_overlap_with_explicit_cancel_binding_rejected`, both set
to `"KEY_F9"`). See AC-1 evidence for pre/post-fix runs of both tests.

## AC-3

```
CUE_NAMES: tuple[str, ...] = typing.get_args(CueName)
```
with `CueName` imported from `stenographer.audio.feedback`. Verified directly
by `test_cue_names_matches_cue_name_literal_args`
(`set(CUE_NAMES) == set(typing.get_args(CueName))`) — see AC-1 for pre/post-fix
output. No circular import: `stenographer/audio/feedback.py` imports only
`logging`, `pathlib`, `subprocess`, `typing` — it does not import `config.py`.
Confirmed by `.venv/bin/python -c "import stenographer.config"` succeeding.

## AC-4

`test_prompt_cue_names_accepted_as_overrides` confirms all four prompt cue
names (`ptt_on_prompt`, `ptt_off_prompt`, `toggle_on_prompt`,
`toggle_off_prompt`) are now accepted as `feedback.cues.*` overrides (FC-3).
`test_unknown_cue_name_still_rejected` confirms an unrecognized cue name
(`bogus_cue_name`) is still rejected with `ConfigError` (FC-4) — passing both
before and after the change, per AC-1.

## AC-5

Full unit suite, post-fix:
```
.venv/bin/pytest -m "not integration" -q
........................................................................ [ 14%]
........................................................................ [ 29%]
........................................................................ [ 44%]
........................................................................ [ 58%]
........................................................................ [ 73%]
........................................................................ [ 88%]
..........................................................               [100%]
490 passed, 4 deselected in 20.31s
```

Lint/format, post-fix:
```
.venv/bin/ruff check .
All checks passed!

.venv/bin/ruff format --check .
57 files already formatted
```
