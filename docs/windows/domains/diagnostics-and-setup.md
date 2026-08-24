# Windows Domain Plan — Diagnostics and Setup

Scope: the Windows `HostProbe`, the per-platform prose that `doctor` and `setup` print, the Windows
binding capture, and the D7 integrity-level reporting. Blast area is **core-touching**: this domain
edits `cli/doctor.py`, `cli/setup.py`, `cli/setup_config.py` and `platform/base.py`, all of which
Linux executes, so every item below carries a §P7 statement and falls under the "both suites" row of
§D8. Read `README.md` first; nothing it owns is restated here.

## Designed source tree

| Path | Mark | Role |
|---|---|---|
| `src/stenographer/cli/doctor.py` | EDIT | consume a provider-supplied text table; add the optional integrity line; `REQUIRED` and the gate math untouched |
| `src/stenographer/cli/setup.py` | EDIT | provider-supplied service prose, hotkey-device note, D7 elevation offer |
| `src/stenographer/platform/windows/probe.py` | NEW | `HostProbe` for doctor plus the Windows `HostText` table |
| `src/stenographer/platform/windows/binding_capture.py` | NEW | temporary LL hook feeding the shared reducer + `SetConsoleMode` quieting |
| `src/stenographer/platform/windows/__init__.py` | EDIT | lazy wiring for `host_text`, `probe_host`, `capture_binding`, `set_service_elevation` |
| `tests/platform/windows/` | NEW | Windows-only pure tests and smoke cases for this domain |

Three rows this domain needs are **not in §T** and extend it (flagged rather than silently added):

| Path | Mark | Role |
|---|---|---|
| `src/stenographer/platform/base.py` | EDIT | `HostText` type, two `HostProbe` fields, `host_text()` / `set_service_elevation()` |
| `src/stenographer/platform/linux/probe.py` | EDIT | the Linux `HostText` table — today's literals moved out of core, byte-for-byte |
| `src/stenographer/cli/setup_config.py` | EDIT | read-only-target retry in `_atomic_replace` (the rule-9 preservation gap, WIN-DIAG-08) |

## Architecture principles

**WIN-DIAG-P1 — All varying prose arrives as data, never as a conditional.** After WIN-DIAG-02 and
WIN-DIAG-04, `cli/doctor.py` and `cli/setup.py` contain zero occurrences of `sys.platform`,
`os.name`, `systemd`, `systemctl`, `journalctl`, `usermod`, `uinput`, `wl-copy`, `xclip`, `schtasks`
or `install.sh`/`install.ps1`. A reviewer greps for those tokens; a hit is a violation. This is §P2
applied to text.

**WIN-DIAG-P2 — One `HostText` field per varying *sentence*, not per varying *noun*.** Core never
assembles grammar from provider fragments (`f"Restart the active {noun}…"` is forbidden), because
substituting "logon task" into a sentence written for "stenographer.service" produces text that
compiles and reads wrong. The provider owns the whole sentence; core owns only which sentence to
print. Fields that are genuinely lexical (`labels`, `fix_hints`, `service_label`) stay maps.

**WIN-DIAG-P3 — Every Linux `HostText` value is the literal from today's source, copied
character-for-character** including the em dash in `not installed — run scripts/install.sh` and the
trailing periods. The extraction is a move, not a rewrite. WIN-DIAG-02/04 golden fixtures are the
enforcement.

**WIN-DIAG-P4 — `REQUIRED` and `missing_required` are frozen.** No name is added, removed, renamed
or reordered; no new `Capabilities` field is ever read by `missing_required`. Everything this domain
adds (`service_run_level`, `integrity_level`) defaults to `None` and is informational, so a Windows
host with no logon task and an unreadable token still exits 0 when the five required capabilities
are present. The internal names (`uinput_writable`, `input_group`) keep leaking into the
`missing required capabilities: …` summary line on both platforms; that is the accepted cosmetic
price of holding the line byte-identical on Linux, and the per-capability line above it carries the
Windows wording.

**WIN-DIAG-P5 — Doctor probes are read-only, with exactly one named exception.** The Windows hook
probe installs `WH_KEYBOARD_LL` and unhooks it inside the same call because Win32 offers no query
form. That probe's callback does nothing but `CallNextHookEx` — it never swallows an event — and
`UnhookWindowsHookEx` runs on every path including exceptions (`try/finally`). No other probe
opens a device, writes, elevates, or touches the network.

**WIN-DIAG-P6 — Console quieting clears echo, never signal processing.** `quiet_console_mode` clears
`ENABLE_ECHO_INPUT (0x0004)` and `ENABLE_LINE_INPUT (0x0002)` and leaves
`ENABLE_PROCESSED_INPUT (0x0001)` set — the exact analogue of the Linux capture leaving `ISIG`
untouched, and the reason Ctrl-C still raises `KeyboardInterrupt` during capture. The original mode
is restored on every exit path, including `BindingCaptureError` and `KeyboardInterrupt`.

**WIN-DIAG-P7 — The capture reducer is not forked.** `platform/windows/binding_capture.py` imports
`CaptureState`, `KeyEvent`, `reduce_capture` and `serialize_capture` from `cli/binding_capture.py`;
a Windows-side state machine, even a "small" one, is a violation. The hook is global, so every
`KeyEvent.device` is the constant `"hook"`, and auto-repeat `WM_KEYDOWN` maps to `value=1` (the
reducer's held-set dedups it) — never to evdev's `value=2`, which the reducer would drop and which
would therefore hide a real repeat bug.

**WIN-DIAG-P8 — Setup never installs, registers, or elevates without an explicit yes.** The
elevation offer prints the trade before the prompt, defaults to *no*, and a refusal leaves the task
exactly as it was and does not change the exit code. Setup still never *installs* anything on either
platform (§D2's correction assigns registration to the installer); the only privileged verbs it may
invoke are `restart_service()` and `set_service_elevation()`, both against an already-registered
task.

**WIN-DIAG-P9 — Informational host state degrades to `None`, never to a lie.** An unqueryable Task
Scheduler yields `(None, None)` → "unknown (cannot query Task Scheduler)"; a *registered-but-absent*
task yields `(None, "inactive")`, deliberately reusing the exact pair Linux produces for an
uninstalled unit so that `format_service_status` and every `service_enabled is None and
service_active == "inactive"` branch in `setup.py` fire identically on both platforms with no new
branch. Inventing `"disabled"` for a task that does not exist is a violation.

## Functional criteria

### WIN-DIAG-01 — Introduce `HostText` and give both providers a table
Phase: 1   Depends on: none
Files: `src/stenographer/platform/base.py` (EDIT), `src/stenographer/platform/linux/probe.py`
(EDIT), `src/stenographer/platform/windows/probe.py` (NEW),
`src/stenographer/platform/windows/__init__.py` (EDIT)
Pure tests: `tests/platform/test_platform.py::test_windows_stub_conforms_and_reports_everything_unavailable`
(unchanged, now also proves `host_text` exists on both providers),
`tests/platform/linux/test_doctor_text.py::test_linux_text_matches_the_recorded_literals`,
`tests/platform/windows/test_doctor_text.py::test_windows_text_covers_every_required_name`
Smoke: none — a frozen dataclass of strings has no host behavior; §P6.
Done when: `current_platform().host_text()` returns a `HostText` on Linux and Windows, and the Linux
table's values are byte-identical to the literals removed from `cli/doctor.py` and `cli/setup.py`.

`HostText` is a `@dataclass(frozen=True, slots=True)` in `platform/base.py`, stdlib-only per §P3,
added to the `Platform` Protocol as `host_text(self) -> HostText` (cheap, no I/O, callable before
any probe — `setup`'s wizard needs it before `doctor.probe`). Fields, doctor half: `labels`,
`fix_hints`, `clipboard_fix_hints`, `clipboard_fix_default`, `service_label`, `service_unknown`,
`service_not_installed`, `integrity_label`. Setup half, one field per sentence (WIN-DIAG-P2):
`restart_prompt`, `restart_done`, `restart_failed`, `not_installed_hint`, `not_active_hint`,
`tryout_active`, `tryout_not_installed`, `tryout_inactive`, `tryout_unknown`,
`tryout_restart_pending`, `tryout_custom_config: Callable[[Path], str]`, `logs_hint`,
`logs_custom_config`. Optional, defaulting to `None`: `hotkey_device_note`, `elevation_prompt`,
`elevation_done`, `elevation_failed`. `LinuxPlatform.host_text()` returns `LINUX_TEXT` in
`platform/linux/probe.py`, whose `tryout_custom_config` keeps the existing
`shlex.quote` call so POSIX quoting leaves core with the literal it already produced;
`WindowsPlatform.host_text()` lazy-imports `WINDOWS_TEXT` from `platform/windows/probe.py`
(§P1) whose `tryout_custom_config` emits `set "STENOGRAPHER_CONFIG=…" && stenographer run` and whose
`logs_hint` names the real state-directory log file resolved through `state_dir`. Windows values:
`service_label = "logon task"`, `service_unknown = "unknown (cannot query Task Scheduler)"`,
`service_not_installed = "not registered — run install.ps1"`, `labels["uinput_writable"] =
"paste injection (SendInput)"`, `labels["input_group"] = "keyboard hook"`,
`clipboard_fix_hints = {"win32": "another process is holding the clipboard open; close "
"clipboard-manager tools and retry"}`. `platform/windows/probe.py` lands in this item carrying the
table plus a `probe_host()` that still returns the stub's degraded values; WIN-DIAG-03 fills it in.

### WIN-DIAG-02 — Route `cli/doctor.py` through `HostText`
Phase: 1   Depends on: WIN-DIAG-01
Files: `src/stenographer/cli/doctor.py` (EDIT), `tests/cli/test_doctor.py` (EDIT),
`tests/platform/linux/test_doctor_text.py` (NEW), `tests/fixtures/doctor_report_linux.txt` (NEW)
Pure tests: `tests/cli/test_doctor.py::test_render_missing_capability_carries_the_supplied_hint`,
`tests/cli/test_doctor.py::test_render_clipboard_hint_falls_back_to_the_table_default`,
`tests/cli/test_doctor.py::test_missing_required_names_each_absent_capability` (unchanged),
`tests/platform/linux/test_doctor_text.py::test_linux_report_is_byte_identical_to_the_baseline`
Smoke: `tests/cli/test_doctor_smoke.py` (existing, unchanged) on Linux; `windows_doctor_exit_code`
on Windows once WIN-DIAG-03 lands.
Done when: `stenographer doctor` on Linux prints a report byte-identical to `origin/dev`'s, and
`cli/doctor.py` contains no Linux literal.

Delete `_FIX_HINTS`, `_LABELS`, `_CLIPBOARD_FIX_HINTS` and the `"systemd unit"` /
`"not installed — run scripts/install.sh"` /
`"unknown (cannot query the systemd user manager)"` literals. `render` becomes
`render(caps, cfg, config_path, *, text: HostText)` and `format_service_status(enabled, active, *,
text: HostText)`; both stay pure — the table is passed in, never fetched from `current_platform()`
inside a pure function. `doctor.run` resolves `current_platform().host_text()` once. The clipboard
line keeps its `f"clipboard ({caps.clipboard_backend})"` construction, so `labels["clipboard"]`
stays present but unused, matching today. `_OVERLAY_FIX_HINTS` stays in core: `UnavailableReason`
is protocol vocabulary, not host prose, and D6 adds Windows reasons additively. The prose-asserting
tests move out of `tests/cli/test_doctor.py` into `tests/platform/linux/test_doctor_text.py` with
their assertion strings unchanged, because `tests/cli/` is collected on `windows-latest` and would
otherwise assert Linux prose against the Windows table; what remains in `tests/cli/test_doctor.py`
uses a synthetic `HostText` and therefore passes on both runners.

### WIN-DIAG-03 — Implement the Windows `HostProbe`
Phase: 1   Depends on: WIN-DIAG-01, `WIN-FEED: in-process sounddevice cue player` (for the player name)
Files: `src/stenographer/platform/windows/probe.py` (EDIT),
`src/stenographer/platform/windows/__init__.py` (EDIT),
`tests/platform/windows/test_probe.py` (NEW), `tests/platform/windows/test_probe_smoke.py` (NEW)
Pure tests: `tests/platform/windows/test_probe.py::test_interactive_window_station_accepts_only_winsta0`,
`tests/platform/windows/test_probe.py::test_clipboard_retry_schedule_is_bounded`
Smoke: `windows_probe_reports_real_capabilities`
Done when: `stenographer doctor` on a real Windows logon session reports the five required
capabilities from live Win32 state and exits 0 once the model is cached.

`probe_host()` returns `HostProbe(key_injector_ok=…, hotkey_access_ok=…, clipboard_ok=…,
clipboard_backend="win32", cue_player=…, service_enabled=None, service_active=None)` — service
fields stay `None` until WIN-DIAG-05, which is safe precisely because they are not in `REQUIRED`.
Mapping, per the SCOPE §2 `probe_host` row (semantic names survive):

- `key_injector_ok` — **not** a hardcoded `True`. `user32.GetProcessWindowStation()` +
  `GetUserObjectInformationW(h, UOI_NAME=2, …)`, passed to the pure
  `interactive_window_station(name) -> bool` (case-insensitive `"WinSta0"`). This is the one thing
  that actually makes `SendInput` impossible — a session-0 context, the failure D2 exists to avoid —
  so the check is real rather than decorative. `False` also when the call fails.
- `hotkey_access_ok` — `hook_installable()`: `SetWindowsHookExW(WH_KEYBOARD_LL=13, cb, None, 0)`
  followed immediately by `UnhookWindowsHookEx`, under WIN-DIAG-P5. The `HOOKPROC` is held in a
  module-level reference for the lifetime of the call so ctypes does not collect it.
- `clipboard_ok` — `OpenClipboard(None)` / `CloseClipboard()` only; never `EmptyClipboard`. Bounded
  retry from the pure `clipboard_retry_delays() -> tuple[float, ...]` (5 attempts, ≤ 150 ms total)
  so a clipboard manager holding the global for a few milliseconds does not report MISSING.
- `cue_player` — `"sounddevice"` when `sounddevice.query_devices()` yields any device with
  `max_output_channels > 0`, else `None`; `PortAudioError`/`ImportError` → `None`. Not in `REQUIRED`,
  so a silent box still passes.

### WIN-DIAG-04 — Route `cli/setup.py` service prose and the hotkey-device note through `HostText`
Phase: 2   Depends on: WIN-DIAG-01, WIN-DIAG-02
Files: `src/stenographer/cli/setup.py` (EDIT), `tests/platform/linux/test_setup_text.py` (NEW),
`tests/fixtures/setup_tryout_linux.txt` (NEW)
Pure tests: `tests/platform/linux/test_setup_text.py::test_tryout_branches_match_the_baseline`,
`tests/platform/linux/test_setup_text.py::test_guided_service_messages_match_the_baseline`,
`tests/cli/test_setup.py::test_restart_eligibility` (unchanged),
`tests/cli/test_setup.py::test_followup_exit_precedence` (unchanged)
Smoke: `tests/cli/test_setup_smoke.py::test_real_active_service_restart` (existing, unchanged);
`windows_quick_setup_transcript` on Windows
Done when: quick setup on Windows prints logon-task prose in every service branch, and the Linux
transcript for all five `_print_quick_tryout` branches is byte-identical to `origin/dev`'s.

`setup.run` resolves `text = current_platform().host_text()` once and threads it into `_guided_setup`,
`_print_quick_tryout`, `_restart_service`, `_wizard`, `_quick_wizard` and the `_EDITORS` mapping
(whose `Callable` signature gains the `HostText` parameter). `_prompt_device` gains
`note: str | None = None`, printed after the device list; `_edit_hotkey` and `_quick_wizard` pass
`text.hotkey_device_note`, `_edit_audio` and the microphone prompt pass nothing, so the audio prompt
is untouched on both platforms. **`hotkey_devices()` returning `[]` (§D5) is already handled**: the
verified path is `_prompt_device` → header `"Hotkey devices (automatic selection is always
available):"` → `"  (no selectable devices found; manual entry is still available)"` → the prompt
`"Hotkey [automatic/unset; Enter keeps, number selects, 'auto' unsets, or type a value]: "`. Nothing
crashes and `parse` never indexes an empty list, but "manual entry is still available" is misleading
where `hotkey.device` is ignored, so the Windows `hotkey_device_note` reads: *"This platform captures
the hotkey with a global keyboard hook, so hotkey.device is ignored; press Enter or type 'auto'."*
Linux's note is `None` and prints nothing.

### WIN-DIAG-05 — Wire the logon-task state and D7 integrity reporting into doctor
Phase: 2   Depends on: WIN-DIAG-02, WIN-DIAG-03, `WIN-LIFE: schtasks query parser`
Files: `src/stenographer/platform/base.py` (EDIT), `src/stenographer/cli/doctor.py` (EDIT),
`src/stenographer/platform/windows/probe.py` (EDIT), `tests/platform/windows/test_probe.py` (EDIT),
`tests/cli/test_doctor.py` (EDIT)
Pure tests: `tests/cli/test_doctor.py::test_integrity_line_is_absent_when_the_host_reports_none`,
`tests/cli/test_doctor.py::test_format_integrity_status_warns_only_at_medium`,
`tests/platform/windows/test_probe.py::test_integrity_label_maps_rid_boundaries`,
`tests/platform/windows/test_probe.py::test_missing_task_maps_to_none_inactive`
Smoke: `windows_service_status_matches_schtasks`
Done when: `doctor` on Windows prints one `integrity level:` line naming both the calling process's
level and the registered task's run level, and Linux's report gains no line at all.

`HostProbe` gains `service_run_level: str | None = None` and `integrity_level: str | None = None`
(defaulted, so `platform/linux/probe.py` needs no change and Linux keeps `None`); `Capabilities`
gains the same two defaulted fields. `render` appends
`f"  {text.integrity_label}: {status}"` only when `format_integrity_status(caps.integrity_level,
caps.service_run_level, text=text)` returns non-`None`, which it never does when
`integrity_level is None` — that is what keeps Linux byte-identical. `format_integrity_status` is
pure and appends the D7 explanation only at `"medium"`: `medium (logon task: highest) — keystrokes
typed into an elevated window are not seen`. Reporting both values is deliberate: `doctor` reads its
*own* token, which is not the daemon's, so the task's run level is the only evidence about the
running daemon. Windows side: `process_integrity_rid()` via
`OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY)` + `GetTokenInformation(TokenIntegrityLevel=25)`,
reading the last SID sub-authority; the pure `integrity_label(rid)` maps `0x0000` untrusted,
`0x1000` low, `0x2000`–`0x2FFF` medium (0x2100 "medium plus" included), `0x3000` high, `0x4000`
system, anything else `"unknown"`. `service_status()` shells `schtasks /query /tn Stenographer /xml
ONE` (XML, not the localized `/fo LIST /v`) and hands stdout to WIN-LIFE's parser, then maps per
WIN-DIAG-P9: task absent → `(None, "inactive", None)`; `schtasks` missing, non-zero for any other
reason, or timed out → `(None, None, None)`; present → `("enabled"|"disabled", "active"|"inactive",
run level)`.

### WIN-DIAG-06 — Offer the `/rl HIGHEST` re-registration from setup
Phase: 2   Depends on: WIN-DIAG-04, WIN-DIAG-05, `WIN-LIFE: logon-task builder with the elevated flag`
Files: `src/stenographer/platform/base.py` (EDIT), `src/stenographer/cli/setup.py` (EDIT),
`src/stenographer/platform/windows/__init__.py` (EDIT), `tests/cli/test_setup.py` (EDIT),
`tests/platform/windows/test_setup_smoke.py` (NEW)
Pure tests: `tests/cli/test_setup.py::test_elevation_offer_eligibility`,
`tests/cli/test_setup.py::test_elevation_offer_is_never_eligible_without_a_prompt`
Smoke: `windows_elevation_round_trip`
Done when: on Windows, a registered medium-integrity task produces one yes/no prompt whose refusal
changes nothing and whose acceptance re-registers the task at `/rl HIGHEST`; on Linux the prompt
never appears and setup's transcript is unchanged.

`Platform` gains `set_service_elevation(self, *, elevated: bool) -> tuple[bool, str]`, the exact
shape of `restart_service`; `LinuxPlatform` raises `UnsupportedPlatformError` and `WindowsPlatform`
lazy-imports WIN-LIFE's `service.py`. Core calls it only through the pure gate
`elevation_offer_eligible(*, prompt_available: bool, service_enabled: str | None,
current_run_level: str | None) -> bool`, true only when a prompt exists, the task is registered
(`service_enabled is not None`) and its run level is not already `"highest"` — so on Linux
`prompt_available` is `False`, the gate is `False`, and `set_service_elevation` is never reached.
The offer prints `text.elevation_prompt` (the trade first, per §D7 and WIN-DIAG-P8) and defaults to
**no**; success prints `text.elevation_done`, failure prints `text.elevation_failed` through
`console.error` and sets `operational_failure`, which `followup_exit_code` already turns into exit 1.

### WIN-DIAG-07 — Windows binding capture: temporary hook plus console quieting
Phase: 2   Depends on: `WIN-INPUT: WH_KEYBOARD_LL listener`, `WIN-INPUT: KEY_* ↔ VK table`
Files: `src/stenographer/platform/windows/binding_capture.py` (NEW),
`src/stenographer/platform/windows/__init__.py` (EDIT),
`tests/platform/windows/test_binding_capture.py` (NEW)
Pure tests: `tests/platform/windows/test_binding_capture.py::test_quiet_console_mode_keeps_processed_input`,
`tests/platform/windows/test_binding_capture.py::test_quiet_console_mode_is_idempotent`,
`tests/platform/windows/test_binding_capture.py::test_hook_events_reduce_to_a_chord_binding`
Smoke: `windows_live_binding_capture`
Done when: quick setup on Windows captures `KEY_LEFTCTRL+KEY_A` from real keystrokes, echoes
nothing while capturing, restores the exact prior console mode, and still cancels on Ctrl-C.

`capture_binding(stdin, device, *, timeout)` ignores `device` (§D5), installs a temporary
`WH_KEYBOARD_LL` hook on a dedicated pump thread reusing WIN-INPUT's hook plumbing under §P4
(callback enqueues only), drains the queue on the calling thread, and feeds
`KeyEvent("hook", evdev_code, 1|0)` into the shared `reduce_capture` (WIN-DIAG-P7). It raises
`BindingCaptureError` — never `UnsupportedPlatformError` — on every failure so
`_capture_or_choose_binding` keeps offering retry/type/keep. The quiet-console context manager
mirrors `platform/linux/binding_capture.py::_quiet_terminal` exactly: `GetConsoleMode(stdin handle)`
→ pure `quiet_console_mode(mode)` → `SetConsoleMode`, drain with `while msvcrt.kbhit():
msvcrt.getwch()` on entry and exit, restore in `finally`. `GetConsoleMode` failing (a piped or
mintty stdin — setup's `isatty()` gate does not guarantee a Win32 console handle) raises
`BindingCaptureError(f"could not prepare the terminal: {exc}")`, the same words and the same
recovery as Linux; `--quick` and non-TTY invocation are unaffected because setup already refuses
non-TTY with exit 2 before any wizard runs and the typed-binding path never touches console mode.

### WIN-DIAG-08 — Close the rule-9 preservation gap on Windows
Phase: 2   Depends on: none
Files: `src/stenographer/cli/setup_config.py` (EDIT), `tests/cli/test_setup_config.py` (EDIT),
`tests/platform/windows/test_setup_config_smoke.py` (NEW), `docs/reauthor.md` (EDIT — §4 note only)
Pure tests: `tests/cli/test_setup_config.py::test_readonly_retry_mode_only_fires_for_unwritable_modes`,
`tests/cli/test_setup_config.py::test_save_preserves_mode_when_the_target_is_writable` (unchanged)
Smoke: `windows_readonly_config_save`; `tests/cli/test_setup_config_smoke.py` (existing, unchanged)
on Linux
Done when: saving a read-only `config.toml` on Windows succeeds, restores the read-only attribute,
and still writes the timestamped backup, while the Linux save path executes the identical statements
it does today.

Hard rule 9's "mode and symlink preservation" is a POSIX contract; on Windows it degrades and the
degradation must be stated, not discovered:

- **Mode.** `os.stat().st_mode` carries only `FILE_ATTRIBUTE_READONLY` (0o666 vs 0o444). Preserving
  it therefore preserves the read-only attribute and nothing else; NTFS ACLs, the hidden/archive
  attributes, EFS encryption and alternate data streams are **not** preserved, and because
  `_atomic_replace` writes a fresh `mkstemp` file and `os.replace`s it, any explicit non-inherited
  ACE on `config.toml` is replaced by the parent directory's inherited ACL. Under `%APPDATA%` these
  coincide; a user who hardened the file loses that hardening silently. Documented as accepted.
- **The bug this exposes.** POSIX `rename(2)` needs only directory write permission, so a read-only
  target replaces fine; Windows `MoveFileExW(MOVEFILE_REPLACE_EXISTING)` fails with
  `ERROR_ACCESS_DENIED` on a read-only destination. Today `_existing_mode` reads `0o444`,
  `_atomic_replace` chmods the temp file to `0o444`, and the save raises `ConfigPersistenceError` →
  exit 1 after the backup was already written. Fix, platform-blind: catch `PermissionError` from
  `os.replace`, and when the pure `readonly_retry_mode(mode) -> int | None` returns a mode (i.e.
  `mode is not None and not mode & 0o200`), `os.chmod(target, retry_mode)`, retry `os.replace` once,
  then re-apply `os.chmod(target, mode)`. On Linux the happy path is untouched and the retry branch
  is unreachable in practice.
- **Symlinks.** `_resolve_target` → `Path.resolve()` → write-through semantics hold on Windows for
  symlinks, directory junctions and OneDrive redirections. Two host facts to keep in mind rather
  than code around: creating a symlink needs Developer Mode or `SeCreateSymbolicLinkPrivilege`, so
  the case is rare; and `mkstemp` already targets `target.parent` (the *resolved* parent), so
  `os.replace` never crosses a volume through a junction.

## Acceptance criteria

### WIN-DIAG-01
- `tests/platform/linux/test_doctor_text.py::test_linux_text_matches_the_recorded_literals` asserts
  every `LINUX_TEXT` string against the literal captured from `origin/dev` (generate once with
  `git show origin/dev:src/stenographer/cli/doctor.py` and
  `git show origin/dev:src/stenographer/cli/setup.py` in a scratch worktree). **Seen to fail** by
  changing `not installed — run scripts/install.sh` to use a hyphen instead of the em dash: the test
  must catch a one-character drift, because that is the realistic form of this bug.
- `tests/platform/windows/test_doctor_text.py::test_windows_text_covers_every_required_name` asserts
  `set(WINDOWS_TEXT.labels) >= set(doctor.REQUIRED)` and the same for `fix_hints` minus `clipboard`.
  **Seen to fail** by deleting the `input_group` key — which would otherwise surface only as a
  `KeyError` inside `render` on a Windows box that is already failing a capability.
- `tests/platform/test_platform.py::test_windows_stub_conforms_and_reports_everything_unavailable`
  and `::test_linux_provider_conforms_to_platform_protocol` must pass **unchanged**; adding
  `host_text` to the `runtime_checkable` `Platform` Protocol makes them the enforcement that neither
  provider forgot it.
- Linux behavior: no runtime behavior changes in this item — `cli/` is untouched, so `doctor` and
  `setup` output on Linux is byte-identical by construction.
- `tests/platform/test_core_isolation.py::test_core_imports_with_linux_only_modules_blocked`
  unchanged and green: `base.py` stays stdlib-only, `windows/probe.py` is imported lazily.

### WIN-DIAG-02
- `tests/platform/linux/test_doctor_text.py::test_linux_report_is_byte_identical_to_the_baseline`
  renders a fixed `Capabilities` (one all-present case, one with `model_cached=False,
  clipboard=False`, one with `service_enabled=None, service_active="inactive"`) with `LINUX_TEXT` and
  compares against `tests/fixtures/doctor_report_linux.txt` with `==` on the whole string. The
  fixture is generated from the pre-change tree and committed in the same commit. **Seen to fail**
  by dropping two spaces of indentation from one capability line — a diff no reviewer catches by
  eye and exactly the class of regression the 2026-08-21 amendment's byte-identical claim forbids.
- `tests/cli/test_doctor.py::test_render_missing_capability_carries_the_supplied_hint` builds a
  synthetic `HostText` with recognizable sentinel strings and asserts they appear verbatim. **Seen
  to fail** by leaving one `_FIX_HINTS` lookup behind in `render` — the sentinel is absent and the
  Linux literal appears instead.
- `tests/cli/test_doctor.py::test_render_clipboard_hint_falls_back_to_the_table_default` passes a
  `clipboard_backend` absent from `clipboard_fix_hints`. **Seen to fail** by porting the old
  `_CLIPBOARD_FIX_HINTS["wl-copy"]` default as a hardcoded key lookup, which raises `KeyError`
  against a Windows table.
- Unchanged and must still pass: `tests/cli/test_doctor.py::test_missing_required_empty_when_all_present`,
  `::test_missing_required_names_each_absent_capability`, `::test_audio_player_is_not_required`,
  `::test_service_status_is_not_required`, `::test_overlay_report_variants_are_informational_only`
  (gate math and overlay vocabulary are untouched); `tests/cli/test_doctor_smoke.py` in full;
  `tests/cli/test_run_smoke.py::test_missing_required_capability_precedes_real_lock` (the daemon's
  `startup_clipboard_backend` still consumes the same `Capabilities`).
- Relocated verbatim (same function names, same asserted strings, new file, no edits to the
  assertions): `test_render_missing_capability_carries_fix_hint`,
  `test_render_clipboard_line_names_the_detected_backend`, `test_format_service_status_installed`,
  `test_format_service_status_not_installed`, `test_format_service_status_unreachable_manager`,
  `test_render_carries_service_status_line`, `test_render_all_present`,
  `test_render_absent_audio_player_is_informational`. Reviewer check: `git log -p` shows the
  assertion lines unchanged across the move.
- Observable: `.venv/bin/stenographer doctor` on Linux, diffed against the same command run from an
  `origin/dev` worktree with the same config and model cache, produces zero bytes of difference.

### WIN-DIAG-03
- `tests/platform/windows/test_probe.py::test_interactive_window_station_accepts_only_winsta0`
  covers `"WinSta0"`, `"winsta0"`, `"Service-0x0-3e7$"`, `""` and `None`. **Seen to fail** by a
  case-sensitive `==` comparison, which reports MISSING on hosts where the station name is returned
  lower-cased.
- `tests/platform/windows/test_probe.py::test_clipboard_retry_schedule_is_bounded` asserts the
  schedule is non-empty, monotonic, and sums to ≤ 0.15 s. **Seen to fail** by an unbounded
  `while True` retry, which would hang `doctor` behind a clipboard-manager hold.
- Smoke `windows_probe_reports_real_capabilities` — procedure: log into an interactive Windows
  session, run `.venv\Scripts\stenographer doctor` from a normal console; assert
  `clipboard_backend == "win32"`, `key_injector_ok` and `hotkey_access_ok` are `True`,
  `audio_player` is `"sounddevice"` or `None`, and the exit code is 0 with the model cached / 78
  without it. Then run the same command from a `PsExec -s` session-0 context and assert
  `key_injector_ok` is `False` and the exit code is 78 — that inversion is the proof the probe reads
  real state instead of returning a constant.
- No mock may satisfy any of this (§P6): the Win32 calls are exercised only by the smoke case; the
  two pure helpers are the unit surface (§P5).

### WIN-DIAG-04
- `tests/platform/linux/test_setup_text.py::test_tryout_branches_match_the_baseline` drives
  `_print_quick_tryout` over a real `_Console` wrapping `io.StringIO` for all five branches
  (custom config, restart pending, active, not installed, inactive, unknown) plus both `hotkey.mode`
  values, and compares the concatenated transcript against `tests/fixtures/setup_tryout_linux.txt`.
  **Seen to fail** by swapping the `service_enabled is None and service_active == "inactive"` branch
  order with the `service_active is not None` branch — a reordering that still prints plausible text
  and would otherwise be found only by a user with an uninstalled unit.
- `tests/platform/linux/test_setup_text.py::test_guided_service_messages_match_the_baseline` asserts
  `text.not_installed_hint`, `text.not_active_hint`, `text.restart_prompt`, `text.restart_done` and
  `text.restart_failed` equal today's literals. **Seen to fail** by dropping the trailing period
  from `Restarted stenographer.service.`, which would break the existing smoke assertion.
- Unchanged and must still pass: every test in `tests/cli/test_setup.py` (the parsers,
  `restart_eligible`, `followup_exit_code`, the reducer cases, and
  `test_setup_requires_an_interactive_terminal`); `tests/cli/test_setup_smoke.py::test_real_active_service_restart`,
  which asserts `"Restarted stenographer.service"` and therefore proves the sentence survived the
  move into `HostText`; `::test_restart_policy_uses_real_user_service_status`;
  `::test_real_quick_setup_persists_and_runs_guided_checks`.
- Smoke `windows_quick_setup_transcript` — procedure: on a Windows box with the logon task
  registered and `stenographer.service`'s analogue running, `stenographer setup --quick`, answer
  Enter throughout; assert the hotkey section prints the device note and no `systemctl`/`journalctl`
  string appears anywhere in the transcript (`findstr /i "systemctl journalctl systemd"` returns
  nothing).
- Observable: a Linux `stenographer setup --quick` transcript captured before and after the change,
  answering Enter throughout with an unchanged config, is byte-identical.

### WIN-DIAG-05
- `tests/cli/test_doctor.py::test_integrity_line_is_absent_when_the_host_reports_none` renders with
  `integrity_level=None` and asserts `"integrity" not in report`. **Seen to fail** by rendering the
  line unconditionally with a `"unknown"` placeholder, which would add a line to the Linux report
  and break WIN-DIAG-02's golden fixture — the two tests are deliberately mutually reinforcing.
- `tests/cli/test_doctor.py::test_format_integrity_status_warns_only_at_medium` covers
  `("medium", "highest")`, `("high", "highest")`, `("medium", None)`, `(None, "highest")`. **Seen to
  fail** by appending the "elevated window" caveat at `"high"`, which tells an already-elevated user
  their dictation is broken when it is not.
- `tests/platform/windows/test_probe.py::test_integrity_label_maps_rid_boundaries` covers `0x0000`,
  `0x1000`, `0x2000`, `0x2100`, `0x2FFF`, `0x3000`, `0x4000`, `0x5000`. **Seen to fail** by an
  `if rid >= 0x2000: "medium" elif rid >= 0x3000: "high"` ordering bug, which silently reports every
  elevated daemon as medium — precisely the reading a user consults to explain a dead hotkey.
- `tests/platform/windows/test_probe.py::test_missing_task_maps_to_none_inactive` feeds the parser
  result for "task not found" and asserts `(None, "inactive", None)`. **Seen to fail** by returning
  `(None, None, None)`, which makes doctor print "unknown (cannot query Task Scheduler)" on a
  perfectly healthy box that simply has no task, and silently disables setup's install hint branch.
- Smoke `windows_service_status_matches_schtasks` — procedure: with the task registered, run
  `stenographer doctor` and `schtasks /query /tn Stenographer /xml ONE` side by side and assert the
  reported enabled/active/run-level agree; `schtasks /delete /tn Stenographer /f`, re-run doctor,
  assert the line reads `not registered — run install.ps1` and the exit code is unchanged.
- Linux: `platform/linux/probe.py` is not edited by this item; `HostProbe`'s new fields default to
  `None`, `format_integrity_status` returns `None`, and the doctor report gains nothing. The
  WIN-DIAG-02 golden fixture is re-run unchanged as the proof.

### WIN-DIAG-06
- `tests/cli/test_setup.py::test_elevation_offer_eligibility` parametrizes
  `elevation_offer_eligible` over (prompt available × registered × run level) exactly as
  `test_restart_eligibility` does for restarts. **Seen to fail** by omitting the
  `current_run_level != "highest"` term, which re-prompts an already-elevated user on every setup
  run and re-registers the task needlessly.
- `tests/cli/test_setup.py::test_elevation_offer_is_never_eligible_without_a_prompt` fixes
  `prompt_available=False` across every other combination. **Seen to fail** by any short-circuit
  that reaches `set_service_elevation` on Linux, where it raises `UnsupportedPlatformError` and
  crashes setup.
- Smoke `windows_elevation_round_trip`, gated behind `STENOGRAPHER_ELEVATION_SMOKE=1` mirroring the
  existing `STENOGRAPHER_SETUP_RESTART_SMOKE` precedent — procedure: register the task at medium,
  run `stenographer setup --quick`, answer *no* and assert `schtasks /query … /xml` still shows
  `LeastPrivilege`; re-run, answer *yes*, assert `HighestAvailable`, log out and back in, and
  confirm dictation works into an elevated console. Restore the medium task afterwards.
- Linux: the prompt is unreachable (`elevation_prompt is None`), so the setup transcript is
  byte-identical — covered by re-running WIN-DIAG-04's `test_tryout_branches_match_the_baseline`
  and `tests/cli/test_setup_smoke.py` unchanged.

### WIN-DIAG-07
- `tests/platform/windows/test_binding_capture.py::test_quiet_console_mode_keeps_processed_input`
  asserts `quiet_console_mode(0x01 | 0x02 | 0x04 | 0x200) == 0x01 | 0x200`. **Seen to fail** by
  clearing `ENABLE_PROCESSED_INPUT` along with echo — the single change that turns Ctrl-C from a
  cancel into a captured keystroke, which no amount of running the code by hand reveals until
  someone tries to abort a capture.
- `::test_quiet_console_mode_is_idempotent` asserts a second application is a no-op, so a nested
  or retried capture cannot corrupt the mode it must restore.
- `::test_hook_events_reduce_to_a_chord_binding` feeds the adapter's `KeyEvent` sequence for
  Ctrl-down, A-down, A-**repeat** (a second `WM_KEYDOWN` with `value=1`), A-up, Ctrl-up through
  `reduce_capture`/`serialize_capture` and asserts `"KEY_LEFTCTRL+KEY_A"`. **Seen to fail** by
  emitting `value=2` for auto-repeat (the reducer ignores it, so the binding is right by accident)
  *and* by emitting a fresh `value=1` without the held-set dedup being relied on — the test pins the
  contract WIN-DIAG-P7 states.
- Smoke `windows_live_binding_capture` — procedure: from a real `cmd.exe` console, run a script that
  calls `capture_binding(sys.stdin, None, timeout=10)`; record `GetConsoleMode` before, poll it
  during (assert `ENABLE_ECHO_INPUT` clear and `ENABLE_PROCESSED_INPUT` set), physically press
  Ctrl+A, assert the result is `"KEY_LEFTCTRL+KEY_A"`, that no characters were echoed, and that
  `GetConsoleMode` afterwards equals the recorded value exactly. Repeat pressing Ctrl-C instead and
  assert `KeyboardInterrupt` propagates and the mode is still restored. This is the direct mirror of
  `tests/cli/test_setup_smoke.py::test_live_binding_capture_uses_real_uinput_and_restores_pty`,
  which must keep passing unchanged on Linux.
- Core untouched by this item: `cli/binding_capture.py` gains no code. Enforcement is
  `tests/platform/test_core_isolation.py` (unchanged) plus a reviewer diff showing the file is not
  in the changeset.

### WIN-DIAG-08
- `tests/cli/test_setup_config.py::test_readonly_retry_mode_only_fires_for_unwritable_modes` covers
  `None`, `0o600`, `0o644`, `0o444`, `0o400`. **Seen to fail** by returning a retry mode for `0o644`,
  which would chmod the target on every ordinary Linux save and change its ctime for no reason.
- Unchanged and must still pass: the whole of `tests/cli/test_setup_config.py` (render preservation,
  unchanged-bytes-not-written, `ConfigChangedError`) and
  `tests/cli/test_setup_config_smoke.py` on Linux, including the symlink and mode cases — those are
  the proof that the retry branch did not disturb the POSIX path.
- Smoke `windows_readonly_config_save` — procedure: `attrib +R %APPDATA%\stenographer\config.toml`,
  run `stenographer setup --quick`, change one value, save; assert the save succeeds, the new value
  is present, a `config.toml.bak-…` exists, and `attrib` still shows `R` on the target. **Seen to
  fail** against the unfixed tree: the save raises `cannot replace …: [WinError 5]` and exits 1
  *after* writing the backup.
- Documentation: the ACL/attribute non-preservation is recorded as a `docs/reauthor.md` §4 note in
  the same commit; a reviewer checks the note exists and names ACLs, hidden/archive attributes, EFS
  and alternate data streams explicitly.

## Risks

**R1 — The prose extraction silently changes Linux output.** Likelihood medium (a dozen sentences
move between files); impact high (it falsifies the 2026-08-21 amendment's byte-identical claim and
breaks the smoke assertion on `Restarted stenographer.service`). Mitigation: WIN-DIAG-P3 plus two
golden fixtures generated from `origin/dev`, not retyped. Covered by WIN-DIAG-02 and WIN-DIAG-04
acceptance.

**R2 — `HostText` becomes a place for logic.** Likelihood medium (the first Windows sentence that
needs a value interpolated invites a `format()` in core, or a conditional in the provider); impact
medium (reintroduces the platform branching §P2 forbids, one string at a time). Mitigation:
WIN-DIAG-P2 makes the rule reviewable — a field is a whole sentence or a lexical map, never a
template with grammar in it, the two `Callable` fields excepted and both taking only a path.
Covered by WIN-DIAG-P1's grep check in WIN-DIAG-02/04 acceptance.

**R3 — The doctor hook probe trips antivirus.** Likelihood low, impact medium: SCOPE.md §7 risk 2
already flags the bundle; a *second* binary that installs `WH_KEYBOARD_LL` widens the heuristic
surface to the diagnostic path, so a user could see `doctor` quarantined while `run` is fine.
Mitigation: the probe installs and unhooks within one call and never swallows an event
(WIN-DIAG-P5); if a shipping Defender build flags it, the fallback is to report `hotkey_access_ok`
from the window-station check alone with the hook hint downgraded to informational — a one-line
change confined to `platform/windows/probe.py`. Covered by WIN-DIAG-03 smoke.

**R4 — The reported integrity level is not the daemon's.** Likelihood high (whenever doctor is run
from a console other than the task's), impact medium (a user reads "high" and concludes their
elevated-window problem is elsewhere). Mitigation: report both the calling process's level and the
task's registered run level in one line, and word the caveat off the *process* level only. Covered
by WIN-DIAG-05's `test_format_integrity_status_warns_only_at_medium`. Residual: doctor still cannot
see the *foreground* window's integrity, so it reports a static risk, never a live diagnosis — this
is the diagnostics-side floor of SCOPE.md §7 risk 1 / §D7 and is accepted.

**R5 — `schtasks` "not found" is indistinguishable from "query failed".** Likelihood medium
(`schtasks` returns non-zero for both, with localized stderr); impact medium (doctor prints
"unknown (cannot query Task Scheduler)" on a healthy box, and setup's install hint never fires).
Mitigation: WIN-DIAG-P9's fixed mapping, driven by exit code plus empty XML rather than by message
text, with `/xml` chosen over the localized `/fo LIST /v`. Covered by
WIN-DIAG-05's `test_missing_task_maps_to_none_inactive` and its smoke case. The parser itself is
WIN-LIFE's; this domain owns only the mapping onto `(enabled, active)`.

**R6 — `stdin.isatty()` is true but there is no Win32 console handle.** Likelihood medium (mintty,
MSYS, some CI shells and ConPTY wrappers), impact low (capture is unavailable, setup still
completes). Mitigation: `GetConsoleMode` failure raises `BindingCaptureError` with the Linux wording,
and `_capture_or_choose_binding`'s existing retry/type/keep menu is the recovery. Covered by
WIN-DIAG-07 acceptance; the typed-binding and `--quick` paths never touch console mode.

**R7 — Config saves lose NTFS ACLs and fail outright on read-only targets.** Likelihood low
(read-only), medium (hardened ACLs), impact medium (an exit-1 save after the backup was written
looks like data loss to the user). Not covered by any SCOPE.md §7 risk — this is new. Mitigation:
the `PermissionError` retry and the explicit documentation of what "mode preservation" means on
Windows. Covered by WIN-DIAG-08.

**R8 — A Windows user sets `hotkey.device` anyway.** Likelihood medium (the prompt still accepts a
typed value, because suppressing the affordance would mean a platform conditional in
`_prompt_device`); impact low (§D5's one-time warning; dictation still works). Mitigation:
`hotkey_device_note` says the key is ignored before the prompt is shown. Covered by WIN-DIAG-04's
smoke transcript check.
