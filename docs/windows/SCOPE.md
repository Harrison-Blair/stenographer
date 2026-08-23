# Windows Feature Parity — Scope

Status: **first-pass scope** (2026-08-23). This maps the surface area, dependency
story, and risks of a full Windows backend. It is not the implementation plan —
that is a second pass — and it decides nothing that `docs/reauthor.md` reserves:
the open decisions in the final section must be recorded as a reauthor.md
amendment before implementation starts, per that document's own rules.

Baseline: `main` @ v0.11.0 (`dev` fully merged via PR #17). The two prerequisites
already exist on that baseline:

- **The platform boundary** (reauthor.md amendment 2026-08-21): every host
  surface sits behind the `stenographer.platform` Protocols, enforced by
  `tests/platform/test_core_isolation.py`, wired at the single point
  `Daemon.build(platform=)`.
- **The Windows stub + CI portability job**: `platform/windows/` imports
  everywhere and reports every surface unavailable; `unit-windows` proves the
  core installs, imports, and passes on `windows-latest`.

`docs/reauthor.md` §7's Windows ledger row pre-authorizes the backend and lists
what is still to build. This document is that list made concrete.

---

## 1. What already works untouched

Most of the pipeline is already Windows-clean. None of the following needs
porting work:

- **Audio capture** — `sounddevice`/PortAudio runs on WASAPI/MME/DirectSound;
  the `Recorder` (block-copy callback, RMS gate, sample-rate fallback) is core.
- **ASR worker** — already `multiprocessing.get_context("spawn")`;
  `cli/__init__.py` already calls `freeze_support()` for the frozen re-exec.
- **Config, formatter, status protocol, delivery policy, spectrum math,
  logging** — all core, all pure or stdlib.
- **Directory policy** — the stub already resolves `%APPDATA%` /
  `%LOCALAPPDATA%` (honouring `XDG_*` overrides).
- **Dependencies** — `faster-whisper`/CTranslate2, `numpy`, `soundfile`,
  `tomlkit`, `pillow`, `huggingface_hub` all ship Windows wheels; the
  Linux-only deps (`evdev`, `pywayland`, `python-xlib`) already carry
  `sys_platform == 'linux'` markers.

What is missing is the **provider** — roughly ten modules under
`platform/windows/` — plus four cross-cutting workstreams (overlay protocol,
service story, doctor/setup text, packaging/CI).

## 2. Provider surface map

Each `Platform` protocol surface, its Linux implementation, and the Windows
mechanism that satisfies the same contract:

| Protocol surface | Linux today | Windows mechanism | Dependency |
|---|---|---|---|
| `KeyTable` / key vocabulary | evdev + generated `keycodes.py` | Keep `StaticKeyTable` (already wired in the stub); add a **`KEY_*` ↔ VK-code mapping table** — a new pure module plus a generator script mirroring `scripts/gen_keycodes.py`. Chord matching stays in evdev codes; the listener translates VK → evdev code at the boundary. | none (static data) |
| `HotkeyListener` | `EvdevHotkeyListener` over `/dev/input` | **`WH_KEYBOARD_LL`** hook via `ctypes.windll.user32.SetWindowsHookExW`, on a dedicated thread running a `GetMessage` pump (stopped with `PostThreadMessage(WM_QUIT)`). The hook callback only translates VK → evdev code and **enqueues**; a dispatch thread feeds `ChordTracker._key_event()`. The queue is load-bearing, not stylistic: edges fire `on_start`/`on_stop` under the daemon lock, and Windows silently removes LL hooks whose callbacks stall (~300 ms budget). Non-grabbing (events pass through), matching the Linux listener. | ctypes (stdlib) |
| `KeyInjector` | uinput Shift+Insert | **`SendInput`** with scan codes (`KEYEVENTF_SCANCODE`) for the paste chord; same modifier-wraps-key ordering as `chord_events()`. Chord choice is an open decision (§7). | ctypes |
| `ClipboardWriter` | wl-copy / xclip + read-back | **`OpenClipboard`/`EmptyClipboard`/`SetClipboardData(CF_UNICODETEXT)`** with a bounded retry loop — the Win32 clipboard is a contended global and `OpenClipboard` fails transiently — confirmed by a `GetClipboardData` read-back so §4.3 copy-confirmed-before-paste is preserved byte-for-byte. Windows has no primary selection: one clipboard write. | ctypes |
| `Notifier` | notify-send `Popen` | **PowerShell toast subprocess** — structurally identical to the notify-send pattern (pure `build_command` unit target + non-blocking `Popen`, failures swallowed to debug). ~1 s latency is acceptable for errors-only. Alternative: the `windows-toasts` package (WinRT) if PowerShell proves too slow. | none (or `windows-toasts`) |
| `CuePlayer` | canberra/pw-play/paplay subprocesses | **In-process `sounddevice` + `soundfile` playback** on a thread with numpy gain scaling — honours `feedback.volume`, reuses existing deps, and PortAudio supports an output stream alongside capture. (`winsound` is stdlib but has no volume control, which would violate the config contract.) `play` is fire-and-forget; `preview` blocks and raises, per the protocol. | none (reuses existing deps) |
| `SingleInstanceLock` | flock in `$XDG_RUNTIME_DIR` | **Named mutex** — `CreateMutexW("Local\\stenographer")`; `ERROR_ALREADY_EXISTS` maps to contention (`acquire() -> False`), other failures raise `SingleInstanceLockError`. `Local\` scopes per session, mirroring the per-user flock semantics. | ctypes |
| `install_stop_signal_handlers` | SIGINT/SIGTERM | `signal.signal(SIGINT)` (already in the stub) **plus `SetConsoleCtrlHandler`** for CTRL_BREAK/CTRL_CLOSE. CTRL_CLOSE grants ~5 s before force-kill, so shutdown must stay fast. | ctypes |
| `capture_binding` | termios + select + evdev | Reuse the **same pure reducer** in `cli/binding_capture.py`, fed from a temporary LL hook; replace the termios quiet-terminal with `SetConsoleMode` echo suppression / an `msvcrt` input-buffer drain. Ctrl-C behaviour preserved. | ctypes, msvcrt |
| `hotkey_devices` | evdev enumeration | Returns `[]` — an LL hook is global and cannot select devices; setup already degrades gracefully on an empty list. `hotkey.device` is documented as ignored on Windows (see §7: Raw Input is the deferred alternative if per-device selection is ever wanted). | — |
| `probe_host` / `restart_service` | uinput access, input group, systemctl | The semantic `doctor.REQUIRED` names survive unchanged (that was the point of the extraction): `key_injector_ok` ≈ always true, `hotkey_access_ok` ≈ hook installable, clipboard probe, cue player detection, plus the service story (§4). | ctypes |
| `helper_spawn_kwargs` | `{}` | `creationflags=CREATE_NO_WINDOW` so the overlay helper never flashes a console window. | stdlib |
| `overlay_backends` | layer-shell → XWayland specs | See §3. Empty until the overlay phase lands (overlay stays disabled via `NullStatusSink`, exactly as designed). | — |

All Win32 calls stay inside method bodies (the lazy-provider rule): `--help`,
the import-isolation test, and the Linux bundle's `collect_submodules` over the
Windows package must never touch them.

`cli/doctor.py` needs a small refactor alongside the provider: the
`_FIX_HINTS` / `_LABELS` / `_CLIPBOARD_FIX_HINTS` dicts are Linux prose
(`sudo usermod -aG input`, "install wl-clipboard") — per-platform hint/label
text is §7-listed work. The gate math and `REQUIRED` names do not change.

## 3. Overlay (largest single item, and a protocol decision)

`status.Backend` is protocol-v4 wire vocabulary (`layer-shell`, `xwayland`). A
Windows overlay therefore requires:

1. A new `Backend` member (e.g. `WIN32`) — an explicit **protocol-extension
   decision** per AGENTS.md, additive member vs. version bump to be recorded.
2. An `OverlayBackendSpec` (probe + construct) from
   `WindowsPlatform.overlay_backends()`.
3. A helper-side backend (`overlay/win32.py`, sibling of `wayland.py`/`x11.py`,
   reachable only via `overlay_backends()`): a layered, click-through, topmost
   window (`WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW |
   WS_EX_TOPMOST`) blitting the existing Pillow `render.py` output via
   `UpdateLayeredWindow` (premultiplied ARGB). Needs per-monitor DPI awareness
   (`SetProcessDpiAwarenessContext`) and work-area positioning.

The daemon-side supervisor, spectrum analysis, NDJSON protocol, and renderer
all carry over untouched. Estimated 400–600 lines and the fiddliest Win32 code
in the project — but **severable**: dictation parity does not depend on it, and
the overlay is failure-disabled by design.

## 4. Service story (a design decision, not just code)

reauthor.md §7 calls for "a service concept that reimplements '78 = don't
restart'". The hard constraint: **a real Windows Service runs in session 0 and
cannot install global hooks, call `SendInput`, or touch the user-session
clipboard.** The daemon must be a user-session process.

The realistic analog is a **Task Scheduler logon task** (or a Startup-folder
entry): `probe_host` maps `service_enabled`/`service_active` onto `schtasks`
queries, `restart_service` restarts the task. Task Scheduler cannot natively
condition restarts on exit code 78, so the options are:

- accept no auto-restart and have doctor/setup print the `schtasks` one-liners
  (mirroring the Linux "print the systemctl command, never install" policy), or
- ship a tiny wrapper that honours the exit-code contract.

Owner decision required (§7).

## 5. Packaging, CI, and the testing gate

- **Packaging**: a Windows PyInstaller onedir path (`stenographer.spec`
  conditionals; `packaging/entry.py` and `hook-sounddevice.py` mostly carry
  over), an `install.ps1` per-user analog of `install.sh` targeting
  `%LOCALAPPDATA%\Programs`, and `windows-latest` jobs in `build.yml` /
  `release.yml` producing a zip + checksums alongside the Linux bundles.
- **CI**: `unit-windows` already runs; the new pure tests (VK table drift,
  chord translation, command builders, retry/quieting logic) extend it for
  free. Windows-only tests mirror `tests/platform/linux/` as
  `tests/platform/windows/`, not collected elsewhere.
- **The hard one**: §6 is binding — no mocked-Win32 theater, and the smoke
  suite is the dev → main merge gate *on a real machine*. Full parity means a
  Windows integration smoke suite (real clipboard round-trip, real `SendInput`
  into a self-owned test window, real mutex contention, real cue playback,
  real hook where feasible) **and a real Windows box in the merge loop**.
  Without that hardware this is a process blocker, not a code problem. Whether
  the smoke gate applies per-platform or globally per release must be decided
  up front.

Explicitly **out of scope without a reauthor.md amendment**: PowerShell
completions (decision 4 fixes the completion surface at Bash/Zsh/Fish), hybrid
trigger mode, per-device hotkey selection.

## 6. Dependency verdict

**Near-zero new runtime dependencies.** The entire provider can be `ctypes` +
`msvcrt` (stdlib), reusing `sounddevice`/`soundfile` for cues and PowerShell
for toasts. The only candidate addition is `windows-toasts` (with a
`sys_platform == 'win32'` marker) if PowerShell toasts prove too slow.

`pywin32` is deliberately not recommended: it is a heavy binary dependency, it
does not usefully expose `SetWindowsHookEx` (the hook needs ctypes regardless),
and ctypes-throughout keeps the provider consistent with the repo's minimal-dep
ethos and the lazy-import rule.

## 7. Risks, ranked

1. **UIPI / elevated windows.** A medium-integrity daemon's LL hook does *not*
   receive keystrokes while an elevated (admin) window has focus, and
   `SendInput`/clipboard into elevated apps is blocked. Dictation silently dies
   whenever an admin console is focused. No clean fix without signed uiAccess
   binaries; document as accepted scope and hint from doctor where possible.
2. **Antivirus / SmartScreen.** An unsigned PyInstaller bundle installing a
   global keyboard hook is textbook keylogger heuristics; expect Defender flags
   on the frozen bundle. The pip-install path is less affected; code signing is
   the eventual answer. Biggest *distribution* risk.
3. **LL hook timeout discipline.** Windows silently removes hooks whose
   callbacks stall. The enqueue-and-return design handles it, but every future
   edit near the hook thread is a footgun — worth a stated invariant, like the
   PortAudio-callback rule (§4.8) it strongly resembles.
4. **The real-machine merge gate** (see §5) — hardware and policy, not code.
5. **Clipboard contention & managers.** `OpenClipboard` retry semantics and
   clipboard-history (Win+V) interplay; read-back confirmation covers
   correctness, but retry/timeout policy must preserve "a failed copy never
   fires the chord".
6. **Paste chord choice.** Shift+Insert works in most Windows apps but some
   UWP/modern apps ignore it; Ctrl+V is near-universal. Decision 7 is
   explicitly a *Linux* contract, so this is an open decision either way.
7. **Overlay protocol extension.** Small, but the strict v4 parser on both
   ends must agree; additive member vs. version bump is a deliberate decision.
8. **Console-close shutdown window** (~5 s under CTRL_CLOSE) and the
   windowless-run question (`pythonw` / frozen no-console vs. console)
   interact with logging and the ctrl handler.

## 8. Suggested phasing

Four severable phases, each independently mergeable behind the existing
"unavailable" degradation:

1. **Dictation parity** — VK keymap table + generator, LL hook listener,
   `SendInput` injector, clipboard, named mutex, ctrl handler, cues, notifier,
   `probe_host` + per-platform doctor hint text. Delivers "hold hotkey, speak,
   text appears" on Windows; overlay stays disabled via `NullStatusSink`.
2. **Setup parity + service story** — Windows binding capture, console
   quieting, `schtasks` integration, and the "78 = don't restart" decision.
3. **Overlay backend** — `Backend` protocol amendment + layered-window helper.
4. **Packaging / CI / release** — Windows PyInstaller bundle, `install.ps1`,
   release artifacts, the Windows smoke suite, and the merge-gate policy.

## 9. Open decisions requiring a reauthor.md amendment first

Per the design record's own rules, these must be recorded before phase 1:

- Paste chord on Windows: Ctrl+V vs Shift+Insert.
- Service concept: Task Scheduler logon task (no auto-restart, print the
  commands) vs a wrapper honouring exit-78 semantics.
- Toast mechanism: PowerShell subprocess vs `windows-toasts` dependency.
- Cue player: in-process sounddevice playback (volume honoured) — confirm the
  departure from the Linux spawn-a-player pattern.
- LL hook (global, no device selection; `hotkey.device` ignored) rather than
  Raw Input; Raw Input stays a deferred door for per-device selection.
- Overlay wire vocabulary: additive `Backend` member vs protocol version bump.
- UIPI limitation (no dictation into elevated windows) as accepted scope.
- Smoke-gate policy: per-platform vs global real-machine gate, and the Windows
  hardware requirement.
