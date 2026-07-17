# FTHR-020 — Preserve full transcript on clipboard when delta delivery fails

Worktree: `.fledge/burrows/FTHR-020` on `feather/FTHR-020-preserve-full-transcript` (cut from `dev`).
Venv: worktree-local, verified importing the worktree's own source before any test was run:

```
$ .venv/bin/python -c "import stenographer; print(stenographer.__file__)"
/home/penguin/source/stenographer/.fledge/burrows/FTHR-020/src/stenographer/__init__.py
```

## AC-1

The tests listed in the spec were observed failing before implementation and pass after.

### Pre-implementation (tests written, source UNCHANGED)

```
$ .venv/bin/pytest tests/test_live.py -m "not integration" \
    -k "delivery_failure or full_transcript_after_delivery_failure"

__________ test_finish_copies_full_transcript_after_delivery_failure ___________
        typed = streamer._finish(_speech(2.0))

        # The delivered text still stops at the prefix (that is FTHR-017's latch,
        # and it is correct) ...
        assert typed == "One"
        assert injector.pasted == ["One"]
        # ... but the clipboard now holds everything the user actually said, so
        # the undelivered remainder is recoverable with a manual paste.
>       assert clipboard.copy.call_args_list[-1] == call("One two three ")
E       AssertionError: assert call('One') == call('One two three ')
E
E         Use -v to get more diff

tests/test_live.py:696: AssertionError
------------------------------ Captured log call -------------------------------
WARNING  stenographer.live:live.py:259 live: delta delivery failed; output stopped at 3 chars to keep
delivered text a prefix of the transcript
=========================== short test summary info ============================
FAILED tests/test_live.py::test_finish_copies_full_transcript_after_delivery_failure
================== 1 failed, 1 passed, 28 deselected in 0.18s ==================
```

The failure is the exact reason the spec predicts: the clipboard's last payload is the
**delivered prefix** `'One'` rather than the full transcript `'One two three '`. The captured
warning confirms the latch engaged (`output stopped at 3 chars`), i.e. the test exercised the
real failure path and not some other route to a mismatch.

**Honest note on the `1 passed`:** that is
`test_delivery_failure_still_stops_pasting_at_prefix`, and it passing here is **by design, not an
oversight**. Per the spec it is a *regression pin* on FTHR-017's latch — "This must keep passing
unchanged in substance." A pin's job is to pass before and after and to fail only if this
feather breaks the latch. Its falsifiability is demonstrated under AC-3 below by mutation, since
a pre-implementation pass proves nothing on its own.

### Post-implementation

```
$ .venv/bin/pytest tests/test_live.py -m "not integration" \
    -k "delivery_failure or full_transcript_after_delivery_failure"
PLACEHOLDER — filled in after implementation
```
