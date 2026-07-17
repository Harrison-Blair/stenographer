---
id: FTHR-021
title: Fix ClipboardManager.copy() hanging on captured wl-copy pipes
plumage: PLM-010
status: hatching
priority: P0
depends_on: []
authored: 2026-07-17T04:05:50Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.8
---

# FTHR-021: Fix ClipboardManager.copy() hanging on captured wl-copy pipes

## Description
`ClipboardManager.copy()` blocks for its full 10-second timeout on every call and
returns `False`, on real hardware, today, on `dev`. Paste mode is non-functional
as shipped. This was found by FTHR-018's human-attended integration run — the
first time `copy()` has ever been executed against a real `wl-copy` from Python —
and is confirmed, not suspected (reproduction below).

**Root cause.** `wl-copy` forks a background process to serve the selection for
as long as it is offered, and that child inherits the stdout/stderr pipes created
by `subprocess.run(..., capture_output=True)`. `subprocess.run` waits for EOF on
those pipes; the daemon holds them open indefinitely; the call blocks until
`timeout=10.0` fires and raises `TimeoutExpired`, which `copy()` catches and
converts to `False`. The clipboard *is* actually set — `wl-copy` does its job —
so the failure has always been silent.

Reproduced directly (orchestrator, on `dev`, 2026-07-17):

```
wl-copy  capture_output=True  (shipped form)           8.01s  TIMEOUT
wl-copy  capture_output=False                          0.02s  ok rc=0
wl-copy --foreground capture_output=True               8.01s  TIMEOUT
```

And the clipboard is populated despite the caller timing out:

```
caller saw TIMEOUT after 6.0s
clipboard now holds: b'probe-token-7781'  (rc=0)
```

**User-visible consequences, in descending severity:**

1. **Live streaming delivers nothing.** The first delta's `copy()` returns
   `False`, which latches `_delivery_failed` (FTHR-017), and the latch is
   permanent for the utterance. Every subsequent delta is skipped. FTHR-017 and
   FTHR-020 are behaving correctly — they are faithfully handling a failure that
   should never occur.
2. **The primary selection is never populated.** `copy()` returns `False` on the
   *first* `wl-copy`'s timeout, so the loop never reaches `["wl-copy",
   "--primary"]`. FTHR-016's dual-population design — the entire mechanism
   FTHR-015 validated by hand, and the reason kitty (which pastes PRIMARY via
   `paste_from_selection`) works at all — has never once executed in production.
3. **Every dictation stalls 10s** (20s after FTHR-016's second call was added, had
   the first not returned early) on the clipboard call. The text landed anyway,
   which is why this never looked broken.

**This predates the run.** `capture_output=True` has been in `copy()` since v1
(`f20ee52`); FTHR-016 (`1465de7`) did not introduce it. Do not treat this as a
regression from PLM-009/PLM-010 — it is a latent v1 defect those feathers
inherited and, by starting to *consume* `copy()`'s return value (FTHR-017), made
visible.

**Why 489 tests missed it.** Every unit test mocks `subprocess.run`, so they pin
the code's intent and can say nothing about `wl-copy`'s real behavior. FTHR-015's
manual probe passed because a shell `printf 'x' | wl-copy` does not capture pipes.
The defect lives exactly in the gap between those two: reachable only by invoking
the real binary from Python. **The missing integration test is as much this
feather's deliverable as the fix** — a fix without it leaves the same blind spot.

Filed under PLM-010 because it blocks PLM-010's completion (FTHR-018 cannot
measure latency while every `copy()` times out) and because PLM-009 is already
`fledged` — reopening it would trip `fledge preen`. The honest classification is
that this defeats PLM-009's FC-1/FC-2 in practice: those criteria are satisfied
*in code* and were never executed. Note that in the evidence.

## Affected Modules
- `src/stenographer/output/clipboard.py::ClipboardManager.copy()` — the fix. The
  `subprocess.run` call's output handling changes; **the strict return contract
  does not** (see Approach).
- `tests/test_inject.py` (or `tests/test_clipboard.py`, matching where the
  existing clipboard tests live) — a new `@pytest.mark.integration` test that
  exercises the real `wl-copy`. This is the deliverable that closes the blind
  spot.
- **Verify, do not assume:** `src/stenographer/output/inject.py::Injector.paste()`
  also uses `capture_output=True`, on `wtype`. `wtype` exits normally rather than
  daemonizing, so it is very likely fine — FTHR-018's run reached `copy()` and
  failed there, never getting as far as `paste()`, so `paste()` is *unproven*
  rather than known-good. Check it explicitly and report; fix it only if it is
  genuinely affected.
- Out of scope: `live.py`, `session.py`, `formatter.py`, `asr/`. The latch and
  the never-revised invariant are correct and must not be touched — once `copy()`
  works, the latch simply stops firing.
- See `.fledge/molt/FTHR-015.md` (the manual probe that passed, and why),
  `.fledge/molt/FTHR-016.md` (dual-population rationale), and
  `.fledge/nest/modules.md` → `src-output`.

## Approach
Stop capturing the pipes the daemon holds. Redirecting stdout/stderr to
`subprocess.DEVNULL` is the smallest change that fixes it (measured at 0.02s
above) and keeps `check=True` working, since the return code is still collected.

Do **not** reach for `--foreground`: it was measured above and still times out
(it keeps the process in the foreground precisely so it can serve the selection,
which is the opposite of what is wanted here). Do not add threads, `Popen`
plumbing, or a clipboard daemon — this is a one-call fix, and a large solution
here is a wrong solution.

**Preserve the strict return contract.** `copy()` must still return `True` only
if *both* the regular and `--primary` writes succeed. That contract is
load-bearing: it is what makes a partial-clipboard desync detectable to
`LiveStreamer._emit()`, and it is the reason FTHR-017's prefix invariant holds.
It has never actually been exercised — `copy()` has always short-circuited on the
first timeout — so this feather is the first time the loop reaches the second
call. Keep it strict. (See FTHR-020's Approach for why loosening it deletes the
signal and leaves the bug.)

Reconsider the `timeout=10.0` only if it falls naturally out of the fix; it is
not this feather's subject. A now-0.02s call keeping a 10s ceiling is harmless.

## Tests
The integration test is the point. It must fail against the current code for the
*real* reason (the timeout), not a mocked stand-in.

- `test_clipboard_copy_real_wl_copy_round_trip` (`@pytest.mark.integration`) — the
  central test. Construct a real `ClipboardManager(available=True)`, call
  `copy(<distinctive token>)`, and assert **(a)** it returns `True`, **(b)** it
  completes in well under the 10s timeout (a generous bound such as 5s is
  appropriate *here* — unlike FTHR-018, this test's subject is "does not hang",
  so a duration bound is the behavior under test, not a latency budget), and
  **(c)** the token is readable back from **both** selections via `wl-paste` and
  `wl-paste --primary` — which pins consequence 2 above, that `--primary` is
  actually reached. Save and restore the user's clipboard around the test.
  Skip conventions: match the existing integration tests (`STENOGRAPHER_INTEGRATION`,
  `shutil.which` guards, `WAYLAND_DISPLAY`).
- `test_copy_does_not_capture_subprocess_pipes` (unit) — a cheap regression pin
  that does not need real hardware: patch `subprocess.run` and assert `copy()`
  does not pass `capture_output=True` (equivalently, that stdout/stderr are
  `DEVNULL`). This is what stops a future refactor from "tidying up" the call and
  silently restoring a 10s hang that no unit test would notice. State plainly in
  the evidence that this pins the *call shape*, not the behavior — the
  integration test is the one that proves the behavior.
- Existing `test_copy_populates_primary_selection` and the rest of the clipboard
  unit suite — must pass unmodified. If one requires modification, stop and
  escalate rather than editing it.
- Implementation order is fixed: (1) write the tests; (2) run them against
  unchanged code and confirm they FAIL for the expected reason — the integration
  test must fail on the *timeout*, taking ~10s, not on an import or a skip; (3)
  implement until they pass.

**The integration test cannot be run unattended by the brooder without checking
with the orchestrator first.** It touches the real clipboard (it does not inject
keystrokes — no `wtype` — so it is far safer than FTHR-018's, but it does clobber
the user's clipboard, hence the save/restore). Confirm with the orchestrator
before the first real run.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after. The integration test's pre-fix failure is the real timeout (~10s elapsed), captured verbatim — not a skip, not an import error.
- [ ] AC-2: `ClipboardManager.copy()` returns `True` against a real `wl-copy` and completes without hitting its timeout — paste mode is functional on real hardware.
- [ ] AC-3: Both selections are populated by a single `copy()` call, verified by reading the token back from `wl-paste` **and** `wl-paste --primary` — PLM-009 FC-1/FC-2's dual-population design executes in production for the first time.
- [ ] AC-4: `copy()`'s strict return contract is unchanged: `True` only if both writes succeed. The loop now genuinely reaches the second call.
- [ ] AC-5: A unit-level pin prevents a future refactor from reintroducing captured pipes, and the evidence states honestly that it pins the call shape rather than the behavior.
- [ ] AC-6: `Injector.paste()`'s `capture_output=True` was explicitly checked against real `wtype` behavior and the finding reported — fixed if affected, documented as unaffected if not. Not assumed either way.
- [ ] AC-7: `live.py`, `session.py`, and `formatter.py` are untouched; FTHR-017's `_delivery_failed` latch and FTHR-020's clipboard-fallback behavior are unchanged (their tests pass unmodified).
- [ ] AC-8: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions.
- [ ] AC-9: The evidence records that this is a v1-era latent defect (`capture_output=True` present since `f20ee52`), not a regression introduced by PLM-009/PLM-010, and notes that PLM-009's FC-1/FC-2 were satisfied in code but never executed.
