# FTHR-011 evidence

Noise-floor-relative tail-silence gating for live streaming. All commands run
from the worktree root (`/home/penguin/source/stenographer/.fledge/burrows/FTHR-011`)
with the worktree-local venv (`.venv/bin/...`).

## Approved deviations from the spec's literal Approach

Two deviations were discovered during test-first implementation and required
escalation; both were approved by the orchestrator (with user sign-off) before
being implemented. Documented here and in code comments at the relevant
branches in `_cut_trailing_silence`:

1. **Option 1 — uniform-window fallback.** The spec's literal formula
   (`cutoff = percentile(step_rms, 10) * 3`, trim loop compares each step's
   RMS against `cutoff`) breaks `test_cut_trailing_silence_keeps_loud_audio`:
   for any window with zero internal RMS variance (e.g. uniformly loud speech
   with no trailing silence at all), the 10th-percentile floor equals every
   step's own RMS, so `cutoff` (3x that) is never reached by any step, and the
   original `else: return window[:0]` fallback would trim the *entire* window
   to nothing even though it's all loud speech. Approved fix: when the
   backward-walk loop exhausts without any step exceeding cutoff, return the
   window **unchanged** (there is nothing safe to trim, since a self-relative
   cutoff cannot distinguish uniform-loud from uniform-silent).
2. **Option (b) — absolute dead-air floor.** Option 1 alone breaks
   `test_all_silent_window_skips_decode` (not in FTHR-011's Tests section, but
   a pre-existing correctness guard in `test_live.py`): with Option 1, a truly
   silent window now returns unchanged instead of empty, so `LiveStreamer._step`
   no longer skip-decodes dead air, risking Whisper hallucinations (e.g.
   " ghost") clearing LocalAgreement-N on the interim path. Approved fix: add
   `_SILENCE_FLOOR_RMS = 0.0005`, a dead-air detector distinct from the trim
   gate. If the window's loudest step never reaches this floor, return empty
   outright (preserving the interim skip-decode guard) before the self-relative
   trim logic runs at all.

A third, narrower fix (not separately escalated, a direct consequence of
implementing the approved fallback correctly): the trim-loop comparison uses
strict `rms > cutoff` rather than `>=`. With a data-driven cutoff, a window
mixing loud speech with true digital silence (RMS exactly 0.0) computes
`cutoff = 0.0`; with `>=`, `0.0 >= 0.0` would treat the silent tail as "loud
enough" and never trim it. Strict `>` fixes this boundary case and is
consistent with "cutoff must be exceeded to count as non-silent."

## AC-1: tests observed failing before implementation, passing after

Per the spec's Tests section: the two existing tests' call sites were updated
to drop `rms_threshold=` (signature changed) and the four new tests were
written, all run against the unchanged (pre-fix) `_cut_trailing_silence`
before any implementation changes.

Command: `.venv/bin/pytest tests/test_live.py -k "cut_trailing_silence" -v`

Pre-fix (captured before any implementation change — all 7 fail with
`TypeError: _cut_trailing_silence() missing 1 required positional argument:
'rms_threshold'`, i.e. the tests target the new (param-dropped) signature
while the implementation still requires the old one):

```
collecting ... collected 24 items / 17 deselected / 7 selected

tests/test_live.py::test_cut_trailing_silence_trims_quiet_tail FAILED    [ 14%]
tests/test_live.py::test_cut_trailing_silence_keeps_loud_audio FAILED    [ 28%]
tests/test_live.py::test_cut_trailing_silence_all_silent_returns_empty FAILED [ 42%]
tests/test_live.py::test_cut_trailing_silence_preserves_quiet_mic_trailing_speech FAILED [ 57%]
tests/test_live.py::test_cut_trailing_silence_normal_mic_still_trims_true_silence FAILED [ 71%]
tests/test_live.py::test_cut_trailing_silence_short_window_returned_unchanged FAILED [ 85%]
tests/test_live.py::test_cut_trailing_silence_is_pure FAILED             [100%]

=================================== FAILURES ===================================
__________________ test_cut_trailing_silence_trims_quiet_tail __________________
    ...
>       out = _cut_trailing_silence(window, SR)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       TypeError: _cut_trailing_silence() missing 1 required positional argument: 'rms_threshold'

tests/test_live.py:259: TypeError
[... same TypeError for all 7 ...]

=========================== short test summary info ============================
FAILED tests/test_live.py::test_cut_trailing_silence_trims_quiet_tail - TypeE...
FAILED tests/test_live.py::test_cut_trailing_silence_keeps_loud_audio - TypeE...
FAILED tests/test_live.py::test_cut_trailing_silence_all_silent_returns_empty
FAILED tests/test_live.py::test_cut_trailing_silence_preserves_quiet_mic_trailing_speech
FAILED tests/test_live.py::test_cut_trailing_silence_normal_mic_still_trims_true_silence
FAILED tests/test_live.py::test_cut_trailing_silence_short_window_returned_unchanged
FAILED tests/test_live.py::test_cut_trailing_silence_is_pure - TypeError: _cu...
======================= 7 failed, 17 deselected in 0.16s =======================
```

Post-fix (after implementing `_cut_trailing_silence` per the approved
design — floor*3 self-relative trim, Option-1 uniform fallback, and the
absolute `_SILENCE_FLOOR_RMS` dead-air floor):

```
collecting ... collected 24 items / 17 deselected / 7 selected

tests/test_live.py::test_cut_trailing_silence_trims_quiet_tail PASSED    [ 14%]
tests/test_live.py::test_cut_trailing_silence_keeps_loud_audio PASSED    [ 28%]
tests/test_live.py::test_cut_trailing_silence_all_silent_returns_empty PASSED [ 42%]
tests/test_live.py::test_cut_trailing_silence_preserves_quiet_mic_trailing_speech PASSED [ 57%]
tests/test_live.py::test_cut_trailing_silence_normal_mic_still_trims_true_silence PASSED [ 71%]
tests/test_live.py::test_cut_trailing_silence_short_window_returned_unchanged PASSED [ 85%]
tests/test_live.py::test_cut_trailing_silence_is_pure PASSED             [100%]

======================= 7 passed, 17 deselected in 0.14s =======================
```

Note: `test_cut_trailing_silence_short_window_returned_unchanged` also
verifies the spec's second failing-for-the-expected-reason claim (the old code
did not skip short-but-nonzero windows) implicitly — pre-fix it failed on the
same `TypeError` (signature mismatch) rather than a distinct "old code ran the
RMS gate on a short window" failure, because the two changes (signature drop +
short-window skip) landed together in one test-first pass per the spec's
stated implementation order. The short-window skip logic itself is exercised
and passes post-fix (see AC-3 below).

## AC-2: gate is relative to the window's own 10th-percentile step RMS

`_cut_trailing_silence` (src/stenographer/live.py) computes
`floor = np.percentile(step_rms, 10)` and `cutoff = floor * _NOISE_FLOOR_MULTIPLIER`
(`_NOISE_FLOOR_MULTIPLIER = 3`, module-level constant) from the window's own
per-50ms step RMS array — no reference to `audio.silence_rms_threshold`
anywhere in the function. Verified by reading the diff and by
`test_cut_trailing_silence_preserves_quiet_mic_trailing_speech` /
`test_cut_trailing_silence_normal_mic_still_trims_true_silence` (both PASSED
above), which exercise the self-relative gate directly.

```
$ grep -n "silence_rms_threshold\|_NOISE_FLOOR_MULTIPLIER\|percentile" src/stenographer/live.py
51:_NOISE_FLOOR_MULTIPLIER = 3
277:    floor = np.percentile(step_rms, 10)
278:    cutoff = floor * _NOISE_FLOOR_MULTIPLIER
```

(`silence_rms_threshold` no longer appears in `live.py` at all — see AC-4.)

## AC-3: windows with fewer than 10 steps (0.5s) are returned unchanged

```python
n_steps = mono.shape[0] // step
if n_steps < 10:
    return window
```

`test_cut_trailing_silence_short_window_returned_unchanged` builds a 0.3s
(6-step) window mixing loud and quiet content and asserts
`out.shape[0] == mixed.shape[0]` and `np.array_equal(out, mixed)` — PASSED
(see AC-1 post-fix output above).

## AC-4: `audio.silence_rms_threshold` / capture.py / other LiveStreamer methods untouched

```
$ git diff --stat -- src/stenographer/audio/capture.py src/stenographer/config.py
(no output — zero changes to either file)

$ git diff src/stenographer/live.py | grep -n "silence_rms_threshold"
-            self._cfg.audio.silence_rms_threshold,
```

The only occurrence removed is the call-site argument in `_step` (which now
calls `_cut_trailing_silence(window, self._cfg.audio.sample_rate)` — one
fewer argument, no other line of `_step` changed). No other `LiveStreamer`
method (`_finish`, `_maybe_trim`, `_decode`, `_emit`, `run`, `_run`, etc.) was
touched — confirmed by `git diff src/stenographer/live.py` showing changes
confined to: the two new module constants, the `_step` call-site, and the
body of `_cut_trailing_silence` itself.

## AC-5: quiet-mic trailing speech preserved; normal/loud-mic true silence still trimmed

`test_cut_trailing_silence_preserves_quiet_mic_trailing_speech`: builds a
window with quiet-mic speech (RMS 0.003, well under the old fixed 0.01
threshold) followed by quiet ambient noise (RMS ~0.0002, not exact zero).
Asserts the old fixed-0.01 gate would have trimmed everything
(`old_gate_result_len = 0`, since every step including speech is < 0.01) while
the new implementation keeps the full speech segment plus cushion. PASSED.

`test_cut_trailing_silence_normal_mic_still_trims_true_silence`: loud speech
(RMS 0.5) followed by >=10 steps of true silence (RMS 0.0). Asserts the output
is bounded to roughly speech + cushion (`SR <= out.shape[0] <= SR + int(0.3*SR)`),
i.e. the silent tail is still trimmed on a normal/loud mic. PASSED.

Both shown PASSED in the AC-1 post-fix output above.

## AC-6: purity — identical input produces identical output

`test_cut_trailing_silence_is_pure` calls `_cut_trailing_silence` twice with
the same window (quiet-mic fixture, long enough to trigger a real trim) and
asserts `np.array_equal(out1, out2)`. PASSED (see AC-1 post-fix output above).
The function reads no `self` state (it is a module-level free function with
no globals mutated) — confirmed by inspection of the diff: no assignment to
any name outside the function's own locals.

## AC-7: full unit suite passes with no regressions

Command: `.venv/bin/pytest -m "not integration" -q`

```
........................................................................ [ 14%]
........................................................................ [ 29%]
........................................................................ [ 44%]
........................................................................ [ 58%]
........................................................................ [ 73%]
........................................................................ [ 88%]
.........................................................                [100%]
489 passed, 4 deselected in 14.91s
```

(Baseline before any FTHR-011 changes was `485 passed, 4 deselected` — the +4
is the four new tests; `test_all_silent_window_skips_decode`, the existing
correctness guard threatened by the Option-1-only design, passes unchanged
thanks to the `_SILENCE_FLOOR_RMS` dead-air floor.)

Lint / format:

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
57 files already formatted
```
