# FTHR-014 evidence

## AC-1

### Pre-implementation (unchanged, FTHR-013-merged code)

The 2 new test cases plus the notification/gen_cues/cli suite prunings were
written first (adding `test_build_cues_excludes_prompt_variants` and
`test_cli_has_no_prompt_cue_adapter`; removing the 6 prompt-specific tests in
`tests/test_notification.py`, `test_build_cues_includes_pitched_down_prompt_variants`
in `tests/test_gen_cues.py`, and the 2 adapter tests in `tests/test_cli.py`) —
with production code (`feedback.py`, `notification.py`, `cli.py`,
`scripts/gen_cues.py`) still unchanged.

Command:

```
.venv/bin/pytest tests/test_gen_cues.py::test_build_cues_excludes_prompt_variants tests/test_cli.py::test_cli_has_no_prompt_cue_adapter -v
```

Output (verbatim):

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.fledge/burrows/FTHR-014/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-014
configfile: pyproject.toml
plugins: anyio-4.14.2, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 2 items

tests/test_gen_cues.py::test_build_cues_excludes_prompt_variants FAILED  [ 50%]
tests/test_cli.py::test_cli_has_no_prompt_cue_adapter FAILED             [100%]

=================================== FAILURES ===================================
___________________ test_build_cues_excludes_prompt_variants ___________________

    def test_build_cues_excludes_prompt_variants() -> None:
        cues = gen_cues.build_cues(SAMPLE_RATE)
    
        for prompt_name in ("ptt_on_prompt", "ptt_off_prompt", "toggle_on_prompt", "toggle_off_prompt"):
>           assert prompt_name not in cues
E           AssertionError: assert 'ptt_on_prompt' not in {'ptt_on': array(...), 'ptt_off': array(...), 'toggle_on': array(...), 'toggle_off': array(...), ...}

tests/test_gen_cues.py:25: AssertionError
______________________ test_cli_has_no_prompt_cue_adapter ______________________

    def test_cli_has_no_prompt_cue_adapter() -> None:
>       assert hasattr(cli, "_PromptCueAdapter") is False
E       AssertionError: assert True is False
E        +  where True = hasattr(cli, '_PromptCueAdapter')

tests/test_cli.py:19: AssertionError
=========================== short test summary info ============================
FAILED tests/test_gen_cues.py::test_build_cues_excludes_prompt_variants - Ass...
FAILED tests/test_cli.py::test_cli_has_no_prompt_cue_adapter - AssertionError...
============================== 2 failed in 0.72s ===============================
```

Both failed for the expected reason: `CueName`/`build_cues()` still contained
the prompt cue names, and `cli._PromptCueAdapter` still existed.

A full pre-implementation run of the unit suite (`.venv/bin/pytest -m "not
integration" -q`) at this same point showed exactly these 2 failures and
451 passed, confirming no other test was silently broken by the test-file
edits alone.

### Post-implementation (after removal)

Command:

```
.venv/bin/pytest tests/test_gen_cues.py::test_build_cues_excludes_prompt_variants tests/test_cli.py::test_cli_has_no_prompt_cue_adapter -v
```

Output (verbatim):

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/stenographer/.fledge/burrows/FTHR-014/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/stenographer/.fledge/burrows/FTHR-014
configfile: pyproject.toml
plugins: anyio-4.14.2, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 2 items

tests/test_gen_cues.py::test_build_cues_excludes_prompt_variants PASSED  [ 50%]
tests/test_cli.py::test_cli_has_no_prompt_cue_adapter PASSED             [100%]

============================== 2 passed in 0.70s ===============================
```

Full unit suite also passes — see AC-6 below (452 passed, 4 deselected).

## AC-2

`CueName` contains exactly the 11 non-prompt names.

Command:

```
.venv/bin/python -c "
import typing
from stenographer.audio.feedback import CueName
print(sorted(typing.get_args(CueName)))
"
```

Output:

```
['cancel', 'discard', 'error', 'model_loading', 'model_ready', 'ptt_off', 'ptt_on', 'segment', 'toggle_off', 'toggle_on', 'transcribe_done']
```

11 entries, no `*_prompt` names — matches AC-2's required set exactly.

## AC-3

`Notification` (in `notification.py`, class `DesktopNotification`) has none
of the 5 removed methods.

Command:

```
.venv/bin/python -c "
from stenographer.notification import DesktopNotification
for m in ('show_listening_prompt','show_transcribing_prompt','show_rewriting','show_prompt_ready','show_prompt_failed'):
    print(m, hasattr(DesktopNotification, m))
"
```

Output:

```
show_listening_prompt False
show_transcribing_prompt False
show_rewriting False
show_prompt_ready False
show_prompt_failed False
```

## AC-4

`cli._PromptCueAdapter` and `cli._PROMPT_CUE_REMAP` do not exist.

Command:

```
.venv/bin/python -c "
import stenographer.cli as cli
print('has adapter', hasattr(cli, '_PromptCueAdapter'))
print('has remap', hasattr(cli, '_PROMPT_CUE_REMAP'))
"
```

Output:

```
has adapter False
has remap False
```

## AC-5

`build_cues()` output has no `*_prompt` keys, and the 4 `*_prompt.wav`
assets no longer exist.

Commands:

```
.venv/bin/pytest tests/test_gen_cues.py::test_build_cues_excludes_prompt_variants -v
.venv/bin/python scripts/gen_cues.py
ls src/stenographer/assets/sounds/
git status --short
```

Output:

```
tests/test_gen_cues.py::test_build_cues_excludes_prompt_variants PASSED  [100%]

cancel.wav
discard.wav
error.wav
model_loading.wav
model_ready.wav
ptt_off.wav
ptt_on.wav
segment.wav
toggle_off.wav
toggle_on.wav
transcribe_done.wav

 M scripts/gen_cues.py
D  src/stenographer/assets/sounds/ptt_off_prompt.wav
D  src/stenographer/assets/sounds/ptt_on_prompt.wav
D  src/stenographer/assets/sounds/toggle_off_prompt.wav
D  src/stenographer/assets/sounds/toggle_on_prompt.wav
 M src/stenographer/audio/feedback.py
 M src/stenographer/cli.py
 M src/stenographer/notification.py
 M tests/test_cli.py
 M tests/test_config.py
 M tests/test_gen_cues.py
 M tests/test_notification.py
```

The 4 assets are `git rm`-tracked deletions (staged `D`); re-running
`scripts/gen_cues.py` regenerates the remaining 11 `.wav` files byte-identical
(no further diff appears against the tracked copies) and writes no
`*_prompt.wav` files. The listing directory contains exactly the 11
non-prompt names.

## AC-6

Full repo suite + lint, both feathers combined.

Commands:

```
.venv/bin/pytest -m "not integration" -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Output:

```
........................................................................ [ 15%]
........................................................................ [ 31%]
........................................................................ [ 47%]
........................................................................ [ 63%]
........................................................................ [ 79%]
........................................................................ [ 95%]
....................                                                     [100%]
452 passed, 4 deselected in 14.26s

All checks passed!

55 files already formatted
```

Note: implementing this feather also required removing
`tests/test_config.py::test_prompt_cue_names_accepted_as_overrides` — not
listed in the feather's Tests section, but it asserted that the 4 removed
prompt cue names were still valid `[feedback.cues]` config overrides, which
directly contradicts AC-2 (`CueName` now has only 11 entries; `config.py`'s
`CUE_NAMES`/cue validation derives from it at runtime per the Approach
section). It is a direct orphan of the CueName shrink specified by the
feather, not a new/expanded scope — removing it was necessary for this
full-suite green run. `test_unknown_cue_name_still_rejected` (unchanged)
continues to cover the "unknown cue name" rejection path generically, now
also exercising the (former) prompt names implicitly.

## AC-7

Full-repo grep for `llm|prompt`, excluding known non-feature hits and
generic English words.

Command:

```
grep -riE "llm|prompt" src/ tests/ scripts/
```

Output:

```
src/stenographer/_parser.py:    update.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
src/stenographer/update.py:interactive prompt and the daemon stop / start steps.
src/stenographer/live.py:        """Wake the driver promptly after the abort event was set."""
tests/test_gen_cues.py:def test_build_cues_excludes_prompt_variants() -> None:
tests/test_gen_cues.py:    for prompt_name in ("ptt_on_prompt", "ptt_off_prompt", "toggle_on_prompt", "toggle_off_prompt"):
tests/test_gen_cues.py:        assert prompt_name not in cues
tests/test_cli_update.py:def test_cli_update_yes_skips_prompt(
tests/test_cli_update.py:def test_cli_update_interactive_prints_changelog_before_prompt(
tests/test_cli_update.py:    # Changelog must appear before the prompt and the cancellation line.
tests/test_cli_update.py:    # install (per the chosen design: before the prompt only).
tests/test_session.py:def test_session_has_no_attach_prompt_listener() -> None:
tests/test_session.py:    assert not hasattr(session, "attach_prompt_listener")
tests/test_session.py:    session.on_recording_start(source="prompt")
tests/test_cli.py:def test_cli_has_no_prompt_cue_adapter() -> None:
tests/test_cli.py:    assert hasattr(cli, "_PromptCueAdapter") is False
tests/test_config.py:def test_defaults_have_no_prompt_binding_field() -> None:
tests/test_config.py:    assert not hasattr(Config.defaults().hotkey, "prompt_binding")
tests/test_config.py:def test_defaults_have_no_llm_field() -> None:
tests/test_config.py:    assert not hasattr(Config.defaults(), "llm")
tests/test_config.py:def test_legacy_llm_and_prompt_binding_keys_ignored(tmp_path: pathlib.Path) -> None:
tests/test_config.py:            hotkey.prompt_binding = "KEY_RIGHTALT"
tests/test_config.py:            [stenographer.llm]
tests/test_config.py:def test_format_default_toml_has_no_llm_or_prompt_binding() -> None:
tests/test_config.py:    assert "llm." not in text
tests/test_config.py:    assert "prompt_binding" not in text
```

Analysis, hit by hit:
- `_parser.py` "confirmation prompt" (the `update --yes` flag), `update.py`
  "interactive prompt" (the update self-update confirmation), `live.py`
  "promptly" (an adverb) — the feather's named exclusions; pre-existing,
  unrelated to LLM-rewrite/prompt-mode.
- `tests/test_gen_cues.py`, `tests/test_cli.py`, `tests/test_config.py` hits
  are all *this feather's own* (and FTHR-013's already-merged) tests
  asserting the **absence** of prompt-mode surface (`*_prompt` cue names,
  `_PromptCueAdapter`, `prompt_binding`, `llm` config) — not references to a
  live feature.
- `tests/test_cli_update.py` "skips prompt" / "before the prompt" refer to
  the *update command's* interactive y/n confirmation prompt (same feature
  as `update.py`/`_parser.py` above), not LLM prompt-crafting.
- `tests/test_session.py::test_session_has_no_attach_prompt_listener`
  asserts absence of prompt-mode wiring (FTHR-013, already merged).
  `session.on_recording_start(source="prompt")` (line ~1005, in
  `test_discard_does_not_abort_stale_streamer_final_decode`) is a
  leftover string used only as an arbitrary source label distinct from
  `"dictate"`, to exercise `Session`'s source-mismatch guard — `source` is
  typed `Literal["dictate"]` at every call site in `session.py` (FTHR-013
  already removed the `"prompt"` literal member), so this is inert test
  data, not a call into any prompt-mode/LLM code path. `session.py` and
  `test_session.py` are outside this feather's Affected Modules and Tests
  sections, and the string doesn't invoke any removed functionality, so it
  was left untouched per scope discipline; flagged here for the skua's
  judgment since it is a literal occurrence of the word "prompt" as a
  feature-shaped identifier value rather than a generic English word.

No LLM-rewrite-feature (prompt-mode routing, prompt-crafting, cue
remapping, prompt notifications) references remain anywhere in `src/`,
`tests/`, or `scripts/`.
