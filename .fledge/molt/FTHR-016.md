# FTHR-016 evidence

Branch selection: `.fledge/molt/FTHR-015.md` records
`RESULT: 3/3 PASS — build universal chord (PLM-009 FC-1/FC-2)` under its AC-2.
**Branch 1 built; Branch 2 (`output.paste_chord` config + chord parser) NOT built**,
per the plumage's pre-committed binary rule.

## AC-1

The tests listed in the feather's Tests section (Branch 1 only), observed FAILING
against unchanged `src/`, then passing after implementation.

### Pre-implementation run (verbatim, captured at the time)

`src/` confirmed unmodified at capture time (`git diff --stat -- src/` empty):

```
$ git diff --stat -- src/
=== src/ is UNCHANGED (no diff above) ===
$ .venv/bin/pytest -m "not integration" \
    tests/test_clipboard.py::test_copy_populates_primary_selection \
    tests/test_inject.py::test_paste_fires_shift_insert \
    tests/test_capabilities.py::test_has_paste_trigger \
    tests/test_session.py::test_paste_gated_on_has_paste_trigger
```

Failure reasons — each is the expected one:

```
E           AssertionError: assert 1 == 2
E            +  where 1 = <MagicMock name='run' id='139867522085760'>.call_count
E           AssertionError: assert ['wtype', '-M... '-m', 'ctrl'] == ['wtype', '-M...t', '-m', ...]
E
E             At index 2 diff: 'ctrl' != 'shift'
E             Right contains one more item: 'shift'
E             Use -v to get more diff
E       AssertionError: assert 'has_paste_trigger' in {'has_asr_model', 'has_input_group', 'has_mic', 'has_paplay', 'has_pw_play', 'has_wl_copy', ...}
E       AssertionError: assert 'has_paste_trigger' in {'has_asr_model', 'has_input_group', 'has_mic', 'has_paplay', 'has_pw_play', 'has_wl_copy', ...}
E           AssertionError: Expected 'paste' to not have been called. Called 1 times.
E           Calls: [call()].
=========================== short test summary info ============================
FAILED tests/test_clipboard.py::test_copy_populates_primary_selection - Asser...
FAILED tests/test_inject.py::test_paste_fires_shift_insert - AssertionError: ...
FAILED tests/test_capabilities.py::test_has_paste_trigger[True] - AssertionEr...
FAILED tests/test_capabilities.py::test_has_paste_trigger[False] - AssertionE...
FAILED tests/test_session.py::test_paste_gated_on_has_paste_trigger - Asserti...
============================== 5 failed in 0.58s ===============================
```

Mapping of each failure to the behaviour it pins:

- `test_copy_populates_primary_selection` — only 1 `wl-copy` call; primary
  selection never populated (`1 == 2`).
- `test_paste_fires_shift_insert` — chord is still `ctrl`+`v`.
- `test_has_paste_trigger[True]`/`[False]` — dataclass field is still `has_wtype`.
- `test_paste_gated_on_has_paste_trigger` — the gate still reads `has_wtype`, so
  setting `has_paste_trigger=False` does not suppress the paste.

### Post-implementation run

```
$ .venv/bin/pytest -m "not integration" \
    tests/test_clipboard.py::test_copy_populates_primary_selection \
    tests/test_inject.py::test_paste_fires_shift_insert \
    tests/test_capabilities.py::test_has_paste_trigger \
    tests/test_session.py::test_paste_gated_on_has_paste_trigger
tests/test_clipboard.py .                                                [ 20%]
tests/test_inject.py .                                                   [ 40%]
tests/test_capabilities.py ..                                            [ 80%]
tests/test_session.py .                                                  [100%]

============================== 5 passed in 0.53s ===============================
```

### Mutation check

Per the repo's test-verification rule, a test only counts if it fails when the
behaviour breaks. Both new behavioural tests were re-run against deliberately
reverted source (primary-selection call removed; chord reverted to `ctrl`+`v`):

```
--- behavior reverted; new tests MUST fail ---
FAILED tests/test_clipboard.py::test_copy_populates_primary_selection - Asser...
FAILED tests/test_inject.py::test_paste_fires_shift_insert - AssertionError: ...
============================== 2 failed in 0.02s ===============================
--- restored ---
====================== 474 passed, 4 deselected in 15.59s ======================
```

## AC-2

FTHR-015's `RESULT:` was 3/3 PASS, so this criterion is the live one.

`ClipboardManager.copy()` (`src/stenographer/output/clipboard.py`) now loops over
`(["wl-copy"], ["wl-copy", "--primary"])`, piping the same `payload` to both, and
returns `True` only if both succeed. Pinned by
`test_copy_populates_primary_selection`, which asserts both argv forms and that
`input` is identical (`b"hello"`) for each.

`Injector.paste()` (`src/stenographer/output/inject.py`) now runs
`["wtype", "-M", "shift", "-k", "Insert", "-m", "shift"]`. Pinned by
`test_paste_fires_shift_insert`, which additionally asserts `"ctrl"` and `"v"`
are absent from the argv. `paste() -> bool` and its no-argument call contract are
unchanged — the FTHR-017 seam is intact.

## AC-3

Vacuous — its condition ("If FTHR-015's `RESULT:` was a fallback") is false.
Branch 2 was NOT built, deliberately. Verified absent:

```
$ grep -rn "paste_chord" src/ tests/
(no matches)
```

No `output.paste_chord` field, no chord parser, no Branch-2 tests
(`test_paste_uses_configured_chord`, `test_paste_chord_default_and_override`).
`config.py` is untouched by this feather.

## AC-4

`Capabilities.has_paste_trigger` replaces `has_wtype` (field + `probe()`), and
every reader was updated — the rename is total, so no `has_wtype` remains in
`src/`:

```
$ grep -rn "has_paste_trigger" src/stenographer/capabilities.py src/stenographer/session.py
src/stenographer/capabilities.py:20:    has_paste_trigger: bool
src/stenographer/capabilities.py:30:        has_paste_trigger = shutil.which("wtype") is not None
src/stenographer/capabilities.py:66:            has_paste_trigger=has_paste_trigger,
src/stenographer/session.py:723:            if self._caps.has_paste_trigger:
src/stenographer/session.py:729:            if self._caps.has_paste_trigger and not injected_text.strip():
src/stenographer/session.py:831:        if self._caps.has_paste_trigger:
```

`session.py:831` — the paste-gate the feather names — reads `has_paste_trigger`,
pinned behaviourally by `test_paste_gated_on_has_paste_trigger` (with the field
`False`, `injector.paste()` is not called, while the clipboard is still populated
as the fallback). `session.py:723` and `:729`, plus `cli.py:207`/`:717`, are the
same field's other readers and were renamed with it (a dataclass field rename is
all-or-nothing; leaving one behind is an `AttributeError`).

## AC-5

`probe()` remains presence-only: line 30 above is `shutil.which("wtype") is not
None` and nothing more — no delivery-verification, no test paste, no round-trip
probe. `test_has_paste_trigger` pins this by patching
`stenographer.capabilities.shutil.which` and asserting the capability tracks that
patched result for both `True` and `False` — a probe that verified delivery could
not pass under a patched `which` alone.

## AC-6

No regressions in `output/` or `session.py`. One pre-existing test,
`test_clipboard.py::test_copy_success_returns_true_and_pipes_input`, asserted
`run.assert_called_once()` — the single-`wl-copy` contract this feather
deliberately supersedes. Its call-count assertion was narrowed to
`run.call_args_list[0]`; every argv/kwarg assertion it made is retained, and the
second call it no longer counts is asserted in full by
`test_copy_populates_primary_selection`. No test was weakened in a way that
unpins behaviour, and none was skipped or deleted.

Test renames that follow the field rename (mechanical, no assertion changes):
`test_process_injector_skipped_when_wtype_unavailable` →
`test_process_injector_skipped_when_paste_trigger_unavailable`;
`has_wtype=` construction kwargs in `test_capabilities.py`, `test_cli.py`,
`test_session.py`.

## AC-7

Full unit suite, no regressions (473 passed pre-change baseline + the 5 new
cases, less the 4 deselected integration tests):

```
$ .venv/bin/pytest -m "not integration"
====================== 474 passed, 4 deselected in 15.68s ======================

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
55 files already formatted
```

Note: run from a worktree-local `.venv` created inside
`.fledge/burrows/FTHR-016` (`python3 -m venv .venv && .venv/bin/pip install -e
".[dev,build]"`), not the main checkout's venv — that one is an editable install
pointing at the main checkout's `src/` and would have tested the wrong code.

## Out-of-scope finding carried forward from FTHR-015

Not re-verified by this feather; recorded so it is not lost. FTHR-015 found that
`wtype` cannot deliver to XWayland clients at all (virtual-keyboard protocol does
not surface there) — no chord, including this one, will work in Discord/Spotify.
The 3/3 PASS that selected Branch 1 covers native-Wayland clients only. XWayland
coverage would require ydotool and is an open user decision, outside this feather.

