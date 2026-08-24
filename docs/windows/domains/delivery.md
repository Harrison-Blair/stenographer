# Windows Domain Plan — Delivery

Scope: the two host surfaces behind `Deliverer` — `ClipboardWriter` (Win32 clipboard, confirmed by
read-back) and `KeyInjector` (the paste chord via `SendInput`) — plus their provider wiring. Blast
area is contained inside `platform/windows/`: `delivery/deliver.py` is core and unchanged, and every
new module is reachable only through `WindowsPlatform.clipboard_writer()` / `key_injector()`. Cues
and toasts on the failure path belong to WIN-FEED; the doctor probe that consumes
`probe_clipboard()` belongs to WIN-DIAG. All items are phase 1 (README §F).

## Designed source tree

My rows from README §T, and one file the §T tree does not list:

```
src/stenographer/platform/windows/
├── clipboard.py        NEW   CF_UNICODETEXT write through a message-only owner window,
│                             bounded retry, read-back confirmation, cloud-clipboard opt-out
├── sendinput.py        NEW   Ctrl+V chord as one atomic SendInput call, tagged dwExtraInfo
└── __init__.py         EDIT  clipboard_writer() / key_injector() wiring; lazy imports only

tests/platform/windows/  NEW  Windows-only tests, not collected elsewhere
├── conftest.py                    NEW   collect_ignore_glob guard (create if absent)
├── test_clipboard.py              NEW   pure: retry schedule, allocation size, confirmation
├── test_sendinput.py              NEW   pure: chord table, struct layout, inject tag
└── test_delivery_smoke.py         NEW   integration: real clipboard, real chord, real window

tests/platform/test_platform.py    EDIT  off-tree: the stub's "everything unavailable"
                                         assertions for the two delivery surfaces
```

> Adding to README §T: `tests/platform/test_platform.py` asserts
> `pytest.raises(UnsupportedPlatformError)` for `clipboard_writer("unavailable")` and
> `key_injector()`. That file is shared, not under `tests/platform/windows/**`, so WIN-DELIV-03
> lands in D8's **both suites** row even though the domain is otherwise contained. This is the only
> file outside `platform/windows/` and `tests/platform/windows/` that this domain touches.

## Architecture principles

Global rules apply unrestated: lazy provider imports and no import-time Win32 (§P1), no mock
theater (§P6), the delivery invariant (§P8), privacy in logs (§P9), SPDX and tooling (§P10).

**WIN-DELIV-P1 — Allocate before opening; never hold the clipboard across an allocation.**
The per-attempt order is fixed: `GlobalAlloc(GMEM_MOVEABLE, …)` →
`GlobalLock`/copy/`GlobalUnlock` → `OpenClipboard(hwnd)` → `EmptyClipboard()` →
`SetClipboardData(CF_UNICODETEXT, h)` → `CloseClipboard()`. Nothing that can fail slowly sits
between `EmptyClipboard` and `SetClipboardData`, because that window is where a failure destroys
the user's *previous* clipboard content with nothing to replace it. `CloseClipboard()` runs in a
`finally`: an attempt that returns early while still holding the global clipboard deadlocks every
other application on the desktop.

**WIN-DELIV-P2 — `SetClipboardData` is the ownership boundary; free the handle if and only if it
returns NULL.** After a non-NULL return the system owns the `HGLOBAL` and calling `GlobalFree` on
it is a double free inside the daemon process. Each retry attempt allocates its own fresh handle;
a handle from a failed attempt is freed and never reused. The same rule applies to the ancillary
`CanUploadToCloudClipboard` handle.

**WIN-DELIV-P3 — The chord is virtual-key driven, not scan-code driven.** `chord_inputs()` sets
`wVk` (`VK_LCONTROL` 0xA2, `VK_V` 0x56) and fills `wScan` from the fixed table (0x1D, 0x2F) for
lParam fidelity; `KEYEVENTF_SCANCODE` is **never** set, and neither is `KEYEVENTF_EXTENDEDKEY` —
neither chord key is in the E0-prefixed set (right Ctrl, Alt Gr, the grey Insert/Delete/arrow
block and NumLock are; left Ctrl and V are not). Setting `KEYEVENTF_EXTENDEDKEY` on 0x1D would
inject *right* Ctrl; setting `KEYEVENTF_SCANCODE` would inject the physical key *position*, which
the foreground thread's layout re-maps — on Dvorak that position is K, so the chord becomes Ctrl+K
and paste silently no-ops. README §D1 fixes the chord as the virtual key Ctrl+V, and the silent
no-op is precisely the failure mode §D1 rejects.

> Correcting SCOPE.md §2 (`KeyInjector` row) and the §T role line for `sendinput.py`: both say
> "`SendInput` with scan codes (`KEYEVENTF_SCANCODE`)", carried over from the Linux injector where
> evdev codes *are* physical. The flag is not a settled decision (§D1 settles only the constant),
> and under it §D1's constant is not what reaches the application on a remapped layout.

**WIN-DELIV-P4 — One `SendInput` call, four events, checked return.** The whole chord goes in a
single `SendInput(4, arr, sizeof(INPUT))`; the array is inserted atomically, so no other thread's
input can interleave between the Ctrl press and the Ctrl release and leave Ctrl latched
system-wide. A return value below 4 means the input was rejected (UIPI against an elevated
foreground window, per §D7, or a locked desktop): `send_chord()` raises
`ctypes.WinError(ctypes.get_last_error())`. It does not swallow the failure — `daemon.py:437`
already catches a raising `deliver()` into the error cue + notify path, and swallowing would report
`DELIVERED` for an utterance that never pasted.

**WIN-DELIV-P5 — Every injected event carries `INJECT_TAG` in `dwExtraInfo`.** `INJECT_TAG` is
defined in `sendinput.py` and imported from there by the WIN-INPUT hook, which drops events
matching it. Filtering on `LLKHF_INJECTED` instead is forbidden: on-screen keyboards, remote
desktop and other assistive tools inject the *user's* real hotkey, and dropping all injected input
would make the hotkey stop working under them. Without the tag a binding containing left Ctrl
self-retriggers on its own paste chord.

**WIN-DELIV-P6 — Confirmation is byte-exact equality against the text we intended to paste.**
`confirm_readback(expected, observed)` compares with `==` after NUL-termination trimming — never
`startswith`, never `strip()`. The formatter emits exactly one trailing space; a whitespace-lenient
comparison confirms a write that lost it, and a prefix comparison confirms a truncated write. A
read-back that does not equal `expected` returns `False` from the writer, and §P8 does the rest.

**WIN-DELIV-P7 — Clipboard history stays; cloud upload is opted out.** In the same clipboard
session, after `CF_UNICODETEXT`, the writer sets the registered format
`RegisterClipboardFormatW("CanUploadToCloudClipboard")` to a 4-byte DWORD `0`.
`CanIncludeInClipboardHistory` and `ExcludeClipboardContentFromMonitorProcessing` are **not** set:
because the clipboard write is the
documented recovery path when focus is wrong, and Win+V history is part of how a user recovers it.
Cloud upload is different in kind — it would ship the transcript off the machine, which the
offline-only contract forbids. A failure of the ancillary set is logged at `debug` and does not
fail the copy; only `CF_UNICODETEXT` is load-bearing.

**WIN-DELIV-P8 — A clipboard manager that rewrites identical text still confirms.**
`GetClipboardSequenceNumber()` is read after the write and again at read-back, and a change is
logged as a numeric metric only. It never fails the copy: managers and history services routinely
re-set the clipboard with byte-identical content, and failing there would break delivery for every
user who runs one. The text comparison of WIN-DELIV-P6 is what §4.3 requires and is sufficient — a
confirmation means the clipboard held *our* text at read time, so the dangerous direction (confirm
while stale content is present) cannot occur. The remaining hole is the microseconds between
read-back and the chord; it is unfixable on any OS, Linux has it too, and it is out of scope.

**WIN-DELIV-P9 — Handle-returning prototypes declare `restype`.** Every `ctypes` prototype used by
either module is declared in a module-level `_PROTOTYPES` table with explicit `argtypes` and
`restype`, applied inside the cached `_user32()` / `_kernel32()` accessors. ctypes defaults
`restype` to `c_int`, which truncates every 64-bit `HWND`/`HGLOBAL` to 32 bits — the resulting
`SetClipboardData` failure is intermittent and looks like contention. DLL handles are resolved with
`ctypes.WinDLL(name, use_last_error=True)` inside those accessors and never at module scope
(§P1: the Linux bundle `collect_submodules` these files, and `ctypes.WinDLL` does not exist on
Linux). Struct, flag and constant definitions may be module-level — `ctypes.wintypes` imports fine
on Linux.

**WIN-DELIV-P10 — Off Windows, the provider methods raise `UnsupportedPlatformError`.**
`WindowsPlatform.clipboard_writer()` and `key_injector()` check `sys.platform != "win32"` *before*
constructing anything. Without the check the Linux failure mode is
`AttributeError: module 'ctypes' has no attribute 'WinDLL'`, which reads as a bug rather than as an
unsupported host, and it breaks the `UnsupportedPlatformError` contract that
`tests/platform/test_platform.py` asserts on every host.

**WIN-DELIV-P11 — The writer is single-threaded by contract, not by locking.** One utterance at a
time (AGENTS.md hard rule 5) means `Deliverer` is only ever called from the pipeline thread. The
message-only owner window is created lazily on the first copy, reused for the process lifetime, and
destroyed only from its creating thread (`DestroyWindow` requires it). A call arriving from a
different thread logs a warning and creates a second window rather than failing; no lock is added,
because a lock here would hide a violation of the one-utterance invariant instead of surfacing it.

## Functional criteria

### WIN-DELIV-01 — Implement the Win32 clipboard writer
Phase: 1   Depends on: none
Files: `src/stenographer/platform/windows/clipboard.py` (NEW),
`tests/platform/windows/conftest.py` (NEW, create if absent),
`tests/platform/windows/test_clipboard.py` (NEW),
`tests/platform/windows/test_delivery_smoke.py` (NEW)
Pure tests: `tests/platform/windows/test_clipboard.py::test_retry_schedules_stay_inside_the_budget`,
`::test_no_retry_delay_is_zero`,
`::test_hglobal_byte_size_counts_utf16_code_units_plus_terminator`,
`::test_confirm_readback_requires_exact_equality`,
`::test_confirm_readback_rejects_a_prefix_and_a_stripped_match`,
`::test_copy_for_backend_maps_the_win32_name_and_rejects_others`,
`::test_handle_returning_prototypes_are_pointer_sized`
Smoke: `test_copy_round_trips_via_the_real_clipboard`,
`test_copy_succeeds_while_another_process_holds_the_clipboard_briefly`,
`test_copy_returns_false_when_the_clipboard_is_held_past_the_budget`,
`test_repeated_copies_do_not_corrupt_the_heap`
Done when: `WindowsClipboard()("text")` returns `True` and `powershell -c Get-Clipboard` prints that
exact text, and returns `False` — leaving the previous clipboard content intact — when another
process holds the clipboard for longer than `RETRY_BUDGET_SECONDS`.

Module surface: `CLIPBOARD_BACKEND = "win32"`; `OPEN_RETRY_DELAYS = (0.005, 0.01, 0.02, 0.04, 0.08,
0.12, 0.2, 0.2, 0.2)`; `READBACK_RETRY_DELAYS = (0.005, 0.01, 0.02, 0.04, 0.08)`;
`RETRY_BUDGET_SECONDS = 1.2`; `hglobal_byte_size(text) -> int`;
`confirm_readback(expected, observed) -> bool`; `read_clipboard_text() -> str | None`;
`class WindowsClipboard` with `__call__(self, text: str) -> bool`;
`copy_for_backend(backend: str) -> ClipboardWriter`; `probe_clipboard() -> tuple[bool, str]`
(an `OpenClipboard`/`CloseClipboard` round trip returning `(ok, CLIPBOARD_BACKEND)`, mirroring
`platform/linux/clipboard.py`, for WIN-DIAG's `probe_host`).

Retry budget, justified against §P8. Ten open attempts (the first plus the nine
`OPEN_RETRY_DELAYS`) summing 0.875 s, then six read-back attempts summing 0.155 s: ~1.03 s of sleep,
declared as a 1.2 s wall-clock budget. `OpenClipboard` fails with `ERROR_ACCESS_DENIED` while
another process holds the global clipboard; typical holds are single-digit milliseconds and the
worst realistic ones (Office, RDP, a history service reacting to the change) are a few hundred, so
the geometric ramp to a 0.2 s ceiling covers them without a busy loop. The budget is bounded rather
than generous because §P8 makes `False` the *safe* result: a longer budget buys a marginally higher
success rate by stalling the single-utterance pipeline, and the daemon has already spent the ASR
decode. 1.2 s also sits under the release guard's 1.5 s default, so the two bounded waits do not
compound into a multi-second gap between speech and paste. Linux's equivalent worst case is 20 s
(`_COPY_TIMEOUT_SECONDS` 10.0 × two selections); Windows has no primary selection, so there is one
write and one read-back.

Retry unit is the whole sequence: a failed `SetClipboardData` closes the clipboard, consumes the
next delay, and re-runs `GlobalAlloc` → open → empty → set with a fresh handle (P1, P2 above).
`GlobalUnlock` returning 0 is checked against `ctypes.get_last_error() == 0`, not treated as
failure — it returns 0 legitimately when the lock count reaches zero.

### WIN-DELIV-02 — Implement the `SendInput` paste chord
Phase: 1   Depends on: none
Files: `src/stenographer/platform/windows/sendinput.py` (NEW),
`tests/platform/windows/test_sendinput.py` (NEW)
Pure tests: `tests/platform/windows/test_sendinput.py::test_chord_inputs_exact_sequence`,
`::test_every_press_has_a_matching_release`,
`::test_v_released_before_ctrl`,
`::test_ctrl_is_the_outer_wrapper`,
`::test_chord_never_sets_the_scancode_flag`,
`::test_chord_never_sets_the_extendedkey_flag`,
`::test_input_struct_size_matches_the_pointer_width`,
`::test_every_built_input_carries_the_inject_tag`
Smoke: none — a chord with no window under test is unobservable, and observing it needs the window
harness that WIN-DELIV-04 builds; that item carries this module's real-machine cases.
Done when: `chord_inputs()` returns the four `(vk, scan, flags)` triples with Ctrl wrapping V and
`ctypes.sizeof(INPUT) == 40` on a 64-bit interpreter.

Module surface: `INJECT_TAG = 0x53544E47`; `VK_LCONTROL`, `VK_V`, `SCAN_LCONTROL = 0x1D`,
`SCAN_V = 0x2F`; `KEYEVENTF_EXTENDEDKEY = 0x0001`, `KEYEVENTF_KEYUP = 0x0002`,
`KEYEVENTF_SCANCODE = 0x0008`; `INPUT_KEYBOARD = 1`; `class KEYBDINPUT`, `MOUSEINPUT`,
`HARDWAREINPUT`, `_INPUTUNION`, `INPUT`; `chord_inputs() -> tuple[tuple[int, int, int], ...]`;
`build_inputs(events) -> ctypes.Array[INPUT]`; `class SendInputKeyboard` with `send_chord()` and a
no-op `close()`.

`MOUSEINPUT` and `HARDWAREINPUT` are declared even though only the keyboard member is used: the
union takes the size of its largest member, and omitting them yields `sizeof(INPUT) == 32` on
x64, so `SendInput` rejects the call with `ERROR_INVALID_PARAMETER` and returns 0.
`ULONG_PTR` members use `wintypes.WPARAM` so the layout follows the pointer width.

### WIN-DELIV-03 — Wire both surfaces into the Windows provider
Phase: 1   Depends on: WIN-DELIV-01, WIN-DELIV-02
Files: `src/stenographer/platform/windows/__init__.py` (EDIT),
`tests/platform/test_platform.py` (EDIT),
`tests/platform/windows/test_delivery_smoke.py` (EDIT)
Pure tests:
`tests/platform/test_platform.py::test_windows_provider_delivery_surfaces_follow_the_host`
Smoke: `test_provider_returns_a_working_writer_and_injector`
Done when: on Windows, `WindowsPlatform().clipboard_writer("win32")` returns a callable that copies
and `key_injector()` returns a `KeyInjector`; on Linux both still raise `UnsupportedPlatformError`
and the rest of `tests/platform/test_platform.py` is unchanged.

`clipboard_writer` lazy-imports `copy_for_backend` and passes the backend name straight through
(mirroring the Linux provider's `ClipboardBackend(backend)` lookup); an unknown name raises
`UnsupportedPlatformError` rather than silently returning the win32 writer, so a WIN-DIAG probe
regression that reports the wrong backend name fails loudly at startup instead of at first paste.
Both methods carry the `sys.platform` guard of WIN-DELIV-P10. The `tests/platform/test_platform.py`
edit splits the two delivery assertions out of
`test_windows_stub_conforms_and_reports_everything_unavailable` into a new host-conditional test;
the remaining stub assertions (lock, key table, directories, `HostProbe`) stay untouched.

This item falls in D8's **both suites** row — see the note under *Designed source tree*. The Linux
behavior that must stay byte-identical is `platform/linux/__init__.py`'s `clipboard_writer` /
`key_injector`, which this item does not touch; the proof is
`tests/platform/linux/test_clipboard.py::test_copy_for_backend_maps_each_backend_to_its_copier`
and the existing Linux delivery smoke suite.

### WIN-DELIV-04 — Build the self-owned-window delivery smoke harness
Phase: 1   Depends on: WIN-DELIV-01, WIN-DELIV-02, WIN-DELIV-03
Files: `tests/platform/windows/test_delivery_smoke.py` (EDIT)
Pure tests: none — this item is the real-machine harness; its logic is Win32 window management,
which has no pure part to extract (§P5 is satisfied by the pure targets of items 01 and 02).
Smoke: `test_chord_pastes_into_a_self_owned_edit_control`,
`test_failed_copy_never_pastes_into_the_test_window`,
`test_chord_does_not_leave_ctrl_latched`
Done when: with `STENOGRAPHER_INTEGRATION=1` on an interactive Windows session, a real
`Deliverer` built from the real writer and the real injector puts a unique token into a
test-process-owned edit control, with no manual step.

Harness: `_edit_window()` creates a real top-level window of the predefined `"EDIT"` class
(`CreateWindowExW(0, "EDIT", None, WS_OVERLAPPEDWINDOW | WS_VISIBLE | ES_MULTILINE, 100, 100, 400,
200, None, None, None, None)`) — the edit control implements Ctrl+V natively, so no custom
`WndProc` is needed — then `SetForegroundWindow` + `SetFocus`, and `_pump(deadline)` runs
`PeekMessageW`/`TranslateMessage`/`DispatchMessageW` until `GetWindowTextW` shows the token or the
deadline passes. `DestroyWindow` in a `finally`. The module self-skips unless
`STENOGRAPHER_INTEGRATION=1`, `sys.platform == "win32"`, and `SetForegroundWindow` succeeds against
a non-NULL `GetForegroundWindow()` — headless and locked-desktop sessions have no input queue to
inject into, and a session running an elevated foreground window is skipped by the same guard
rather than reported as a failure (§D7).

The clipboard-contention cases use `_clipboard_hog(hold_seconds)`, a `subprocess.Popen` of
`sys.executable -c` that opens the clipboard through the same Win32 calls, prints a ready line on
stdout, sleeps, and closes. Nothing here is mocked: the hog is a genuine second process contending
for the genuine global clipboard.

## Acceptance criteria

### WIN-DELIV-01

**Pure tests — and the broken behavior each must be seen to fail against (§P6).**

- `test_retry_schedules_stay_inside_the_budget` — asserts
  `sum(OPEN_RETRY_DELAYS) + sum(READBACK_RETRY_DELAYS) <= RETRY_BUDGET_SECONDS` and
  `RETRY_BUDGET_SECONDS < 1.5`. Seen to fail against a schedule widened to
  `(0.5,) * 20`: 10 s of sleeping inside a copy stalls the one-at-a-time pipeline past the release
  guard and past the next utterance, which is exactly the trade §P8 forbids.
- `test_no_retry_delay_is_zero` — asserts `min(OPEN_RETRY_DELAYS) > 0` and the same for the
  read-back schedule. Seen to fail against `(0.0,) * 9`, which turns the retry into a microsecond
  busy loop: the CPU spins and the ten attempts all land inside a single contended hold, so
  transient contention fails as if there were no retry at all.
- `test_hglobal_byte_size_counts_utf16_code_units_plus_terminator` — asserts `""` → 2, `"a"` → 4,
  `"é"` → 4, `"😀"` → 6, `"ab😀"` → 10. Seen to fail against `(len(text) + 1) * 2`, which
  under-allocates by two bytes per astral character; the copy then writes past the allocation and
  the read-back returns truncated text.
- `test_confirm_readback_requires_exact_equality` — asserts `confirm_readback("hi ", "hi ")` is
  `True`, `confirm_readback("hi ", None)` is `False`, `confirm_readback("hi ", "")` is `False`.
- `test_confirm_readback_rejects_a_prefix_and_a_stripped_match` — asserts
  `confirm_readback("hello world ", "hello")` and `confirm_readback("hello world ", "hello world")`
  are both `False`. Seen to fail against a `startswith` comparison and against
  `expected.strip() == observed.strip()`; the second is the live hazard, because the formatter's
  single trailing space is contract and a whitespace-lenient confirm would fire the chord for a
  write that lost it.
- `test_copy_for_backend_maps_the_win32_name_and_rejects_others` — asserts
  `isinstance(copy_for_backend("win32"), WindowsClipboard)` and that `copy_for_backend("wl-copy")`
  raises `UnsupportedPlatformError`. Constructing `WindowsClipboard` must not touch Win32, which
  this test enforces by construction.
- `test_handle_returning_prototypes_are_pointer_sized` — for each of `CreateWindowExW`,
  `GlobalAlloc`, `GlobalLock`, `SetClipboardData`, `GetClipboardData`, asserts the `_PROTOTYPES`
  entry's `restype` satisfies `ctypes.sizeof(restype) == ctypes.sizeof(ctypes.c_void_p)`. Seen to
  fail against a table entry left at the ctypes default `c_int`, which truncates a 64-bit handle
  and makes `SetClipboardData` fail intermittently in a way indistinguishable from contention.

**Smoke — real-machine procedure.** Run `STENOGRAPHER_INTEGRATION=1 .venv\Scripts\pytest
tests\platform\windows -m integration` on an interactive Windows session.

- `test_copy_round_trips_via_the_real_clipboard` — copy `stenographer-smoke-<uuid4>`, assert the
  writer returned `True`, then read it back through a separate `powershell -NoProfile -Command
  Get-Clipboard` process and compare exactly. A second process reading it proves the write is
  visible outside our own clipboard session. Also asserts the writer's `_hwnd` is identical across
  two consecutive copies (one owner window, reused — WIN-DELIV-P11).
- `test_copy_succeeds_while_another_process_holds_the_clipboard_briefly` — start
  `_clipboard_hog(0.3)`, wait for its ready line, call the writer, assert `True` and that the
  elapsed time is under `RETRY_BUDGET_SECONDS`. Observable: transient contention is survived, not
  merely retried.
- `test_copy_returns_false_when_the_clipboard_is_held_past_the_budget` — seed the clipboard with
  sentinel `A`, start `_clipboard_hog(3.0)`, call the writer with `B`, assert it returned `False`
  within ~1.3 s, then after the hog exits assert the clipboard still holds `A`. Two observables in
  one: the bounded budget really bounds, and a copy that fails on contention has not destroyed the
  user's previous clipboard (WIN-DELIV-P1).
- `test_repeated_copies_do_not_corrupt_the_heap` — 500 sequential copies of distinct tokens through
  one writer instance, asserting `True` and a matching read-back on each. A `GlobalFree` of a
  handle the system already owns (WIN-DELIV-P2) corrupts the process heap; the observable is that
  the test process survives all 500 iterations and the last read-back still matches.

**Observable behavior.** `stenographer doctor` on Windows reports `clipboard (win32)` as available
once WIN-DIAG consumes `probe_clipboard()`; a transcript copied by the daemon appears in Win+V
history and does not appear on another device signed into the same Microsoft account with cloud
clipboard enabled (WIN-DELIV-P7 — verified once, by hand, on the merge-gate machine).

### WIN-DELIV-02

**Pure tests — and the broken behavior each must be seen to fail against.**

- `test_chord_inputs_exact_sequence` — asserts the exact four-triple tuple
  `((VK_LCONTROL, SCAN_LCONTROL, 0), (VK_V, SCAN_V, 0), (VK_V, SCAN_V, KEYEVENTF_KEYUP),
  (VK_LCONTROL, SCAN_LCONTROL, KEYEVENTF_KEYUP))`. This is the Windows counterpart of
  `tests/platform/linux/test_uinput.py::test_chord_events_exact_sequence`.
- `test_every_press_has_a_matching_release` — every vk appearing without `KEYEVENTF_KEYUP` appears
  again with it. Seen to fail against a table missing the Ctrl release, which latches Ctrl
  system-wide for every subsequent keystroke the user types.
- `test_v_released_before_ctrl` and `test_ctrl_is_the_outer_wrapper` — the modifier-wraps-key
  ordering. Seen to fail against Ctrl released before V, which delivers a bare `v` keystroke into
  the focused document after the paste.
- `test_chord_never_sets_the_scancode_flag` — asserts no triple's flags contain
  `KEYEVENTF_SCANCODE`. Seen to fail against the literal SCOPE.md §2 reading; the observable
  consequence is covered by the Dvorak case under WIN-DELIV-04.
- `test_chord_never_sets_the_extendedkey_flag` — asserts no triple's flags contain
  `KEYEVENTF_EXTENDEDKEY`. Seen to fail against setting it on the Ctrl entries, which injects right
  Ctrl (E0 1D); with a Right-Ctrl hotkey binding that is the user's own binding being injected, and
  it re-enters the hook as a phantom press.
- `test_input_struct_size_matches_the_pointer_width` — asserts `ctypes.sizeof(INPUT) == 40` when
  `ctypes.sizeof(ctypes.c_void_p) == 8`, else 28. Runs on any host, since `ctypes.wintypes` imports
  on Linux. Seen to fail against a union declared with `KEYBDINPUT` alone (32 bytes on x64), the
  form in which `SendInput` returns 0 with `ERROR_INVALID_PARAMETER` and nothing ever pastes.
- `test_every_built_input_carries_the_inject_tag` — builds `build_inputs(chord_inputs())` and
  asserts every element has `type == INPUT_KEYBOARD` and `ki.dwExtraInfo == INJECT_TAG`. No DLL is
  loaded: the array is plain ctypes memory. Seen to fail against a builder that leaves
  `dwExtraInfo` at 0, which is the state in which the WIN-INPUT hook cannot tell our chord from a
  human keypress.

**Smoke: none, justified.** `SendInput` with no window under test has no observable effect that a
test can assert without either a mock (forbidden, §P6) or a global keyboard hook belonging to
another domain. The real-machine coverage is WIN-DELIV-04, which depends on this item.

**Observable behavior.** With the daemon running and a Notepad window focused, dictating one
utterance leaves the transcript in the document and leaves no modifier stuck: pressing a letter key
afterwards types that letter rather than triggering a Ctrl shortcut.

### WIN-DELIV-03

**Pure test.**
`tests/platform/test_platform.py::test_windows_provider_delivery_surfaces_follow_the_host` — on
`sys.platform == "win32"`, asserts `clipboard_writer("win32")` is callable and
`key_injector()` satisfies the `KeyInjector` protocol; on every other host, asserts both raise
`UnsupportedPlatformError`. Seen to fail, on Linux, against provider methods that construct the
backends without the WIN-DELIV-P10 guard: the raised exception is
`AttributeError: module 'ctypes' has no attribute 'WinDLL'`, not `UnsupportedPlatformError`. Also
asserts `clipboard_writer("wl-copy")` raises `UnsupportedPlatformError` on Windows.

**Smoke.** `test_provider_returns_a_working_writer_and_injector` — build the writer and injector
through `WindowsPlatform()` rather than by importing the backends directly, construct a real
`Deliverer(keyboard=injector, copy=writer)`, and assert `deliver(token)` returns `True` with the
token readable back from the clipboard. This is the wiring under test, not the backends.

**Regression guard on the existing suites.** `.venv/bin/pytest -m "not integration"` on Linux stays
green with no change to any assertion other than the two that moved, and `unit-windows` collects
`tests/platform/windows/` for the first time. Per D8 this item requires both real-machine suites.

**Observable behavior.** `stenographer run` on Windows no longer exits 78 for the clipboard and
injector rows of the doctor gate (the hotkey row still gates until WIN-INPUT lands), and
`stenographer --help` still completes without loading `ctypes.windll` — checked with
`python -X importtime -m stenographer.cli --help` showing no `platform.windows.clipboard` or
`platform.windows.sendinput` import (§P1).

### WIN-DELIV-04

**Smoke — real-machine procedure.** Same command as WIN-DELIV-01, on an interactive session with no
elevated window focused.

- `test_chord_pastes_into_a_self_owned_edit_control` — create the edit window, focus it, copy a
  unique token through the real writer, call `SendInputKeyboard().send_chord()`, pump messages for
  up to 2 s, assert `GetWindowTextW(hwnd) == token`. Fully automated, with no manual paste step —
  unlike the Linux `tests/delivery/test_deliver_smoke.py`, which documents a per-compositor manual
  confirmation because it has no window it owns. Run it a second time with the session keyboard
  layout switched to United States-Dvorak (Settings → Language → add layout, then Win+Space): the
  assertion must still hold, which is the observable proof of WIN-DELIV-P3. Restore the layout
  afterwards.
- `test_failed_copy_never_pastes_into_the_test_window` — the §P8 case. Seed the clipboard with
  sentinel `A`, create and focus the edit window, start `_clipboard_hog(3.0)`, then call
  `Deliverer(keyboard=real_injector, copy=real_writer).deliver(B)`. Assert `deliver` returned
  `False`, and after pumping messages for 1 s assert the edit control text is still `""` — not `A`.
  The distinction is the whole point: a chord fired after a failed copy would paste the stale
  sentinel, which is the §4.3 hazard stated as an observation rather than as an assertion about a
  call that did not happen. Nothing is mocked; the injector and writer are the real ones.
- `test_chord_does_not_leave_ctrl_latched` — after `send_chord()`, assert
  `GetKeyState(VK_CONTROL) & 0x8000 == 0` and `GetAsyncKeyState(VK_LCONTROL) & 0x8000 == 0`.
  Catches a partially-inserted chord (WIN-DELIV-P4) and a table missing the Ctrl release.

**Observable behavior.** The harness skips cleanly, with a stated reason, on a headless or
locked session instead of failing — so the D8 Windows gate is a genuine signal rather than a
flaky one.

## Risks

1. **Scan-code injection breaks paste on remapped layouts.** Likelihood medium — SCOPE.md §2 and
   README §T both say `KEYEVENTF_SCANCODE`, so an implementer following the plan literally writes
   the broken form. Impact high: silent no-op paste on Dvorak, Colemak and any custom layout that
   moves V, indistinguishable from a bad paste — the failure mode README §D1 exists to avoid.
   Mitigation: WIN-DELIV-P3 plus the correction blockquote. Covered by AC WIN-DELIV-02
   (`test_chord_never_sets_the_scancode_flag`) and the Dvorak run of AC WIN-DELIV-04.
2. **Clipboard contention and clipboard managers** — SCOPE.md §7 risk 5. Likelihood high (a Win+V
   history service is on by default on Windows 11), impact medium: intermittent copy failures,
   which §P8 turns into a safe no-paste plus an error cue. Mitigation: the bounded schedule of
   WIN-DELIV-01 and the identical-rewrite rule of WIN-DELIV-P8. Covered by AC WIN-DELIV-01
   (the two hog cases).
3. **The injected chord re-triggers the hotkey.** Likelihood high if the tag is dropped — a binding
   containing left Ctrl matches our own injection. Impact high: a paste starts a new utterance,
   which pastes, which starts another; a feedback loop the user can only break by killing the
   daemon. Mitigation: WIN-DELIV-P5, with `INJECT_TAG` exported for the WIN-INPUT hook to filter on.
   Covered by AC WIN-DELIV-02 (`test_every_built_input_carries_the_inject_tag`) on this side; the
   filtering half is WIN-INPUT's acceptance criterion.
4. **`GlobalAlloc` ownership mistakes.** Likelihood medium — the free-iff-NULL rule is the single
   easiest Win32 clipboard bug to get wrong. Impact high: a double free corrupts the daemon's heap
   and crashes it mid-utterance (and with §D2 there is no auto-restart until next logon); the
   opposite error leaks a few hundred bytes per utterance. Mitigation: WIN-DELIV-P2, fresh handle
   per attempt. Covered by AC WIN-DELIV-01 (`test_repeated_copies_do_not_corrupt_the_heap`).
5. **A failed write leaves the clipboard empty.** Likelihood low — it needs `SetClipboardData` to
   fail after `EmptyClipboard` succeeded, which the pre-allocation of WIN-DELIV-P1 makes rare.
   Impact medium: the user loses their prior clipboard content *and* gets no transcript, so the
   documented recovery path is gone for that utterance. Mitigation: allocate before opening; the
   error cue and toast (WIN-FEED) still fire on the `False` return. Covered by AC WIN-DELIV-01,
   which asserts sentinel `A` survives a contention failure.
6. **UIPI blocks the chord against an elevated foreground window** — SCOPE.md §7 risk 1, accepted
   scope per README §D7. Likelihood medium (any focused admin console), impact medium: no paste,
   but the clipboard write is not blocked, so the recovery path holds. Mitigation: the checked
   return of WIN-DELIV-P4 turns a blocked chord into a raised error rather than a false
   `DELIVERED`; doctor surfacing the integrity level is WIN-DIAG's. Covered by AC WIN-DELIV-04
   (the `SetForegroundWindow` skip guard keeps the gate honest) and AC WIN-DELIV-02.
7. **Read-back confirming another application's write.** Likelihood very low — it requires an
   interloper to write byte-identical text in the millisecond between our write and our read-back.
   Impact none in the dangerous direction: a confirmation means the clipboard held our exact text,
   so the chord can only paste that. The realistic race outcome is a false *negative*, which is the
   safe side of §P8. Mitigation: WIN-DELIV-P6 and P8, with the sequence-number delta logged as a
   numeric metric. Covered by AC WIN-DELIV-01's `confirm_readback` tests; the residual read-back-to-
   chord TOCTOU is documented as out of scope and is identical on Linux.
8. **`tests/platform/test_platform.py` pulls a contained domain into the both-suites gate.**
   Likelihood certain, impact low: WIN-DELIV-03 needs a green Linux smoke run it does not otherwise
   require. Mitigation: confine the edit to the two delivery assertions and keep every other
   Windows-specific test under `tests/platform/windows/`, so later domains inherit the same one-file
   cost rather than a growing one. Covered by AC WIN-DELIV-03's regression guard.
