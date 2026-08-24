# Windows Parity — Overlay

Scope: the optional lifecycle pill on Windows — the additive protocol vocabulary in `status.py`, the
`OverlayBackendSpec` returned by `WindowsPlatform.overlay_backends()`, and `overlay/win32.py`, a
layered click-through helper backend that blits the existing Pillow renderer through
`UpdateLayeredWindow`. Blast area is **core-touching**: `status.py` and `overlay/supervisor.py` are
executed by Linux, so every item that touches them carries the §P7 burden and the "both suites" row
of §D8. Everything else in the overlay stack — the mailbox, generation and coalescing policy in
`supervisor.py`, `spectrum.py`, `render.py`, `entry.py`, and the NDJSON machinery in `status.py`
below the enums — is unchanged; `render.premultiplied_argb32(image, byteorder="little")` already
emits exactly the premultiplied BGRA layout `UpdateLayeredWindow` wants, so no new conversion math
enters the renderer. The domain is severable in the sense SCOPE.md §3 claims: drop all six items and
`overlay_backends()` stays `()`, `supervisor._select_backend` raises, the helper answers
`unavailable(backends_unavailable)`, the supervisor takes the expected-exit path and disables the
mailbox — `NullStatusSink` semantics, dictation untouched.

## Designed source tree

Rows this domain owns, from README §T, plus one addition §T does not carry.

```
src/stenographer/
├── status.py                          EDIT  Backend.WIN32 + two UnavailableReason members (D6)
├── overlay/
│   ├── win32.py                       NEW   pure placement/DIB layer + Win32OverlayBackend
│   └── supervisor.py                  EDIT  portable helper read loop (addition to §T, WIN-OVL-02)
└── platform/windows/
    ├── overlay.py                     NEW   win32 OverlayBackendSpec: read-only probe + construct
    └── __init__.py                    EDIT  overlay_backends() delegates instead of returning ()

tests/
├── test_status.py                     EDIT  win32 vocabulary in the round-trip matrix
├── overlay/
│   ├── test_overlay.py                EDIT  helper-reader queue coverage
│   ├── test_overlay_win32.py          NEW   pure layer; collected on Linux and Windows
│   └── test_overlay_helper_smoke.py   EDIT  accept Backend.WIN32; bytes, never text mode
└── platform/windows/                  NEW   Windows-only, not collected elsewhere
    ├── conftest.py                    NEW   collect_ignore_glob mirror of tests/platform/linux
    ├── test_overlay_backends.py       NEW   real probe/construct agreement
    ├── test_overlay_win32_smoke.py    NEW   real layered window
    └── test_overlay_helper_win32_smoke.py  NEW  real helper process end to end
```

`supervisor.py` is not in §T because SCOPE.md §3 records the daemon-side supervisor as carrying over
untouched. That is wrong on Windows and WIN-OVL-02 states why; §T should gain the row.

## Architecture principles

Global rules are cited, not restated: §P1 (lazy provider imports), §P2 (core stays host-blind), §P5
(every backend keeps a pure unit target), §P6 (no mock theater), §P7 (core-touching costs more), §P9
and AGENTS.md hard rule 7 (privacy across the IPC boundary).

- **WIN-OVL-P1 — `overlay/win32.py` imports on every OS.** Module level is stdlib plus
  `stenographer.overlay.render` and `stenographer.status`. Every `ctypes.windll`, every
  `ctypes.WINFUNCTYPE`, and every `wintypes`-based `Structure` is built inside `_api()`, an
  `functools.lru_cache(maxsize=1)` accessor returning one configured API façade. This is not style:
  `ctypes.WINFUNCTYPE` and `ctypes.windll` do not exist off-Windows, and `wintypes.LONG` is 8 bytes
  on LP64, so a module-level `RECT` is silently 32 bytes on Linux. The payoff is that the pure layer
  and its tests run in *both* CI jobs, which is why this domain needs no `importorskip` guard where
  `wayland.py` and `x11.py` do.
- **WIN-OVL-P2 — Reachable only through `overlay_backends()`.** Nothing in `overlay/__init__.py`,
  `overlay/supervisor.py`, `platform/windows/__init__.py`, or any core module imports
  `stenographer.overlay.win32` at module level, matching how `x11.py` and `wayland.py` are reached.
- **WIN-OVL-P3 — The overlay never takes activation or foreground.** The extended style is
  `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE` — one
  bit more than SCOPE.md §3 lists — over a plain `WS_POPUP`. Shown with `SW_SHOWNOACTIVATE`; every
  `SetWindowPos` passes `SWP_NOACTIVATE`; `SetForegroundWindow`, `SetFocus`, `SetActiveWindow` and
  `SetCapture` are never called. A violation still renders correctly and silently re-targets the
  paste chord, which is the delivery invariant §P8 protects.
- **WIN-OVL-P4 — The probe creates nothing and mutates no process state.** `probe_win32()` may call
  only `GetProcessWindowStation`, `GetUserObjectInformationW(UOI_FLAGS)` and
  `GetSystemMetrics(SM_CMONITORS)`. It must not call `SetProcessDpiAwarenessContext`,
  `RegisterClassExW` or `CreateWindowExW`: `doctor` runs the probe inside the *daemon* process, and
  DPI awareness is a one-way process-global. Awareness is set exactly once, in
  `Win32OverlayBackend.__init__`, in the helper process only, best-effort.
- **WIN-OVL-P5 — The window procedure only sets flags.** `_wnd_proc` records `WM_DISPLAYCHANGE`,
  `WM_DPICHANGED` and `WM_SETTINGCHANGE` on an instance attribute and returns `DefWindowProcW`; no
  rendering, no protocol work, no I/O. The `WNDPROC` callback object is stored on the instance for
  the window's entire life — a collected ctypes callback is an access violation, not an exception.
  Same severity class as §P4's hook-callback rule.
- **WIN-OVL-P6 — Placement is frozen for one visible interval.** Monitor and DPI scale are chosen at
  the hidden→visible transition and retained until `HIDDEN`, exactly as `x11.freeze_placement` does.
  `WM_DPICHANGED` and `WM_DISPLAYCHANGE` never move or rescale a visible pill; the single exception,
  mirroring `x11._handle_x_events`, is that a frozen monitor which no longer enumerates forces a
  destroy and re-show on the new selection.
- **WIN-OVL-P7 — One DIB per surface size.** A `CreateDIBSection` top-down 32-bit surface is created
  when the frame size changes and reused for every `UpdateLayeredWindow`; the per-frame work is a
  `memmove` into the section's bits plus one ULW call. No GDI object is created inside the 60 fps
  loading cadence.
- **WIN-OVL-P8 — The wire grows by exactly three fixed tokens.** `"win32"` in `ready`, and two fixed
  `unavailable` reasons. Never encode monitor or adapter names, window titles, HWNDs, coordinates,
  DPI values, `GetLastError` codes, or any Win32 diagnostic string, and the helper writes nothing to
  stderr or to a log file (§P9, hard rule 7).
- **WIN-OVL-P9 — The pump thread owns the window; the reader thread owns nothing.** The window is
  created, updated and destroyed on the thread running `Win32OverlayBackend.run()`. The NDJSON
  reader is a separate daemon thread whose whole job is `os.read(fd, 4096)` → `queue.Queue`; framing
  (`LineReader`), decoding, gating (`DisplayMessageGate`) and rendering all happen on the pump
  thread. No display call and no protocol decode ever runs off the pump thread.

## Functional criteria

### WIN-OVL-01 — Add the win32 overlay vocabulary to `status.py`
Phase: 3   Depends on: none
Files: `src/stenographer/status.py` (EDIT), `tests/test_status.py` (EDIT)
Pure tests: `tests/test_status.py::test_protocol_round_trip_is_one_ndjson_record` (extend the
parametrization with `ReadyMessage(Backend.WIN32)` and an `UnavailableMessage` for each new reason),
`tests/test_status.py::test_backend_and_unavailable_vocabulary_is_fixed_and_version_stable`
Smoke: none — the item adds enum members and their encode/decode paths; no host surface exists yet
to exercise, and a smoke case here could only assert what the round-trip test already proves (§P6).
Done when: `decode_message(encode_message(ReadyMessage(Backend.WIN32)))` round-trips inside
`MAX_MESSAGE_BYTES` with `"v":4` on the wire and `PROTOCOL_VERSION == 4` unchanged.

Adds `Backend.WIN32 = "win32"`, `UnavailableReason.NO_INTERACTIVE_DESKTOP = "no_interactive_desktop"`
(non-visible window station, no desktop, or zero display monitors — one reason, because the operator
conclusion is identical: there is no screen to draw on) and
`UnavailableReason.WIN32_LAYERED_UNAVAILABLE = "win32_layered_unavailable"` (user32/gdi32 entry
points, class registration, window creation or `UpdateLayeredWindow` failed). Nothing else in
`status.py` changes; per §D6 the version does not move.

### WIN-OVL-02 — Make the supervisor's helper read loop portable
Phase: 3   Depends on: none
Files: `src/stenographer/overlay/supervisor.py` (EDIT), `tests/overlay/test_overlay.py` (EDIT)
Pure tests: `tests/overlay/test_overlay.py::test_helper_reader_delivers_chunks_then_exactly_one_eof`,
`tests/overlay/test_overlay.py::test_helper_reader_get_honours_the_serve_timeout_cadence`
Smoke: covered by WIN-OVL-06's `test_windows_helper_reports_ready_win32_without_a_console_flash`;
on Linux the existing `tests/overlay/test_overlay_helper_smoke.py` is the unchanged-behavior gate.
Done when: `OverlaySupervisor._serve` drives a real helper process to `ready` on Windows, and no
`selectors` import remains in `supervisor.py`.

`_serve` currently registers the child's stdout **pipe** with `selectors.DefaultSelector()`. On
Windows that selector is `SelectSelector` and `select.select` accepts sockets only, so
`selector.select(timeout)` raises `OSError` on the first turn; the supervisor's `except Exception`
converts that into `supervisor_failed`, spends the restart budget, and disables the overlay after
two wasted helper spawns. Replace the selector with `_HelperReader`: a daemon thread looping
`os.read(process.stdout.fileno(), 4096)` and putting each chunk — then a single sentinel for EOF or
`OSError` — on a `queue.Queue`, with `_serve` calling `queue.get(timeout=serve_timeout(...))` and
treating `queue.Empty` as the old empty-ready-set case. Chunk size, ordering, EOF handling, the
`reader.finish()` call, the ready deadline, the spectrum cadence and `RestartBudget` are all
unchanged; the loop keeps `serve_timeout` as its pure timing target (§P5). The rewrite is
unconditional — a platform branch here would violate §P2.

### WIN-OVL-03 — Pure placement, DPI and layered-blit layer of `overlay/win32.py`
Phase: 3   Depends on: WIN-OVL-01
Files: `src/stenographer/overlay/win32.py` (NEW), `tests/overlay/test_overlay_win32.py` (NEW)
Pure tests: `tests/overlay/test_overlay_win32.py::test_cursor_work_area_wins_over_primary_and_stale_monitors`,
`::test_dpi_scale_is_clamped_to_sane_dpi_and_falls_back_to_one`,
`::test_placement_monitor_and_scale_are_frozen_until_hidden`,
`::test_win32_position_offsets_the_visible_pill_inside_the_work_area`,
`::test_layered_payload_is_premultiplied_bgra_with_a_dword_stride`,
`::test_bitmapinfoheader_is_top_down_thirty_two_bit_bi_rgb`,
`::test_pump_timeout_rounds_up_and_maps_none_to_infinite`
Smoke: none — this layer is arithmetic and byte packing with no host call; the live surface it feeds
is WIN-OVL-04's smoke case (§P6).
Done when: `python -c "import stenographer.overlay.win32"` succeeds on Linux and the file's pure
suite passes in both the `ubuntu-latest` and `windows-latest` unit jobs.

Public surface: `Win32Monitor(handle, work_area, dpi, primary)`; `Win32Placement(monitor, scale)`;
`select_win32_monitor(monitors, *, cursor)` (work area containing the cursor → primary → first
enumerated, `ValueError` on empty); `win32_dpi_scale(dpi)` (`dpi / 96.0`, clamped to the 72–384 DPI
sane window, `1.0` for anything non-positive or non-finite); `freeze_win32_placement(current,
monitor)`; `win32_position(monitor, frame)` delegating to `render.overlay_position(monitor.work_area,
frame, edge_offset=EDGE_OFFSET)`; `layered_window_payload(frame) -> LayeredPayload(width, height,
stride, pixels)` built from `render.premultiplied_argb32(frame.image, byteorder="little")` and
asserting `stride == width * 4` and `len(pixels) == height * stride`;
`bitmapinfoheader_bytes(width, height)` packing a 40-byte header with `biHeight = -height`,
`biPlanes = 1`, `biBitCount = 32`, `biCompression = BI_RGB`, `biSizeImage = width * height * 4`;
`pump_timeout_ms(seconds)` mapping `None` → `INFINITE` and otherwise `ceil(seconds * 1000)` clamped
to `[0, 0xFFFFFFFE]`; `Win32Unavailable(RuntimeError)` carrying a fixed `UnavailableReason`, the
sibling of `X11Unavailable`.

### WIN-OVL-04 — Live `Win32OverlayBackend`: layered window, pump, reader thread
Phase: 3   Depends on: WIN-OVL-03
Files: `src/stenographer/overlay/win32.py` (EDIT), `tests/overlay/test_overlay_win32.py` (EDIT),
`tests/platform/windows/test_overlay_win32_smoke.py` (NEW), `tests/platform/windows/conftest.py`
(NEW if no other Windows item has created it)
Pure tests: `tests/overlay/test_overlay_win32.py::test_overlay_window_styles_are_click_through_topmost_and_never_activating`
Smoke: `test_real_win32_layered_window_is_click_through_and_updates_in_place`
Done when: on a real Windows desktop the helper shows the pill for `recording`, repaints in place
for spectrum, loading and `transcribing`, destroys the window on `hidden`, and `WindowFromPoint` at
the pill's center never returns the overlay's `HWND`.

`Win32OverlayBackend` carries `backend = Backend.WIN32` and satisfies the `OverlayBackend` Protocol
(`run(input_stream)` / `close()`), with the same message-application shape as `X11OverlayBackend`:
`_apply` for the four display/command records, `_expire_error` at `ERROR_DISPLAY_SECONDS`,
`_expire_loading_animation` through the shared `render.LoadingPulse`, `_event_timeout(gate)` folding
those deadlines into one wait. `__init__` calls `SetProcessDpiAwarenessContext`
(`DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2`) best-effort — a failure means the process is already
awareness-locked and the backend continues with whatever `GetDpiForMonitor` reports, it is never an
unavailability. It then registers a `WNDCLASSEXW` (`cbSize` set, own `_wnd_proc` kept alive per
WIN-OVL-P5) and raises `Win32Unavailable(WIN32_LAYERED_UNAVAILABLE)` when class registration or a
required entry point is missing. `_show` enumerates monitors with `EnumDisplayMonitors` +
`GetMonitorInfoW` (`rcWork`) + `GetDpiForMonitor`, picks the cursor's monitor via `GetCursorPos`,
freezes the placement, renders through `render_overlay`, creates the `WS_POPUP` window with the
WIN-OVL-P3 extended style, and blits with `UpdateLayeredWindow(hwnd, NULL, POINT(x, y),
SIZE(w, h), memDC, POINT(0, 0), 0, BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA), ULW_ALPHA)`.
`run()` starts the reader thread of WIN-OVL-P9, then loops:
`MsgWaitForMultipleObjectsEx(0, NULL, pump_timeout_ms(...), QS_ALLINPUT, MWMO_INPUTAVAILABLE)`,
drain with `PeekMessageW(PM_REMOVE)` + `TranslateMessage`/`DispatchMessageW`, drain the byte queue
unconditionally, feed `drain_display_stream(chunk, reader, gate)`. The reader thread wakes the pump
with `PostThreadMessageW(main_tid, WM_STENO_DATA, 0, 0)` after each put. `close()` destroys the
window and DIB, unregisters the class, and joins the reader thread under a bounded timeout.

### WIN-OVL-05 — `platform/windows/overlay.py` and provider wiring
Phase: 3   Depends on: WIN-OVL-04
Files: `src/stenographer/platform/windows/overlay.py` (NEW),
`src/stenographer/platform/windows/__init__.py` (EDIT), `tests/platform/test_platform.py` (EDIT),
`tests/platform/windows/test_overlay_backends.py` (NEW)
Pure tests: `tests/platform/test_platform.py::test_windows_provider_offers_exactly_the_win32_overlay_backend`
Smoke: `test_real_win32_probe_agrees_with_construct`
Done when: `WindowsPlatform().overlay_backends()` is a one-element tuple whose `backend is
Backend.WIN32`, constructed without importing `stenographer.overlay.win32`, and `doctor` on a real
Windows desktop reports the overlay backend available.

`overlay.py` mirrors `platform/linux/overlay.py`: `_probe_win32()` and `_construct_win32()` each
lazy-import `stenographer.overlay.win32` inside the function body (§P1, WIN-OVL-P2), the probe
returning `UnavailableReason` or `None` and swallowing an import failure as
`UnavailableReason.BACKENDS_UNAVAILABLE` exactly as `_probe_xwayland` does. Unlike the Linux probes,
which construct and immediately close a live connection, `probe_win32()` observes only — window
station visibility and monitor count (WIN-OVL-P4). `WindowsPlatform.overlay_backends()` returns
`(OverlayBackendSpec(Backend.WIN32, _probe_win32, _construct_win32),)`.

### WIN-OVL-06 — Windows helper end to end, and the severability check
Phase: 3   Depends on: WIN-OVL-02, WIN-OVL-05; WIN-LIFE-02;
WIN-PKG: tests/platform/windows collection guard and the Windows smoke-gate job
Files: `tests/overlay/test_overlay_helper_smoke.py` (EDIT),
`tests/platform/windows/test_overlay_helper_win32_smoke.py` (NEW)
Pure tests: none — every assertion in this item is about a real spawned process and a real desktop;
the protocol layer it exercises is already covered pure by WIN-OVL-01 and WIN-OVL-02 (§P6).
Smoke: `test_windows_helper_reports_ready_win32_without_a_console_flash`,
`test_overlay_failure_leaves_dictation_unaffected`
Done when: on a real Windows desktop `stenographer run` shows the pill through a full utterance with
no console window appearing, and killing the helper mid-utterance leaves dictation working with the
overlay disabled for the rest of the session.

`tests/overlay/test_overlay_helper_smoke.py` needs two edits to run on Windows: accept
`Backend.WIN32` alongside the two Linux backends, and stop driving the child through
`subprocess.run(text=True)` — a `TextIOWrapper` with `newline=None` rewrites `\n` to `os.linesep`,
so every record would arrive `\r\n`-terminated and `decode_message` would reject it (`"\r" in
record`) with `ProtocolError`. Pass `bytes` and compare `bytes`. The daemon path is already correct:
`supervisor` opens the pipes with `bufsize=0` and writes ASCII bytes.

## Acceptance criteria

### AC-01 (WIN-OVL-01)
- `test_protocol_round_trip_is_one_ndjson_record` with the three new parameters catches a member
  added to the enum but not reachable through `_enum_value` (a mistyped `StrEnum` value, or a member
  whose value collides with an existing one — `StrEnum` would not complain, and the helper's `ready`
  record would decode as the wrong backend).
- `test_backend_and_unavailable_vocabulary_is_fixed_and_version_stable` asserts
  `tuple(Backend) == (LAYER_SHELL, XWAYLAND, WIN32)`, that every `UnavailableReason` value is a
  lowercase ASCII identifier, and `PROTOCOL_VERSION == 4`. It catches the change §D6 forbids — a
  version bump smuggled in beside the new members — and it must be seen to fail with
  `PROTOCOL_VERSION = 5` and with a member appended in the wrong position.
- **Linux behavior that stays byte-identical**: encoded records for every pre-existing message are
  unchanged, and the decoder still rejects unknown backends and reasons. Proven unchanged by
  `tests/test_status.py::test_protocol_uses_version_four_and_only_fixed_state_fields` (pins the exact
  bytes `{"v":4,"type":"state","generation":3,"state":"transcribing"}\n`),
  `::test_visible_state_set_has_no_loading_pill`,
  `::test_protocol_rejects_malformed_or_expansive_records_without_echo`,
  `::test_encoder_rejects_invalid_typed_values`, and the whole of `tests/overlay/test_overlay.py`.
  On the real Linux box, `tests/overlay/test_overlay_x11_smoke.py::test_real_xwayland_window_is_click_through_and_updates_in_place`
  and `tests/overlay/test_overlay_helper_smoke.py` must pass with no edits.
- Observable: `stenographer doctor` output and the Linux helper wire bytes are unchanged.

### AC-02 (WIN-OVL-02)
- `test_helper_reader_delivers_chunks_then_exactly_one_eof` builds a real `os.pipe()`, writes two
  chunks and closes the write end, and asserts the queue yields both chunks in order followed by one
  and only one EOF sentinel. No mock — a real fd, a real thread (§P6). It catches a reader that
  drops the tail chunk on EOF, one that emits the sentinel repeatedly (which would make `_serve`
  treat a healthy helper as crashed and spend the restart budget), and one that swallows `OSError`
  into a silent hang.
- `test_helper_reader_get_honours_the_serve_timeout_cadence` asserts an empty queue returns control
  within `serve_timeout(...)` and that `queue.Empty` is not treated as EOF. It catches the naive
  `queue.get()` with no timeout, which would stall spectrum production for a whole utterance while
  the helper is quiet — the loop's cadence, not just its reads, depends on this.
- Both must be seen to fail against the pre-change tree by pointing them at a selector-based reader.
- **Linux behavior that stays byte-identical**: identical chunking, ordering, EOF and error paths;
  identical ready deadline, spectrum cadence and restart budget. Proven by the unchanged
  `tests/overlay/test_overlay.py::test_helper_readiness_deadline_is_bounded_and_guarded_by_ready_state`,
  the three `test_serve_timeout_*`, the five `test_schedule_spectrum_*`, all `test_mailbox_*`,
  `::test_restart_budget_allows_exactly_one_unexpected_restart` and
  `::test_expected_exit_never_spends_or_uses_restart_budget`; and on the real Linux box by
  `tests/overlay/test_overlay_helper_smoke.py::test_source_private_overlay_responds_without_creating_logs`
  plus the XWayland smoke case above.
- Observable: on Linux, `overlay: ready backend=layer-shell` still appears within the 3 s readiness
  window and no `supervisor_failed` line appears; on Windows the same line appears with `win32`
  instead of an immediate `supervisor_failed`.

### AC-03 (WIN-OVL-03)
- `test_cursor_work_area_wins_over_primary_and_stale_monitors` builds three `Win32Monitor` values and
  asserts the cursor's work area wins, then the primary, then the first enumerated, and that an
  empty sequence raises `ValueError`. Catches a selector that reads `rcMonitor` semantics into a
  `rcWork` field or silently returns the primary when the cursor is on the second display.
- `test_dpi_scale_is_clamped_to_sane_dpi_and_falls_back_to_one` pins `96 → 1.0`, `144 → 1.5`,
  `240 → 2.5`, and `0`, `-1`, `10_000`, `float("nan")` → `1.0`. Catches the classic `dpi / 100`
  and the unguarded divide that renders a 6000-pixel pill from a bogus DPI.
- `test_placement_monitor_and_scale_are_frozen_until_hidden` asserts `freeze_win32_placement` returns
  the existing placement unchanged when one is present. Catches the WIN-OVL-P6 violation where a
  cursor moved to the other monitor teleports a visible pill mid-utterance.
- `test_win32_position_offsets_the_visible_pill_inside_the_work_area` asserts the pill bottom sits
  exactly `EDGE_OFFSET * scale` above `work_area` bottom (not the canvas bottom — the frame carries
  a shadow margin) and horizontally centered within one pixel. Catches offsetting by `frame.height`,
  which hides the pill behind the taskbar, and catches using the full monitor rect instead of
  `rcWork`, which puts it under the taskbar on a maximized desktop.
- `test_layered_payload_is_premultiplied_bgra_with_a_dword_stride` renders a real frame, then
  asserts a straight-alpha `(255, 0, 0, 128)` source pixel arrives as `B=0, G=0, R=128, A=128`, that
  `stride == width * 4`, and `len(pixels) == height * stride`. Catches the single most likely
  regression in this domain: someone replacing the call with `image.tobytes("raw", "BGRA")`, which
  is straight alpha and produces a bright halo around every antialiased edge under `ULW_ALPHA`.
- `test_bitmapinfoheader_is_top_down_thirty_two_bit_bi_rgb` unpacks the 40 bytes and asserts
  `biHeight < 0`, `biBitCount == 32`, `biCompression == 0`, `biSizeImage == width * height * 4`.
  Catches a positive `biHeight`, which renders the pill upside down, and `biBitCount == 24`, which
  drops alpha and paints an opaque black box over the desktop.
- `test_pump_timeout_rounds_up_and_maps_none_to_infinite` asserts `None → 0xFFFFFFFF`, `0.0004 → 1`,
  `-5 → 0`, `1.5 → 1500`. Catches truncation to `0`, which busy-spins the helper at 100% CPU, and
  `None → 0`, the same spin with a subtler cause.
- Observable: importing the module on Linux succeeds and the file's tests appear in both CI jobs'
  collection counts.

### AC-04 (WIN-OVL-04)
- `test_overlay_window_styles_are_click_through_topmost_and_never_activating` asserts every one of
  `WS_EX_LAYERED`, `WS_EX_TRANSPARENT`, `WS_EX_TOOLWINDOW`, `WS_EX_TOPMOST`, `WS_EX_NOACTIVATE` is
  set, that `WS_EX_APPWINDOW` and `WS_EX_ACCEPTFILES` are clear, and that the base style is
  `WS_POPUP` with no `WS_CHILD` and no `WS_CAPTION`. This is the §P5 pure target for an item whose
  rest is `ctypes`: a dropped `WS_EX_TRANSPARENT` or `WS_EX_NOACTIVATE` bit leaves the code running
  and correct-looking while stealing clicks or focus. Seen to fail by removing one bit.
- Smoke `test_real_win32_layered_window_is_click_through_and_updates_in_place`, modeled on
  `tests/overlay/test_overlay_x11_smoke.py`: run the backend on a thread of the test process fed by a
  real `os.pipe()`, write real `encode_message` records, and from the test thread assert —
  (1) `GetWindowLongPtrW(hwnd, GWL_EXSTYLE)` carries the five required bits;
  (2) `GetForegroundWindow()` is identical before and after `recording` appears (no focus theft);
  (3) `WindowFromPoint` at the pill center does not return the overlay `HWND` (click-through);
  (4) a `BitBlt` from the screen DC with `CAPTUREBLT` over the pill rect changes after a
  `SpectrumMessage(0, 0, (255,) * 18)`, again after `LoadingActivityMessage(True)`, and again one
  frame later (the pulse is animating), while `GetWindowRect` is byte-identical across the
  `recording` → `transcribing` transition (repaint in place, not recreate);
  (5) `hidden` destroys the window — `IsWindow(hwnd)` is false;
  (6) `CommandMessage(SHUTDOWN)` returns from `run()` and the thread exits.
  The case skips, never fails, when `Win32Unavailable` is raised, mirroring the XWayland smoke case's
  skip on `X11Unavailable`.
  Real-machine procedure: on a physically attached (not RDP) Windows desktop session with at least
  one monitor, `STENOGRAPHER_INTEGRATION=1 .venv\Scripts\pytest tests\platform\windows`.
- Multi-monitor procedure, same session, run by hand once per release: start `stenographer run` with
  the overlay enabled, hold the hotkey with the cursor on the secondary display, and confirm the pill
  appears above that display's taskbar; while still holding, drag a window between displays and
  confirm the pill does not move (WIN-OVL-P6); release, then unplug or disable the secondary display
  during a new utterance and confirm the pill reappears on the remaining display rather than
  vanishing or leaving a ghost. Repeat with the two displays at different scale factors (100% /
  150%) and confirm the pill is physically the same size on each.
- Observable: no `stenographer.log` is created by the helper, and `GetLastError` values never reach
  the wire (WIN-OVL-P8) — the only failure record is one of the two fixed reasons.

### AC-05 (WIN-OVL-05)
- `test_windows_provider_offers_exactly_the_win32_overlay_backend` runs on Linux and Windows: it
  constructs `WindowsPlatform()`, asserts `tuple(spec.backend for spec in plat.overlay_backends()) ==
  (Backend.WIN32,)`, that both `probe` and `construct` are callables, and that
  `"stenographer.overlay.win32" not in sys.modules` afterwards. Catches an eager import at provider
  level, which would break the Linux bundle's `collect_submodules` over the Windows package (§P1).
  This edit replaces the current `assert plat.overlay_backends() == ()` in
  `tests/platform/test_platform.py::test_windows_stub_conforms_and_reports_everything_unavailable`;
  the remainder of that test is untouched, and it is a test Linux runs — §P7 applies to the edit.
- Smoke `test_real_win32_probe_agrees_with_construct`: on the real desktop, assert `probe_win32()`
  returns `None` and a constructed `Win32OverlayBackend` closes cleanly; then assert the probe
  performed no process mutation by checking `GetAwarenessFromDpiAwarenessContext(
  GetThreadDpiAwarenessContext())` is unchanged across the probe call (WIN-OVL-P4). Catches a probe
  that quietly locks the daemon process into per-monitor awareness, which would change how every
  other daemon-side Win32 call reports coordinates.
- Observable: `stenographer doctor` on a real desktop names the overlay backend as available and
  exits 0 on an otherwise healthy host; in a session-0 or service context it reports
  `no_interactive_desktop` and the overlay is disabled without affecting the `REQUIRED` gate.

### AC-06 (WIN-OVL-06)
- Smoke `test_windows_helper_reports_ready_win32_without_a_console_flash`: spawn the helper exactly
  as the supervisor does (`helper_command(...)` plus `current_platform().helper_spawn_kwargs()`),
  write a real `CommandMessage(SHUTDOWN)` as **bytes**, and assert the first record decodes to
  `ReadyMessage(Backend.WIN32)`, that the raw stdout bytes contain no `\r` (the text-mode regression
  of WIN-OVL-06 would otherwise appear as an unexplained `protocol_error`), that the process exits 0,
  that no `stenographer.log*` is created under a redirected state directory, and that
  `GetConsoleWindow()` in the child is `NULL` — the observable form of `CREATE_NO_WINDOW`.
- Smoke `test_overlay_failure_leaves_dictation_unaffected`: with the daemon running, terminate the
  helper process mid-utterance and confirm the transcript is still delivered, `overlay:
  helper_restarting` appears once, a second kill disables the overlay
  (`helper_disabled reason=restart_budget_exhausted`), and dictation continues for two further
  utterances. This is the severability claim of SCOPE.md §3 made checkable.
- Real-machine procedure: physical desktop session, `STENOGRAPHER_INTEGRATION=1` for the pytest
  cases; the kill case is run by hand with Task Manager against the second `stenographer` process.
- Observable: a full hold-speak-release cycle shows the pill and pastes the text; with the helper
  killed, the same cycle pastes the text and shows nothing.

## Risks

1. **Windows `select()` is socket-only, so the supervisor does not carry over untouched.** Verified
   by reading `overlay/supervisor.py:437` against `selectors.DefaultSelector` on Windows. Likelihood
   certain; impact: the overlay never starts on Windows and two helper processes are spawned and
   reaped per daemon run. This contradicts SCOPE.md §3's "the daemon-side supervisor … carries over
   untouched". Mitigation: WIN-OVL-02, which is unconditional and keeps Linux on the same cadence.
   Covered by AC-02.
2. **Text-mode CRLF on the helper pipe.** Likelihood medium (any test or tool that drives the helper
   with `text=True`); impact: every record is rejected and the overlay disables with
   `protocol_error`, which reads as a backend bug rather than a framing bug. Mitigation: bytes-only
   pipes plus the decoder's existing `"\r" in record` rejection, which fails loudly instead of
   silently corrupting. Covered by AC-06's no-`\r` assertion.
3. **Focus theft re-targets the paste chord.** Likelihood medium if a style bit or `SWP_NOACTIVATE`
   is dropped; impact: the confirmed clipboard text is pasted into the wrong window — a delivery
   failure caused by an optional component, which is exactly the coupling the overlay isolation rule
   exists to prevent. Mitigation: WIN-OVL-P3 and the style test. Covered by AC-04 (1) and (2).
4. **The `WNDPROC` ctypes callback is garbage-collected.** Likelihood medium — it is the standard
   ctypes trap and nothing in the type system prevents it; impact: an access violation kills the
   helper (not the daemon), the supervisor restarts once and then disables the overlay, so the
   symptom is "the pill disappears after a while". Mitigation: WIN-OVL-P5's lifetime rule; the
   crash surfaces in AC-04's smoke case as a failed `run()` return.
5. **60 fps loading pulse against ~15.6 ms timer granularity.** Likelihood high; impact cosmetic
   only — `loading_border_opacity` is elapsed-time driven, so a coarse tick drops frames without
   distorting the animation. Mitigation: accept it; do **not** call `timeBeginPeriod`, which is a
   system-wide power regression for a decorative pulse. Covered by AC-04 (4), which asserts the
   pulse advances, not that it advances at 60 Hz.
6. **Disconnected or locked sessions.** Likelihood medium (RDP, fast user switching, lock screen);
   impact: `UpdateLayeredWindow` fails repeatedly and a naive loop spins. Mitigation: a bounded
   consecutive-failure count that raises `Win32Unavailable(WIN32_LAYERED_UNAVAILABLE)` so the helper
   exits and the supervisor takes the ordinary unavailable path. Covered by AC-05's session-0 case
   and AC-06's severability case.
7. **A later `PROTOCOL_VERSION` bump.** Per §D6 no bump is needed and none is planned; the risk is a
   future edit doing it anyway. The decoder requires exact equality, so the failure is not a graceful
   downgrade: a daemon built from the tree spawning a *stale frozen helper* — precisely what
   `tests/overlay/test_overlay_helper_smoke.py::test_frozen_private_overlay_responds_without_creating_logs`
   runs against `dist/` — would see every record rejected, the helper would answer
   `unavailable(protocol_error)`, and the overlay would silently disable on both platforms until the
   bundle is rebuilt. Likelihood low, impact medium, and it is silent, which is why AC-01 pins the
   constant with a test rather than a comment.
8. **Antivirus heuristics on the frozen bundle** (SCOPE.md §7 risk 2): a topmost transparent
   always-on-top window adds a small amount of marginal heuristic surface on top of the global
   keyboard hook. Owned by WIN-PKG; no mitigation in this domain beyond keeping the helper a plain
   child process of the daemon with no elevation.
9. **The real-machine Windows merge gate** (SCOPE.md §7 risk 4, §D8): every acceptance criterion
   here beyond the pure tests requires a physical Windows desktop session. Owned by WIN-PKG; this
   domain's exposure is that its smoke cases are the ones that cannot be run in CI at all.
