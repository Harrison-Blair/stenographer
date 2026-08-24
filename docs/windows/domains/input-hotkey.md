# Windows Parity — Input & Hotkey

This domain builds the Windows key vocabulary and the push-to-talk listener: a generated
`KEY_*` ↔ scan/VK translation table, the `WH_KEYBOARD_LL` hook with its pump thread and
dispatch queue, and the provider wiring that turns `hotkey_listener()` from
`UnsupportedPlatformError` into a working listener. Blast area is contained inside
`platform/windows/` plus two new pure-test files and one generator script — no core module is
edited, no Protocol in `platform/base.py` changes, and every item degrades to today's stub
behavior if reverted (README §T). Binding capture (WIN-DIAG) and the paste chord (WIN-DELIV)
consume this domain's table and hook plumbing but are not owned here.

## Designed source tree

| Path | Marker | Role |
|---|---|---|
| `src/stenographer/platform/windows/vk.py` | NEW | Generated pure scan/VK → evdev-code tables and the `translate()` resolver; stdlib-only and importable on every OS, exactly like `keycodes.py`. |
| `scripts/gen_vk_keycodes.py` | NEW | Emits `vk.py` from a hand-authored mapping literal, validated against `stenographer.keycodes`; `--check` fails on staleness, mirroring `scripts/gen_keycodes.py`. |
| `src/stenographer/platform/windows/hotkey.py` | NEW | `LowLevelHotkeyListener` — hook thread + `GetMessage` pump, enqueue-only callback, dispatch thread, release watchdog, `can_install_hook()`. |
| `src/stenographer/platform/windows/__init__.py` | EDIT | Provider wiring for `hotkey_listener()`; `hotkey_devices()` docstring pinned to README §D5. |
| `tests/platform/windows/` | NEW | Windows-only tests (`conftest.py` blanket-ignores off `win32`, mirroring `tests/platform/linux/conftest.py`) plus the interactive hook smoke. |
| `tests/platform/test_vk_table.py` | NEW | Cross-platform pure tests for `vk.py`. It sits *outside* `windows/` on purpose: `vk.py` is pure stdlib data, so its drift and coverage tests must run on both CI legs, and `tests/platform/test_platform.py` already imports the Windows provider on Linux. This file is an addition to README §T's test rows. |

`keys()` needs no edit: the stub already returns the core `StaticKeyTable`, which is the correct
end state — the `KEY_*` vocabulary is core data, not a host capability (README §T note,
AGENTS.md *Platform boundary*). A Windows-specific `KeyTable` would wrongly narrow the
vocabulary that `config.py` and `setup` must still parse and render.

## Architecture principles

Global rules are cited, not restated: §P1 (lazy provider imports), §P2 (core stays host-blind),
§P4 (the hook callback only enqueues), §P5 (every backend keeps a pure unit target), §P6 (no
mock theater), §P10 (SPDX and tooling).

- **WIN-INPUT-P1 — Thread confinement is the callback's only concurrency tool.** §P4 forbids
  locks and I/O in the hook callback; the positive rule is that the callback may read and mutate
  *only* state owned exclusively by the hook thread (`DownKeys`, the resync flag) plus one
  `queue.SimpleQueue.put_nowait`. Any new field the callback touches must be provably written by
  no other thread. A reviewer checks this by listing every attribute the callback names.
- **WIN-INPUT-P2 — The hook is non-grabbing.** The callback returns `CallNextHookEx(...)` on
  every path, including the error, untranslatable, injected, and ignored-scan paths. It never
  returns a non-zero `LRESULT`. This is the Windows spelling of "the device is never grabbed:
  non-chord keys pass through" (`platform/linux/hotkey.py`); swallowing a key would make the
  bound key stop working in every application while the daemon runs.
- **WIN-INPUT-P3 — Auto-repeat becomes evdev value 2, never a second value 1.** Windows delivers
  held keys as repeated `WM_KEYDOWN` with no repeat flag in `KBDLLHOOKSTRUCT`. `ChordTracker`
  reads a second value-1 for a held code as a *lost release* and synthesizes stop-then-start, so
  forwarding repeats verbatim would stop and restart recording tens of times per second while
  the user holds the key. The listener classifies repeats against `DownKeys` and emits 2, which
  `ChordTracker._key_event` ignores.
- **WIN-INPUT-P4 — Injected events are dropped before enqueue.** Any event with
  `LLKHF_INJECTED` (0x10) is passed through and not enqueued. Linux gets this structurally — the
  uinput injector advertises only `KEY_LEFTSHIFT`/`KEY_INSERT`, so `is_main_keyboard()` excludes
  it from `auto_detect_paths()` and the listener never reads it back. A global hook has no device
  to exclude (README §D5), so the flag is the whole defense against the daemon's own `SendInput`
  chord re-triggering the binding.
- **WIN-INPUT-P5 — Physical-key identity comes from the scan code, not the virtual key.** VK
  codes are layout-dependent (`KEY_A`'s VK is the physical Q key on AZERTY) while evdev codes are
  physical-position codes that equal set-1 scan codes across the base block. Resolution order is
  `(extended, scan_code)` first, `vk` only as the fallback for events with `scan_code == 0` or an
  unmapped scan. A binding therefore names the same physical key on Windows and Linux.
- **WIN-INPUT-P6 — No second state machine.** The provider registers exactly one synthetic
  device id (`HOOK_DEVICE_ID`) in `_held_by_device` and calls
  `ChordTracker._key_event(HOOK_DEVICE_ID, code, value)`. Held-key union, edge dispatch under the
  daemon lock, stuck-key synthesis and `wait_binding_released` stay in `stenographer.hotkey`; the
  provider adds no held-key set, no edge computation, and no mode logic.
- **WIN-INPUT-P7 — Synthesize releases only.** Recovery paths (watchdog, hook reinstall, stop)
  may emit value-0 events and may clear state; they never emit a value-1 event. A synthesized
  press would start a recording the user did not ask for, with an open microphone.
- **WIN-INPUT-P8 — VK and scan numerals live only in `vk.py`.** `hotkey.py` contains window
  message, hook and flag constants (`WH_KEYBOARD_LL`, `WM_KEYUP`, `LLKHF_*`) and no key-code
  literal. Grep for `0x` in `hotkey.py` is the review check.
- **WIN-INPUT-P9 — `hotkey.device` degrades in the provider, once.** Per README §D5 and §P2 the
  Linux-only key is ignored with exactly one `logging.warning` per process, at listener
  construction. It is never a `ConfigError`, never an exception, and never reaches `config.py`.

## Functional criteria

### WIN-INPUT-01 — Generate the evdev ↔ Windows key translation table
Phase: 1   Depends on: none
Files: `scripts/gen_vk_keycodes.py` (NEW), `src/stenographer/platform/windows/vk.py` (NEW),
`tests/platform/test_vk_table.py` (NEW)
Pure tests: `tests/platform/test_vk_table.py::test_base_scan_codes_are_identity_with_evdev`,
`::test_generated_module_is_not_stale`, `::test_required_binding_vocabulary_is_covered`,
`::test_translate_prefers_scan_code_over_virtual_key`,
`::test_extended_flag_separates_navigation_from_numpad`,
`::test_generic_modifier_vks_resolve_by_side`, `::test_fake_shift_scans_are_ignored`,
`::test_reverse_tables_round_trip_and_survive_alias_names`
Smoke: none — the module is pure static data with no host call; every host-observable
consequence is covered by `WIN-INPUT-02`'s `test_key_atlas` (see Acceptance criteria).
Done when: `.venv/bin/python scripts/gen_vk_keycodes.py --check` passes on a clean tree and
`translate(vk=0xA3, scan_code=0x1D, extended=True)` returns 97 (`KEY_RIGHTCTRL`, the default
binding) on Linux and Windows alike.

The generator owns three hand-authored literals and no runtime discovery: `_EXTENDED`
(`E0`-prefixed scan → evdev name, e.g. `0x1D → KEY_RIGHTCTRL`, `0x1C → KEY_KPENTER`,
`0x52 → KEY_INSERT`, `0x38 → KEY_RIGHTALT`, `0x5B → KEY_LEFTMETA`, `0x5D → KEY_COMPOSE`, the
media/browser block), `_SCAN_EXCEPTIONS` (base-block scans that are *not* their evdev code, plus
`KEY_PAUSE` and `KEY_SYSRQ`), and `_VK_FALLBACK` (VK → evdev name for events arriving with
`scan_code == 0`, plus generic `VK_SHIFT`/`VK_CONTROL`/`VK_MENU`). It emits, sorted and
`MappingProxyType`-wrapped: `SCAN_TO_EVDEV`, `EXTENDED_SCAN_TO_EVDEV`, `VK_TO_EVDEV`,
`EVDEV_TO_SCAN` (code → `(scan, extended)`, consumed by WIN-DELIV for `KEYEVENTF_SCANCODE`),
`EVDEV_TO_VK` (code → VK, consumed by WIN-DIAG), `IGNORED_EXTENDED_SCANS = (0x2A, 0x36)` (the
driver-inserted "fake shift" around numpad keys), and the pure resolver
`translate(vk: int, scan_code: int, extended: bool) -> int | None`. It validates before writing:
every evdev name it mentions exists in `stenographer.keycodes.KEY_CODES`, no scan maps to two
codes within one table, and every VK is in `0x01..0xFE`. `--check` emits a unified diff and
exits non-zero, byte-for-byte the `gen_keycodes.py` contract.

### WIN-INPUT-02 — Implement the `WH_KEYBOARD_LL` listener
Phase: 1   Depends on: WIN-INPUT-01
Files: `src/stenographer/platform/windows/hotkey.py` (NEW), `tests/platform/windows/conftest.py`
(NEW), `tests/platform/windows/test_hotkey_listener.py` (NEW),
`tests/platform/windows/test_hotkey_smoke.py` (NEW)
Pure tests: `tests/platform/windows/test_hotkey_listener.py::test_repeat_keydown_becomes_value_two`,
`::test_release_clears_down_state_so_the_next_press_is_value_one`,
`::test_resync_request_clears_down_state_on_the_next_event`,
`::test_dispatch_feeds_the_tracker_and_fires_one_edge_pair`,
`::test_dispatch_stops_on_the_sentinel_without_touching_the_tracker`,
`::test_injected_events_never_reach_the_queue`
Smoke: `windows-hotkey-hook` (`test_injected_chord_never_fires_an_edge`,
`test_pump_starts_and_stops_cleanly`, `test_hook_survives_a_sustained_event_stream`,
`test_physical_press_drives_start_then_stop`, `test_key_atlas`)
Done when: on a real Windows desktop, holding `KEY_RIGHTCTRL` fires exactly one `on_start` and
releasing it fires exactly one `on_stop`, and `stop()` returns within 2 s with both threads
joined and no keystroke lost by any other application.

`LowLevelHotkeyListener(ChordTracker)` takes the `Platform.hotkey_listener` keyword signature
(`chord`, `device`, `on_start`, `on_stop`, `lock`). `start()` clears `_stop_event`, registers
`_held_by_device = {HOOK_DEVICE_ID: set()}`, creates a `queue.SimpleQueue`, spawns
`hotkey-dispatch` and `hotkey-hook` (both `daemon=True`), and blocks on an installation
`threading.Event` for 2 s, raising `UnsupportedPlatformError` with `GetLastError()` when
`SetWindowsHookExW` returned NULL. The pump thread resolves `ctypes.WinDLL("user32")` /
`("kernel32")` inside its body (§P1), builds the `WINFUNCTYPE(LRESULT, c_int, WPARAM, LPARAM)`
callback and stores it on `self` so it is never garbage-collected while installed, calls
`SetWindowsHookExW(WH_KEYBOARD_LL=13, proc, GetModuleHandleW(None), 0)`, records
`GetCurrentThreadId()`, runs `while GetMessageW(byref(MSG()), None, 0, 0) > 0: pass`, and calls
`UnhookWindowsHookEx` in a `finally`. `stop(timeout)` sets `_stop_event`, posts
`PostThreadMessageW(thread_id, WM_QUIT=0x0012, 0, 0)`, pushes the dispatch sentinel, joins both
threads, clears `_held`/`_held_by_device` and sets `_active = False` — the same teardown contract
`EvdevHotkeyListener.stop` implements. `is_running` reports the pump thread's liveness.

The callback reads `KBDLLHOOKSTRUCT` (`vkCode`, `scanCode`, `flags`, `time`, `dwExtraInfo`) via
`ctypes.cast(lParam, POINTER(KBDLLHOOKSTRUCT))` and, in order: returns `CallNextHookEx` when
`nCode != HC_ACTION (0)`; drops `flags & LLKHF_INJECTED (0x10)`; drops
`extended and scan_code in IGNORED_EXTENDED_SCANS`; derives `is_down` from `wParam`
(`WM_KEYDOWN 0x0100`, `WM_SYSKEYDOWN 0x0104` down; `WM_KEYUP 0x0101`, `WM_SYSKEYUP 0x0105` up);
calls `vk.translate(...)` and drops `None`; classifies the value through `DownKeys.value_for(code,
is_down)`; `put_nowait((code, value))`; and returns `CallNextHookEx` (§P4, WIN-INPUT-P1/P2).
`DownKeys` is the pure unit target: a `set[int]` plus `value_for()` returning 1 on a first
keydown, 2 on a repeat, 0 on a keyup, and a `request_resync()` bool flag the callback consumes
(WIN-INPUT-P3). The dispatch thread loops `queue.get()`, exits on the `None` sentinel, and calls
`self._key_event(HOOK_DEVICE_ID, code, value)`, exiting when it returns `False`
(WIN-INPUT-P6). Module-level `can_install_hook() -> bool` installs and immediately unhooks on a
short-lived pump thread; WIN-DIAG's `probe_host().hotkey_access_ok` calls it rather than
duplicating the prototypes.

### WIN-INPUT-03 — Wire the provider and degrade `hotkey.device`
Phase: 1   Depends on: WIN-INPUT-02
Files: `src/stenographer/platform/windows/__init__.py` (EDIT),
`src/stenographer/platform/windows/hotkey.py` (EDIT),
`tests/platform/windows/test_hotkey_wiring.py` (NEW)
Pure tests: `tests/platform/windows/test_hotkey_wiring.py`
`::test_device_warning_text_names_the_key_and_linux`,
`::test_device_warning_is_none_for_empty_and_unset_device`,
`::test_device_warning_is_logged_exactly_once_per_process`,
`::test_untranslatable_chord_keys_are_named_in_one_warning`,
`::test_translatable_chord_produces_no_warning`
Smoke: `windows-hotkey-hook::test_provider_builds_a_running_listener`
Done when: `WindowsPlatform().hotkey_listener(...)` returns a `HotkeyListener` instead of
raising, `tests/platform/test_platform.py` still passes unchanged on both hosts, and a config
with `hotkey.device = "/dev/input/event3"` starts normally with one warning in the log and no
`ConfigError`.

`hotkey_listener()` lazy-imports `LowLevelHotkeyListener` and constructs it (§P1). Two pure
helpers live in `hotkey.py` and are called from the listener's `__init__`:
`device_ignored_warning(device: str | None) -> str | None` returns the message text for a
non-empty device and `None` otherwise, guarded by a module-level `_DEVICE_WARNED` bool so the
process logs it once (WIN-INPUT-P9); `untranslatable_keys(chord: frozenset[int], keys: KeyTable)
-> tuple[str, ...]` returns the canonical names in the chord that have no `EVDEV_TO_SCAN` entry,
logged as one warning so a binding that can never fire says so at startup instead of failing
silently. `hotkey_devices()` keeps returning `[]`; its docstring cites README §D5 and names Raw
Input as the deferred door.

### WIN-INPUT-04 — Recover stuck chords and a silently removed hook
Phase: 1   Depends on: WIN-INPUT-02
Files: `src/stenographer/platform/windows/hotkey.py` (EDIT),
`tests/platform/windows/test_hotkey_watchdog.py` (NEW)
Pure tests: `tests/platform/windows/test_hotkey_watchdog.py`
`::test_stale_releases_names_only_tracked_keys_that_are_physically_up`,
`::test_stale_releases_is_empty_when_the_chord_is_physically_held`,
`::test_watchdog_never_proposes_a_press`,
`::test_reinstall_is_rate_limited_and_needs_consecutive_misses`,
`::test_watchdog_holds_off_while_the_queue_is_non_empty`
Smoke: `windows-hotkey-hook::test_lost_keyup_is_reconciled`
Done when: with a chord key's release deliberately withheld from the daemon, recording stops
within 200 ms of the key being physically up, and the next press starts a new recording.

The watchdog runs on a `hotkey-watchdog` thread at `_WATCHDOG_INTERVAL_SECONDS = 0.05`. Each
tick, if the dispatch queue is empty, it samples `user32.GetAsyncKeyState(vk)` for
`EVDEV_TO_VK[code]` over the chord only and feeds the pure
`stale_releases(tracked: frozenset[int], physically_down: frozenset[int], chord: frozenset[int])
-> frozenset[int]`; each returned code is fed as `_key_event(HOOK_DEVICE_ID, code, 0)` and
triggers `DownKeys.request_resync()` so the hook thread rebuilds its own down-set on the next
event (WIN-INPUT-P1/P7). The queue-empty precondition removes the race where a keyup is enqueued
but not yet dispatched. The same loop detects a hook Windows removed silently: when the *whole*
chord reads physically down while the tracker holds nothing for `_INACTIVITY_POLLS = 20`
consecutive ticks, it logs one warning and asks the pump thread to unhook and reinstall, at most
once per `_REINSTALL_COOLDOWN_SECONDS = 30.0`, decided by the pure
`should_reinstall(consecutive_misses: int, seconds_since_last: float) -> bool`.

## Acceptance criteria

### WIN-INPUT-01

Pure tests, each with the broken behavior it must be seen to fail against (§P6) — all run on
both CI legs because `vk.py` is stdlib-pure:

- `test_base_scan_codes_are_identity_with_evdev` — asserts every non-extended entry of
  `SCAN_TO_EVDEV` in `0x01..0x58` equals its evdev code (`0x1E → 30`, `0x1D → 29`,
  `0x1C → 28`, `0x45 → 69`), except the codes listed in an explicit `_EXCEPTIONS` constant in
  the test. Fails against a generator that transcribes a scan code by hand and fat-fingers one
  digit, and against a mapping silently authored from VK codes instead of scan codes.
- `test_generated_module_is_not_stale` — runs `gen_vk_keycodes.render()` and compares to the
  checked-in file text. Fails against a hand-edit of `vk.py` (the exact drift failure
  `test_keycodes_drift.py` catches for the core table).
- `test_required_binding_vocabulary_is_covered` — a literal list of 104-key US layout names plus
  `KEY_F13..KEY_F24`, `KEY_102ND`, `KEY_COMPOSE`, `KEY_LEFTMETA`, `KEY_RIGHTMETA`, `KEY_SYSRQ`,
  `KEY_PAUSE`, the `KEY_KP*` block and the media/browser block must all appear in
  `EVDEV_TO_SCAN`. Fails against a table that covers letters and modifiers only — the state in
  which a user binding `KEY_KPENTER` gets a listener that never fires.
- `test_translate_prefers_scan_code_over_virtual_key` — with a VK whose fallback entry names a
  different key from its scan entry, `translate()` returns the scan-derived code. Fails against
  a resolver that checks `VK_TO_EVDEV` first, which is the layout-dependence bug of
  WIN-INPUT-P5.
- `test_extended_flag_separates_navigation_from_numpad` — `translate(vk=VK_INSERT, scan=0x52,
  extended=False) == KEY_KP0` and `extended=True == KEY_INSERT`; likewise `0x1C` →
  `KEY_ENTER`/`KEY_KPENTER` and `0x1D` → `KEY_LEFTCTRL`/`KEY_RIGHTCTRL`. Fails against a
  resolver that ignores `LLKHF_EXTENDED`, which would make the *default* binding
  (`KEY_RIGHTCTRL`) fire on left control.
- `test_generic_modifier_vks_resolve_by_side` — `VK_CONTROL`/`VK_MENU` with `scan_code == 0`
  resolve left vs right by the extended flag and `VK_SHIFT` by scan `0x2A`/`0x36`. Fails against
  a fallback that maps generic modifier VKs to a single side.
- `test_fake_shift_scans_are_ignored` — `(0x2A, extended=True)` and `(0x36, extended=True)` are
  in `IGNORED_EXTENDED_SCANS` and not in `EXTENDED_SCAN_TO_EVDEV`. Fails against a table that
  resolves them to `KEY_LEFTSHIFT`, which would inject a phantom shift press on every shifted
  numpad key.
- `test_reverse_tables_round_trip_and_survive_alias_names` — for every code in `EVDEV_TO_SCAN`,
  `translate(EVDEV_TO_VK[code], scan, extended) == code`, and the check is keyed by *code*, so
  aliased spellings (`KEY_MUTE` is code 113 whose canonical `CODE_NAMES` entry is
  `KEY_MIN_INTERESTING`) do not break it. Fails against a generator that builds the reverse table
  keyed by name and drops or duplicates aliased codes.

Observable: `.venv/bin/python scripts/gen_vk_keycodes.py` rewrites `vk.py` deterministically,
`--check` is clean on a fresh checkout, and `ruff check`/`format --check` pass on the emitted
file. No smoke case: the module performs no host call, so a real-machine case could only assert
what the pure tests already assert; the *hardware* facts it encodes are settled by
`test_key_atlas` under WIN-INPUT-02.

### WIN-INPUT-02

Pure tests (in `tests/platform/windows/`, collected only on `win32`; no Win32 call is made —
they drive `DownKeys`, a real `queue.SimpleQueue`, and a real `ChordTracker` built with a real
`threading.RLock` and list-appending callbacks, exactly as `tests/test_hotkey.py` drives the
tracker):

- `test_repeat_keydown_becomes_value_two` — `DownKeys.value_for(30, True)` returns 1 then 2 then
  2. Fails against a listener that forwards every `WM_KEYDOWN` as 1; the failure the test must be
  seen to produce is the tracker emitting `["start", "stop", "start", "stop", "start"]` for one
  held key (WIN-INPUT-P3).
- `test_release_clears_down_state_so_the_next_press_is_value_one` — down, up, down yields
  `1, 0, 1`. Fails against a `DownKeys` that never discards on keyup, which would make the second
  real press invisible.
- `test_resync_request_clears_down_state_on_the_next_event` — after `request_resync()`, a keydown
  for a code still in the set returns 1, not 2. Fails against a resync flag that is set but never
  consumed — the state in which WIN-INPUT-04's recovery cannot re-arm the key.
- `test_dispatch_feeds_the_tracker_and_fires_one_edge_pair` — pushing
  `(KEY_RIGHTCTRL, 1), (KEY_RIGHTCTRL, 2), (KEY_RIGHTCTRL, 0)` through the dispatch loop yields
  exactly `["start", "stop"]`. Fails against a dispatch loop that passes a device id not
  registered in `_held_by_device` (`_key_event` returns `False` and nothing fires at all —
  WIN-INPUT-P6).
- `test_dispatch_stops_on_the_sentinel_without_touching_the_tracker` — the `None` sentinel ends
  the loop and fires no callback. Fails against a loop that unpacks the sentinel and raises, or
  that only checks `_stop_event` and so blocks forever in `queue.get()` on `stop()`.
- `test_injected_events_never_reach_the_queue` — the pure classifier
  `should_enqueue(n_code, flags, extended, scan_code)` returns `False` for `LLKHF_INJECTED`,
  `n_code < 0`, and ignored extended scans, and `True` otherwise. Fails against a callback that
  tests `flags == LLKHF_INJECTED` instead of masking, so an injected *extended* key
  (`flags == 0x11`) slips through — precisely the daemon's own Ctrl+V chord (WIN-INPUT-P4).

Smoke suite `windows-hotkey-hook` — `tests/platform/windows/test_hotkey_smoke.py`,
`pytest.mark.integration`, module-level skip unless `STENOGRAPHER_INTEGRATION=1`, on a real
interactive Windows desktop session (never CI, per AGENTS.md *Commands*):

- `test_pump_starts_and_stops_cleanly` — `start()`; assert `is_running`; `stop(timeout=2.0)`;
  assert not `is_running` and that both threads are joined. Repeat five times in one process to
  prove the hook handle and callback reference are released each cycle. Observable failure of a
  leak: the fifth `start()` raises or `stop()` times out.
- `test_hook_survives_a_sustained_event_stream` — with the listener running, drive 2000
  `SendInput` key events over ~10 s for a key *outside* the chord, then perform the interactive
  press of `test_physical_press_drives_start_then_stop`. Proves Windows did not silently remove
  the hook for exceeding the callback budget (SCOPE §7 risk 3) and that the callback reference
  survived a GC pass (`gc.collect()` is called mid-stream).
- `test_injected_chord_never_fires_an_edge` — with the chord set to `KEY_LEFTCTRL+KEY_V` (the
  worst case: identical to WIN-DELIV's paste chord), send that chord via `SendInput` ten times
  and assert `on_start` was never called within 1 s. This is the automated proof of
  WIN-INPUT-P4; it is also why the physical-press case below cannot be automated — software
  cannot synthesize a non-injected keystroke, and no test backdoor is added to allow it.
- `test_physical_press_drives_start_then_stop` — additionally guarded by
  `STENOGRAPHER_SMOKE_INTERACTIVE=1`; prints `press and hold Right Ctrl for one second, then
  release` and waits up to 15 s, asserting exactly one start, then one stop, and that
  `wait_binding_released(timeout=1.0)` returns `True`. The one-second hold is load-bearing: it
  spans several auto-repeat ticks, so a WIN-INPUT-P3 regression fails here as extra edges.
- `test_key_atlas` — interactive; prompts for `Right Ctrl`, `Left Ctrl`, `Right Alt`, `Enter`,
  `Numpad Enter`, `Insert`, `Numpad 0` (NumLock on and off), `Print Screen`, `Pause`, `Menu` and
  asserts each resolves to the expected `KEY_*` name. This is where the two hardware facts the
  plan cannot assert from a desk are settled — the flags Windows reports for Pause
  (`0xE1`-prefixed) and Print Screen — and a mismatch is fixed in `_EXTENDED`/`_VK_FALLBACK`,
  regenerating `vk.py`.

Observable: `stenographer run` on Windows no longer aborts at listener construction; pressing the
bound key logs the same `hotkey: mode=hold` line and drives the same daemon edges as Linux, and
every other application continues to receive the bound key (WIN-INPUT-P2 — verified by typing in
Notepad with the daemon running).

### WIN-INPUT-03

Pure tests (Windows-collected, no Win32 call — `device_ignored_warning` and
`untranslatable_keys` are pure functions, and the once-per-process assertion uses `caplog`, the
real logging framework, over two real listener constructions; `__init__` installs no hook):

- `test_device_warning_text_names_the_key_and_linux` — the message contains `hotkey.device` and
  says the key is Linux-only and ignored. Fails against a silent ignore, which is the state where
  a user's explicit device setting appears to be honored and is not (README §D5).
- `test_device_warning_is_none_for_empty_and_unset_device` — `None` and `""` produce no warning.
  Fails against a truthiness bug that warns on every Windows start.
- `test_device_warning_is_logged_exactly_once_per_process` — two listeners, one record. Fails
  against a per-instance guard, which in `setup`'s flow would warn on each rebuild.
- `test_untranslatable_chord_keys_are_named_in_one_warning` — a chord containing a code absent
  from `EVDEV_TO_SCAN` produces one warning naming it. Fails against a listener that starts
  happily on a binding that can never fire.
- `test_translatable_chord_produces_no_warning` — the default `KEY_RIGHTCTRL` chord logs nothing.
  Fails against an over-broad check that warns on every start.

Smoke `windows-hotkey-hook::test_provider_builds_a_running_listener` — build through
`WindowsPlatform().hotkey_listener(chord=parse_binding("KEY_RIGHTCTRL", plat.keys()), device=None,
...)`, start, assert `is_running`, stop. Proves the lazy import resolves and the provider passes
the keyword contract; a signature drift from `platform/base.py` fails here as a `TypeError`.

Observable: `tests/platform/test_platform.py`
`::test_windows_stub_conforms_and_reports_everything_unavailable` is updated only where it
asserts `hotkey_listener` raises, and every other assertion in it still passes byte-identically
on Linux; `stenographer --help` on Linux and Windows still imports no `ctypes.windll` (§P1,
proved by the existing CLI import test).

### WIN-INPUT-04

Pure tests (Windows-collected; `stale_releases` and `should_reinstall` take plain sets, ints and
floats and call nothing — the `GetAsyncKeyState` sample is the caller's argument, which is why
the policy is testable without mocking Win32, per §P5):

- `test_stale_releases_names_only_tracked_keys_that_are_physically_up` — tracked `{29, 97}`,
  physically down `{29}`, chord `{97}` yields `{97}`. Fails against a reconciler that returns
  every tracked key not physically down, which would drop keys outside the chord the listener
  never tracked in the first place.
- `test_stale_releases_is_empty_when_the_chord_is_physically_held` — the normal held case
  proposes nothing. Fails against an inverted comparison, whose symptom is a recording that stops
  50 ms after it starts, every time.
- `test_watchdog_never_proposes_a_press` — every value the reconciliation step emits is 0
  (WIN-INPUT-P7). Fails against a "resync to physical truth" implementation that also emits
  value-1 events for keys physically down but untracked — an unrequested recording with a live
  microphone.
- `test_reinstall_is_rate_limited_and_needs_consecutive_misses` —
  `should_reinstall(19, 60.0)` is `False`, `should_reinstall(20, 60.0)` is `True`,
  `should_reinstall(20, 5.0)` is `False`. Fails against a reinstall on the first miss, which
  would tear the hook down during a normal fast keypress.
- `test_watchdog_holds_off_while_the_queue_is_non_empty` — the tick predicate returns no
  proposals when the queue reports non-empty. Fails against a watchdog that races the dispatch
  thread and truncates the last 50 ms of every utterance.

Smoke `windows-hotkey-hook::test_lost_keyup_is_reconciled` — interactive
(`STENOGRAPHER_SMOKE_INTERACTIVE=1`): with the listener running, the operator holds Right Ctrl,
then the test suppresses the keyup by asking the operator to release the key while an
elevated Command Prompt has focus (the genuine UIPI scenario of SCOPE §7 risk 1 — a real
condition, not a simulated one). Assert `on_stop` fires within 200 ms of the release and that a
subsequent press fires `on_start` again. Without WIN-INPUT-04 this case hangs until
`audio.max_recording_seconds` and the following press produces nothing.

Observable: with the daemon running and an elevated window taking focus mid-press, recording ends
promptly instead of running to the max-duration cap, and the log carries one
`hotkey: reconciled stale release` line — a numeric/structural log line only (§P9).

## Risks

| # | Risk | Likelihood | Impact | Mitigation | Covered by |
|---|---|---|---|---|---|
| 1 | Auto-repeat forwarded as a second value-1 keydown turns `ChordTracker`'s stuck-key synthesis into a stop/start storm while the key is held. | High if unhandled — repeats are the default for every held key | Critical: hold-mode dictation is unusable and every storm cycle starts and abandons an ASR job | WIN-INPUT-P3: `DownKeys` classifies repeats as value 2, which `_key_event` ignores | `WIN-INPUT-02::test_repeat_keydown_becomes_value_two`, and the one-second hold in `test_physical_press_drives_start_then_stop` |
| 2 | The daemon's own `SendInput` paste chord re-enters the hook and re-triggers the binding — Linux avoids this by device exclusion, which a global hook cannot do. | Medium (certain if the binding shares keys with the chord) | High: a paste loop that re-arms recording after every delivery | WIN-INPUT-P4: mask `LLKHF_INJECTED` before enqueue | `WIN-INPUT-02::test_injected_events_never_reach_the_queue` and smoke `test_injected_chord_never_fires_an_edge` |
| 3 | SCOPE §7 risk 3 (silent hook removal). | Low once §P4 holds | Critical: dictation dies with no error and no log | Enqueue-only callback (§P4, WIN-INPUT-P1) plus the inactivity detector and rate-limited reinstall of WIN-INPUT-04 | `WIN-INPUT-04::test_reinstall_is_rate_limited_and_needs_consecutive_misses`, smoke `test_hook_survives_a_sustained_event_stream` |
| 4 | SCOPE §7 risk 1 (UIPI) additionally *loses the keyup*, leaving the chord latched. | Medium (any elevated window stealing focus mid-press) | High: recording runs to `audio.max_recording_seconds`, then the key appears dead | WIN-INPUT-04's release watchdog, queue-empty-gated and release-only | `WIN-INPUT-04::test_stale_releases_*` and smoke `test_lost_keyup_is_reconciled` |
| 5 | VK-based translation is keyboard-layout dependent, so a binding names a different physical key on AZERTY/QWERTZ than on Linux. | High on non-US layouts | Medium: the bound key silently does nothing; a captured binding is not portable | WIN-INPUT-P5: resolve `(extended, scan_code)` first, VK only as fallback | `WIN-INPUT-01::test_translate_prefers_scan_code_over_virtual_key`, `::test_base_scan_codes_are_identity_with_evdev` |
| 6 | Driver-inserted "fake shift" (`E0 2A` / `E0 36`) around shifted numpad keys enters the held-key union as a phantom `KEY_LEFTSHIFT`. | Medium (numpad + shift users) | Medium: a chord containing shift fires without the user pressing shift | `IGNORED_EXTENDED_SCANS` filtered in the callback before enqueue | `WIN-INPUT-01::test_fake_shift_scans_are_ignored`, `WIN-INPUT-02::test_injected_events_never_reach_the_queue` |
| 7 | The `WINFUNCTYPE` callback object is garbage-collected while the hook is installed, crashing the process on the next keystroke. | Medium — the classic ctypes hook footgun, invisible until GC runs | Critical: hard process crash mid-dictation | Store the callback on the listener instance for the hook's whole lifetime; never build it inline in the `SetWindowsHookExW` call | Smoke `test_hook_survives_a_sustained_event_stream` (calls `gc.collect()` mid-stream) and the five-cycle `test_pump_starts_and_stops_cleanly` |
| 8 | `stop()` deadlocks: the pump thread misses `WM_QUIT` (posted before the pump reached `GetMessageW`) or the dispatch thread blocks in `queue.get()`. | Medium | High: `stenographer run` never exits, and the single-instance lock blocks the next start | Post `WM_QUIT` only after the installation `Event` is set, always push the dispatch sentinel, and join with the caller's timeout — the `stop(timeout=2.0)` contract of `platform/base.py` | Smoke `test_pump_starts_and_stops_cleanly` (five cycles, each asserting both threads joined) |
| 9 | `Pause` and `Print Screen` report flags this plan predicts rather than measures, so those two names resolve wrongly. | Medium | Low: only bindings naming those keys | Settle on hardware, then regenerate `vk.py` from `_EXTENDED`/`_VK_FALLBACK` — no code change | `WIN-INPUT-02::test_key_atlas` |
