# Windows Domain — Lifecycle and Service

Owns the Windows process lifetime: the single-instance named mutex, the environment and
creation flags for spawned children, console control-event shutdown, the kill-on-close job
object that stops the ASR worker and overlay helper with the daemon, the `schtasks` logon task
of README §D2 (builder, parser, restart) including the `elevated` flag of §D7, and the user
directory policy. The blast area is contained inside `platform/windows/`: every item here is
reachable only through `WindowsPlatform` methods the core already calls, so no core module,
no protocol, and no Linux path changes. Text and prompts are not owned here (WIN-DIAG), nor is
the installer that registers the task (WIN-PKG).

## Designed source tree

Rows from README §T owned by this domain; the rest of the tree is unchanged by it.

| Path | Marker | Role |
|---|---|---|
| `src/stenographer/platform/windows/lock.py` | NEW | `MutexSingleInstanceLock` over `CreateMutexW("Local\\stenographer")` plus the pure contention classifier. |
| `src/stenographer/platform/windows/process.py` | NEW | Child env scrub, no-window creation flags, `SetConsoleCtrlHandler` stop path, kill-on-close job object. |
| `src/stenographer/platform/windows/service.py` | NEW | Logon-task XML renderer, `schtasks` argv builders, `/FO LIST /V` parser, `service_status`, `restart_service`. |
| `src/stenographer/platform/windows/__init__.py` | EDIT | Replaces four degraded returns: `single_instance_lock`, `helper_spawn_kwargs`, `install_stop_signal_handlers`, `restart_service`. |
| `tests/platform/windows/` | NEW | Windows-only tests plus `conftest.py` (`collect_ignore_glob = [] if sys.platform == "win32" else ["*.py"]`), mirroring `tests/platform/linux/conftest.py`. |

`platform/windows/dirs.py` is deliberately **not** created: §T lists no such row, and unlike Linux —
where `lock.py` imports `dirs.runtime_dir` to place the flock file — the Windows lock is a kernel
object with no path, so the directory policy has no second consumer inside the provider. It stays
in `__init__.py` (WIN-LIFE-08).

## Architecture principles

Global rules are not restated; §P1 (lazy provider imports), §P4 (callback discipline), §P5 (every
backend keeps a pure unit target), §P6 (no mock theater), §P9 (privacy), §P10 (SPDX and tooling)
bind this domain as written.

- **WIN-LIFE-P1 — Declared ctypes prototypes.** Every Win32 function used here sets `.argtypes`
  and `.restype` before its first call, and every handle is `ctypes.c_void_p` — never the default
  `c_int` return, which truncates a 64-bit `HANDLE` to a plausible-looking non-zero value and
  keeps running. `kernel32` is obtained as `ctypes.WinDLL("kernel32", use_last_error=True)` and the
  error code is read with `ctypes.get_last_error()` on the statement immediately after the call,
  before any other ctypes traffic.
- **WIN-LIFE-P2 — The three modules import on Linux.** `lock.py`, `process.py`, and `service.py`
  must import cleanly on a non-Windows host: no module-scope `WinDLL`, no `import ctypes.wintypes`
  (it raises on Linux), and structures declared with fixed-width `c_uint32` / `c_uint64` /
  `c_size_t` rather than `DWORD` / `ULONG` aliases, so layouts are identical under LLP64 and LP64.
  This extends §P1 beyond `__init__.py`, because `tests/platform/test_platform.py` is collected on
  Linux and constructs provider objects there, and the Linux bundle `collect_submodules` this
  package.
- **WIN-LIFE-P3 — Callback and handle lifetime is explicit.** The `WINFUNCTYPE` console-handler
  object and the job-object handle live in module-level globals for the process lifetime. A
  garbage-collected handler object means Windows calls freed memory at close time; closing the job
  handle terminates every member of the job, the daemon included. Neither object is ever released.
- **WIN-LIFE-P4 — Single-instance identity is object existence, not mutex ownership.** The lock
  calls `CreateMutexW(NULL, FALSE, "Local\\stenographer")` and treats `ERROR_ALREADY_EXISTS` as the
  only contention signal; `release()` is `CloseHandle` alone. `WaitForSingleObject` and
  `ReleaseMutex` are never used: mutex ownership is thread-affine, and `release()` runs on whichever
  thread unwound `daemon.run(cfg)` — a non-owning thread would fail with `ERROR_NOT_OWNER` and leave
  the lock apparently held. On the contention path the handle returned alongside
  `ERROR_ALREADY_EXISTS` is closed before returning `False`.
- **WIN-LIFE-P5 — The console handler runs on a thread Windows injects.** It is not the POSIX
  signal-handler model the core assumes: `daemon.run(cfg)`'s `_handler` is invoked on a foreign
  thread while the main thread sits in `Daemon.run`'s `self._stop_event.wait()`. The handler may
  therefore only set events (`Daemon.request_stop` sets `threading.Event` and nothing else). It must
  not take `Daemon._lock`, call `signal.signal` (main-thread-only), import a module, or perform
  I/O. This is §P4's rule applied to the other injected callback in the provider.
- **WIN-LIFE-P6 — Only valid `signal.Signals` members cross the boundary.** `daemon.run(cfg)`'s
  handler formats `signal.Signals(signum).name`. Raw console control codes must never be passed
  through: `CTRL_LOGOFF_EVENT` (5) and `CTRL_SHUTDOWN_EVENT` (6) are not members of `signal.Signals`
  on Windows and would raise `ValueError` inside the handler, so the stop request would be dropped
  and the daemon would never stop. `process.py` maps events to signal numbers before invoking the
  core handler.
- **WIN-LIFE-P7 — Shutdown correctness never depends on the shutdown budget.** `CTRL_CLOSE_EVENT`
  grants roughly 5 s before a force-kill, while `Daemon.stop()` may spend up to
  `2 x _PIPELINE_JOIN_SECONDS` (60 s) joining the warm-up and pipeline threads. The budget is
  therefore best-effort by construction, and every lifetime-critical resource must be correct under
  `TerminateProcess`: the mutex is destroyed when the kernel closes the last handle, `logging`
  flushes per record so the rotating file loses nothing, and children die with the job object.
  Nothing may be added whose only cleanup path is the graceful one.
- **WIN-LIFE-P8 — `schtasks` is reached only through `service.py`'s pure builders.** No other
  module composes a `schtasks` argv. Every invocation passes `env=child_env()`, the no-window
  creation flags, and a bounded `timeout=`, and classifies `OSError` / `TimeoutExpired` the same way
  `platform/linux/probe.py:service_status` classifies a failed `systemctl` query.
- **WIN-LIFE-P9 — The `(enabled, active)` vocabulary is systemd's, not schtasks'.** The parser
  emits only `{None, "enabled", "disabled"}` x `{None, "active", "inactive", "failed"}`, and "task
  not registered" is exactly `(None, "inactive")` — the shape `systemctl is-enabled` /
  `is-active` produce for an uninstalled unit, which `cli/doctor.py:format_service_status` and
  `cli/setup.py:_print_quick_tryout` already branch on. No core branch, label, or comparison changes
  to accommodate Windows.
- **WIN-LIFE-P10 — Nothing re-adds auto-restart.** Per §D2 the task document carries no restart
  setting and no second process. The supervisor wrapper is deferred with its reconciliations
  recorded below; adding one is a §D2 revision, not an implementation choice.

### The rotating state-file log

`utils/logging_setup.setup_logging()` in the **daemon parent process** is the sole owner of the
5 MiB x 3 `RotatingFileHandler` at `state_dir() / "stenographer.log"` —
`%LOCALAPPDATA%\stenographer\stenographer.log` under the policy WIN-LIFE-08 freezes. Nothing in
this domain opens, closes, rotates, or adds handlers to it: not `service.py`, not the console
control handler (P5), not the job-object code. The ASR worker already forwards records over the
multiprocessing queue and never opens the file; the overlay helper must not either. The rule is
stricter on Windows than on Linux because rotation is a rename and Windows refuses to rename a file
another process holds open — a second writer does not interleave, it breaks rotation permanently.
The single-instance mutex is what guarantees a single writer, which makes WIN-LIFE-01 a
prerequisite of log correctness and not only of dictation correctness.

### Deferred: the supervisor wrapper (§D2)

Recorded so the deferral is on record rather than an omission. §D2 accepts that a transient crash
leaves dictation dead until next logon; a wrapper process that re-launches the daemon on non-78
exits is the known alternative, and adding it later changes only `<Command>` / `<Arguments>` in the
task document (WIN-LIFE-05). Three reconciliations must be solved before it can land:

1. **The child holds the mutex, not the parent.** If the supervisor acquires
   `Local\stenographer`, its handle keeps the object alive across every restart and each new child
   sees `ERROR_ALREADY_EXISTS` and exits 1 — an auto-restart loop that never restarts.
2. **`CTRL_CLOSE_EVENT` must be forwarded without respawning.** The supervisor must distinguish
   console/logoff shutdown from a child crash; otherwise closing the console resurrects the daemon,
   and the 5 s budget is spent starting a process rather than stopping one.
3. **The supervisor must not open the rotating log file.** Two `RotatingFileHandler`s on one path
   break rotation on Windows (above). The supervisor logs to stderr or not at all.

A fourth, cheaper consequence: the job object (WIN-LIFE-04) moves to the supervisor, with the
daemon as a member, or a crashed daemon's ASR child outlives every restart.

### Where §D2's accepted regression is surfaced

The absence of `Restart=on-failure` must appear in exactly three user-visible places, all owned by
other domains and all fed by constants exported from `service.py`:

1. `scripts/install.ps1` post-install notes, where `scripts/install.sh` prints the unit path and
   `systemctl --user status` line — WIN-PKG.
2. `doctor`'s service line, alongside the registered/not-registered state this domain supplies —
   WIN-DIAG.
3. `setup`'s post-save service message, the branch `cli/setup.py` reaches when
   `caps.service_active != "active"` — WIN-DIAG.

## Functional criteria

### WIN-LIFE-01 — Implement the named-mutex single-instance lock
Phase: 1   Depends on: none
Files: `src/stenographer/platform/windows/lock.py` (NEW),
`src/stenographer/platform/windows/__init__.py` (EDIT),
`tests/platform/windows/conftest.py` (NEW, if no other item has created it),
`tests/platform/windows/test_lock.py` (NEW), `tests/platform/test_platform.py` (EDIT)
Pure tests: `tests/platform/windows/test_lock.py::test_is_mutex_contention_only_already_exists`,
`tests/platform/windows/test_lock.py::test_lock_name_is_session_local`,
`tests/platform/test_platform.py::test_windows_lock_constructs_without_win32`
Smoke: `smoke_mutex_contention_between_processes`, `smoke_mutex_free_after_hard_kill`
Done when: a second `stenographer run` on the same Windows session prints "another instance is
already running." and exits 1, while the first keeps dictating.

`lock.py` exports `LOCK_NAME = "Local\\stenographer"`, `ERROR_ALREADY_EXISTS = 183`, the pure
`is_mutex_contention(last_error: int) -> bool`, and `MutexSingleInstanceLock` (`acquire`,
`release`) mirroring `platform/linux/lock.py:FlockSingleInstanceLock`. `acquire()` calls
`CreateMutexW(None, False, LOCK_NAME)`, reads `ctypes.get_last_error()` immediately, raises
`SingleInstanceLockError` on a NULL handle (chaining `ctypes.WinError(err)`), closes the handle and
returns `False` on contention, stores it and returns `True` otherwise; a second `acquire()` on a
held lock returns `True` without opening a second handle. `release()` is `CloseHandle` on a held
handle and a no-op otherwise. `WindowsPlatform.single_instance_lock()` lazy-imports the module and
returns the instance; the existing assertion in
`tests/platform/test_platform.py::test_windows_stub_conforms_and_reports_everything_unavailable`
that it raises `UnsupportedPlatformError` is replaced by a Protocol-conformance assertion.

### WIN-LIFE-02 — Implement child environment and no-window spawn flags
Phase: 1   Depends on: none
Files: `src/stenographer/platform/windows/process.py` (NEW),
`src/stenographer/platform/windows/__init__.py` (EDIT),
`tests/platform/windows/test_process_env.py` (NEW)
Pure tests: `tests/platform/windows/test_process_env.py::test_scrub_removes_pyinstaller_vars_when_frozen`,
`tests/platform/windows/test_process_env.py::test_scrub_is_identity_when_not_frozen`,
`tests/platform/windows/test_process_env.py::test_no_window_kwargs_flag_value`
Smoke: `smoke_overlay_helper_spawns_without_console_flash`
Done when: `WindowsPlatform().helper_spawn_kwargs()` returns
`{"creationflags": CREATE_NO_WINDOW}` and no console window appears when the daemon spawns a child.

`process.py` exports `CREATE_NO_WINDOW = 0x08000000`, the pure
`_scrub(env: dict[str, str], frozen: bool) -> dict[str, str]` (mirroring
`platform/linux/process.py`, removing `_PYI_APPLICATION_HOME_DIR`, `_PYI_ARCHIVE_FILE`, and
`_MEIPASS2` when frozen and copying otherwise), `child_env()`, `no_window_kwargs()`, and
`helper_spawn_kwargs()`. `no_window_kwargs()` is the single source of the flag for every subprocess
this provider spawns — the overlay helper, `schtasks` (WIN-LIFE-05..07), and the PowerShell toast
(WIN-FEED: notifier) — so a windowless daemon never flashes a console.

### WIN-LIFE-03 — Install the console control handler
Phase: 1   Depends on: WIN-LIFE-02
Files: `src/stenographer/platform/windows/process.py` (EDIT),
`src/stenographer/platform/windows/__init__.py` (EDIT),
`tests/platform/windows/test_console_ctrl.py` (NEW)
Pure tests: `tests/platform/windows/test_console_ctrl.py::test_console_ctrl_signal_declines_ctrl_c`,
`tests/platform/windows/test_console_ctrl.py::test_console_ctrl_signal_maps_close_logoff_shutdown`,
`tests/platform/windows/test_console_ctrl.py::test_console_ctrl_signal_values_are_signal_members`,
`tests/platform/windows/test_console_ctrl.py::test_shutdown_budget_is_under_close_timeout`
Smoke: `smoke_console_ctrl_break_stops_daemon`, `smoke_console_close_stops_daemon_within_budget`
Done when: pressing Ctrl+Break in a foreground `stenographer run`, and closing its console window,
both stop the daemon through the same `Daemon.request_stop` path that Ctrl+C uses.

`process.py` gains the pure `console_ctrl_signal(event: int) -> int | None`
(`CTRL_C_EVENT` 0 -> `None`; `CTRL_BREAK_EVENT` 1 -> 21 / `SIGBREAK`; `CTRL_CLOSE_EVENT` 2,
`CTRL_LOGOFF_EVENT` 5, `CTRL_SHUTDOWN_EVENT` 6 -> 15 / `SIGTERM`; anything else -> `None`),
`SHUTDOWN_BUDGET_SECONDS = 4.0`, a module-global `_shutdown_done = threading.Event()` with
`mark_shutdown_complete()` registered through `atexit.register` at install time, and
`install_stop_signal_handlers(handler)` which keeps the stub's `signal.signal(SIGINT, handler)`,
then registers a module-global `WINFUNCTYPE(c_int, c_uint32)` callback with
`SetConsoleCtrlHandler(cb, True)`. Declining `CTRL_C_EVENT` (returning 0) is required so the C
runtime's own handler still raises `SIGINT` on the main thread and `KeyboardInterrupt` semantics —
including `cli/binding_capture` — are unchanged. For a handled event the callback calls
`handler(signum, None)`, waits `_shutdown_done` for `SHUTDOWN_BUDGET_SECONDS`, and returns 1. A
`SetConsoleCtrlHandler` failure (a windowless daemon under the logon task has no console) is logged
at debug and is not fatal.

Budget contract, stated for review: inside the ~5 s the handler must stop the listener (its
`stop(timeout=2.0)`), stop the recorder and zero its samples, and let the parent's logging handlers
flush. Explicitly abandonable: the up-to-30 s warm-up and pipeline joins in `Daemon.stop()`, the
in-flight transcription's result, the ASR worker's graceful exit, overlay helper reaping, and cue
playback. Per WIN-LIFE-P7 nothing in that abandoned set can leave persistent damage.

### WIN-LIFE-04 — Assign the daemon to a kill-on-close job object
Phase: 1   Depends on: WIN-LIFE-03
Files: `src/stenographer/platform/windows/process.py` (EDIT),
`tests/platform/windows/test_job_object.py` (NEW)
Pure tests: `tests/platform/windows/test_job_object.py::test_extended_limit_information_layout`,
`tests/platform/windows/test_job_object.py::test_kill_on_job_close_flag_value`
Smoke: `smoke_job_kills_asr_child_on_hard_kill`
Done when: force-killing the daemon (Task Manager, or `schtasks /End`) leaves no surviving
`stenographer` ASR worker or overlay helper process.

`process.py` gains `install_child_job() -> bool`, called from `install_stop_signal_handlers()`
before the console handler is registered: `CreateJobObjectW(None, None)`, then
`SetInformationJobObject(job, JobObjectExtendedLimitInformation=9, ...)` with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000`, then
`AssignProcessToJobObject(job, GetCurrentProcess())`; the handle is kept in a module global forever
(WIN-LIFE-P3). Children inherit membership, so the spawned ASR worker and overlay helper die with
the daemon under any termination path. Nested jobs are supported on Windows 8+, so membership in a
Task Scheduler or container job does not defeat this; a failure at any step is logged at debug and
leaves the daemon running. This closes the gap that Linux gets free from the systemd unit's
control-group kill, and it is the reason `schtasks /End` (a hard terminate of the top-level process
only) does not strand a 1.5 GB model in RAM.

### WIN-LIFE-05 — Build the logon-task document and schtasks commands
Phase: 2   Depends on: WIN-LIFE-02
Files: `src/stenographer/platform/windows/service.py` (NEW),
`tests/platform/windows/test_service_builder.py` (NEW)
Pure tests: `tests/platform/windows/test_service_builder.py::test_task_xml_is_wellformed_and_escapes_paths`,
`tests/platform/windows/test_service_builder.py::test_task_xml_disables_battery_and_time_limits`,
`tests/platform/windows/test_service_builder.py::test_task_xml_run_level_follows_elevated_flag`,
`tests/platform/windows/test_service_builder.py::test_task_xml_has_no_restart_settings`,
`tests/platform/windows/test_service_builder.py::test_build_commands_argv`,
`tests/platform/windows/test_service_builder.py::test_parse_run_level_roundtrips_rendered_xml`
Smoke: `smoke_logon_task_register_query_delete`
Done when: `schtasks /Create /TN stenographer /XML <rendered> /F` succeeds unelevated for the
current user, and the registered task starts the daemon at next logon.

`service.py` exports `TASK_NAME = "stenographer"` and the pure builders:
`render_task_xml(*, command: str, arguments: str, user_id: str, elevated: bool) -> str`,
`build_create_command(xml_path, *, task_name=TASK_NAME)`, `build_query_command(...)`,
`build_query_xml_command(...)` (`["schtasks", "/Query", "/TN", name, "/XML", "ONE"]`),
`build_end_command(...)`, `build_run_command(...)`, `build_delete_command(...)`, and the pure
`parse_run_level(xml_text) -> str | None`. `current_user_id()` (reading `USERDOMAIN` / `USERNAME`)
is the impure half and stays out of the renderer.

The document is registered with `/XML` rather than assembled from `/Create` flags for four reasons
that the flag form cannot address, none of which changes §D2's decision — it is still a plain
`ONLOGON` logon task with no auto-restart: `schtasks /Create` defaults
`ExecutionTimeLimit` to `PT72H` (the daemon would be terminated after three days of uptime),
defaults `DisallowStartIfOnBatteries` and `StopIfGoingOnBatteries` to true (dictation would not
start, or would be stopped, on an unplugged laptop), offers no way to set
`MultipleInstancesPolicy`, and forces the whole command line through one `/TR` string whose quoting
is destroyed by `subprocess.list2cmdline` for any path containing a space. The rendered document
sets `<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>`, both battery settings false,
`<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>`,
`<LogonType>InteractiveToken</LogonType>`, a `<LogonTrigger>` scoped to `user_id`, and separate
`<Command>` / `<Arguments>` elements. §D7's `/RL HIGHEST` opt-in maps to
`<RunLevel>HighestAvailable</RunLevel>`; `elevated=False` maps to `<RunLevel>LeastPrivilege</RunLevel>`
(`/RL LIMITED`). The file is written UTF-16LE with BOM, which is what `schtasks /Create /XML`
accepts. WIN-PKG (installer) calls these builders; WIN-DIAG (setup, doctor) owns offering
`elevated` and reporting `parse_run_level`.

### WIN-LIFE-06 — Parse task state into the systemd status vocabulary
Phase: 2   Depends on: WIN-LIFE-05
Files: `src/stenographer/platform/windows/service.py` (EDIT),
`tests/platform/windows/test_service_query.py` (NEW)
Pure tests: `tests/platform/windows/test_service_query.py::test_parse_query_list_running_task`,
`tests/platform/windows/test_service_query.py::test_parse_query_list_ready_and_disabled`,
`tests/platform/windows/test_service_query.py::test_parse_query_list_could_not_start_is_failed`,
`tests/platform/windows/test_service_query.py::test_parse_query_list_localized_output_is_unknown`,
`tests/platform/windows/test_service_query.py::test_status_vocabulary_matches_core_branches`
Smoke: `smoke_service_status_registered`, `smoke_service_status_not_registered`
Done when: `stenographer doctor` prints `enabled, active` while the logon task is running the
daemon, and the not-installed line when no task is registered.

`service.py` gains the pure `parse_query_list(stdout: str) -> tuple[str | None, str | None]` over
`schtasks /Query /TN stenographer /FO LIST /V` output — `Scheduled Task State: Enabled|Disabled`
-> `"enabled"` / `"disabled"`, `Status: Running` -> `"active"`, `Ready`/`Disabled` -> `"inactive"`,
`Could not start` -> `"failed"`, absent field -> `None` — and the impure `service_status()`
mirroring `platform/linux/probe.py:service_status`: `shutil.which("schtasks") is None`,
`OSError`, or `TimeoutExpired` (`timeout=5`) -> `(None, None)`; a non-zero exit (the task is not
registered) -> `(None, "inactive")`; success -> `parse_query_list(stdout)`.

The mapping onto the core branches that already exist, per WIN-LIFE-P9:
`cli/doctor.py:format_service_status` returns "unknown" for `(None, None)`, "not installed" for
`enabled is None`, and `f"{enabled}, {active}"` otherwise; `cli/setup.py:restart_eligible` offers a
restart only when `service_active == "active"`, i.e. only when the task's `Status` is `Running`;
`cli/setup.py:_guided_setup` reaches its "not installed" branch on `caps.service_enabled is None`;
and `cli/setup.py:_print_quick_tryout` reaches its "service is not installed" branch on
`service_enabled is None and service_active == "inactive"` — which is why an unregistered task must
map to `(None, "inactive")` and not to `(None, None)`. WIN-DIAG's `probe.py` calls
`service_status()` and puts the pair into `HostProbe`.

### WIN-LIFE-07 — Implement restart_service over /End then /Run
Phase: 2   Depends on: WIN-LIFE-05, WIN-LIFE-06
Files: `src/stenographer/platform/windows/service.py` (EDIT),
`src/stenographer/platform/windows/__init__.py` (EDIT),
`tests/platform/windows/test_service_restart.py` (NEW)
Pure tests: `tests/platform/windows/test_service_restart.py::test_restart_detail_from_failed_run`,
`tests/platform/windows/test_service_restart.py::test_restart_settle_deadline_is_bounded`
Smoke: `smoke_restart_task_cycles_process`
Done when: answering yes to setup's "Restart the active stenographer.service to apply changes?"
replaces the running daemon with a new process that reads the saved configuration.

`service.py` gains `restart_service() -> tuple[bool, str]`: run `build_end_command()`
(`timeout=10`, exit code ignored and logged at debug, since `/End` fails when the task is not
running), poll `service_status()` every 0.25 s for up to `SETTLE_SECONDS = 5.0` until `active` is
no longer `"active"`, then run `build_run_command()` (`timeout=15`). A non-zero `/Run` exit returns
`(False, stderr.strip() or f"schtasks exited {rc}")`; `OSError` / `TimeoutExpired` returns
`(False, str(exc))`; success returns `(True, "")` — the exact contract
`cli/setup.py:_restart_service` and `cli/sounds.py` consume. The settle poll is load-bearing: the
task's default `MultipleInstancesPolicy` is `IgnoreNew` (WIN-LIFE-05), so a `/Run` issued while the
previous instance is still terminating is silently dropped and the daemon never comes back.
`WindowsPlatform.restart_service()` lazy-imports and delegates, replacing the stub's
`(False, "no service manager integration on Windows")`.

### WIN-LIFE-08 — Freeze the Windows directory policy
Phase: 1   Depends on: none
Files: `src/stenographer/platform/windows/__init__.py` (EDIT),
`tests/platform/test_platform.py` (EDIT)
Pure tests: `tests/platform/test_platform.py::test_windows_stub_directories_honour_xdg_then_windows_conventions`
(extended), `tests/platform/test_platform.py::test_windows_runtime_dir_honours_xdg_runtime_home`
Smoke: none — the policy is a pure function of `env` and `home` and is fully covered by tests that
run on both CI hosts; nothing observable requires a real Windows host.
Done when: `config_path`, `state_dir`, and `runtime_dir` each consult their `XDG_*` variable first
and fall back to `%APPDATA%` / `%LOCALAPPDATA%`, with no new module.

The policy stays in `__init__.py` (see *Designed source tree*). The one change is consistency:
`runtime_dir` currently ignores `XDG_RUNTIME_DIR` while `config_path` and `state_dir` honour
`XDG_CONFIG_HOME` / `XDG_STATE_HOME`, contradicting §T's and SCOPE.md §1's description of the
policy as "honouring `XDG_*`". It gains the same first-choice lookup. No Windows consumer of
`runtime_dir` exists or is planned — the single-instance lock is a kernel object with no path
(WIN-LIFE-01), which is the reason no `dirs.py` is warranted — so the change is alignment, not
mechanism. The item also asserts that `state_dir` is what `utils/logging_setup` resolves the
5 MiB x 3 rotating log against.

## Acceptance criteria

Pure tests live under `tests/platform/windows/` (Windows-only collection) except where a path
above says otherwise; smoke cases carry `@pytest.mark.integration` and run only with
`STENOGRAPHER_INTEGRATION=1` on a real Windows machine, per AGENTS.md rule 4 and §D8. No criterion
below is satisfiable by mocking a Win32 call or `subprocess` (§P6).

### WIN-LIFE-01
- `test_is_mutex_contention_only_already_exists`: `183 -> True`; `0`, `5` (`ERROR_ACCESS_DENIED`),
  `6` (`ERROR_INVALID_HANDLE`), `1450` -> `False`. Must be seen to fail against the plausible wrong
  implementation `return last_error != 0`, which turns a permissions failure into a silent
  "another instance is running" and exit 1 instead of the exit 78 that `SingleInstanceLockError`
  produces.
- `test_lock_name_is_session_local`: `LOCK_NAME` starts with `Local\` and contains exactly one
  backslash. Seen to fail against `Global\stenographer`, which would make a second logged-on user's
  daemon report contention.
- `test_windows_lock_constructs_without_win32` (collected on Linux): importing
  `stenographer.platform.windows.lock` and constructing `MutexSingleInstanceLock()` succeeds on the
  Linux CI host, and `isinstance(WindowsPlatform().single_instance_lock(), SingleInstanceLock)`
  holds. Seen to fail against a module-scope `ctypes.WinDLL("kernel32")` — which also breaks the
  Linux bundle's `collect_submodules` (§P1, WIN-LIFE-P2).
- `smoke_mutex_contention_between_processes`: start a real holder as a child
  (`sys.executable -c "...MutexSingleInstanceLock().acquire(); input()"` with `child_env()`), assert
  the parent's `acquire()` returns `False` and raises nothing, close the child's stdin, wait for
  exit, then assert `acquire()` returns `True`. Proves both contention and the absence of a stale
  lock after a clean exit.
- `smoke_mutex_free_after_hard_kill`: same holder, terminated with `Popen.kill()`
  (`TerminateProcess`), then `acquire()` returns `True` within 1 s. Proves the answer to "what if
  the process dies without releasing": the kernel closes the last handle, the object is destroyed,
  and no stale lock file exists to clean up — unlike a PID file.
- Observable: two `stenographer run` invocations in one session; the second prints "another
  instance is already running." and exits 1 (`daemon.run(cfg)`'s `not acquired` path), while a lock
  I/O failure prints the `SingleInstanceLockError` message and exits 78.

### WIN-LIFE-02
- `test_scrub_removes_pyinstaller_vars_when_frozen`: with `frozen=True`, `_PYI_APPLICATION_HOME_DIR`,
  `_PYI_ARCHIVE_FILE`, and `_MEIPASS2` are absent from the result and every other key survives
  unchanged. Seen to fail against `return dict(env)`, which lets a frozen daemon's PyInstaller
  variables reach `schtasks` and PowerShell and mis-resolve a nested frozen re-exec.
- `test_scrub_is_identity_when_not_frozen`: with `frozen=False` the mapping is equal to the input
  and is not the same object. Seen to fail against unconditional scrubbing, which would strip a
  developer's deliberately set variables under `pip install -e`.
- `test_no_window_kwargs_flag_value`: `no_window_kwargs() == {"creationflags": 0x08000000}` and
  `helper_spawn_kwargs()` returns an equal mapping. Seen to fail against `DETACHED_PROCESS`
  (`0x00000008`), which detaches the helper from job-object-adjacent console semantics and changes
  its stdio handles.
- `smoke_overlay_helper_spawns_without_console_flash`: run the daemon from a windowless launcher
  (`pythonw.exe` or the frozen exe), trigger a helper spawn, and assert with
  `GetConsoleWindow()`/screen observation that no console window appeared and the helper's PID is a
  child of the daemon. Verified by the operator during the merge-gate run.

### WIN-LIFE-03
- `test_console_ctrl_signal_declines_ctrl_c`: `console_ctrl_signal(0) is None`. Seen to fail against
  a mapping that handles `CTRL_C_EVENT`, which suppresses the C runtime's `SIGINT` and breaks
  `KeyboardInterrupt` in `binding_capture` and in a foreground `stenographer run`.
- `test_console_ctrl_signal_maps_close_logoff_shutdown`: `1 -> 21`, `2 -> 15`, `5 -> 15`, `6 -> 15`,
  `3 -> None`, `99 -> None`.
- `test_console_ctrl_signal_values_are_signal_members`: every non-`None` return satisfies
  `signal.Signals(value)`. Seen to fail against passing the raw event code through:
  `signal.Signals(5)` raises `ValueError` inside `daemon.run(cfg)`'s `_handler`, so the stop
  request is dropped and the daemon runs until the force-kill.
- `test_shutdown_budget_is_under_close_timeout`: `0 < SHUTDOWN_BUDGET_SECONDS <= 4.5`. Seen to fail
  against reusing `daemon._PIPELINE_JOIN_SECONDS` (30.0), which would guarantee the force-kill.
- `smoke_console_ctrl_break_stops_daemon`: start `stenographer run` in a new process group
  (`CREATE_NEW_PROCESS_GROUP`), send `GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pid)`, assert exit
  within 5 s with code 0 and that the log's last records show the normal stop path (listener
  stopped, recorder closed) — the same records a `SIGTERM` produces on Linux.
- `smoke_console_close_stops_daemon_within_budget`: launch the daemon in its own console window,
  close the window, and assert the mutex is immediately re-acquirable and no `stenographer` process
  survives. This is the case that proves WIN-LIFE-P7: it passes whether the graceful path finished
  or the force-kill won.
- Observable: all three of Ctrl+C, Ctrl+Break, and window close stop the daemon, and none of them
  leaves a held mutex, an orphaned child, or a truncated log.

### WIN-LIFE-04
- `test_extended_limit_information_layout`:
  `ctypes.sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION) == 144` and
  `ctypes.sizeof(JOBOBJECT_BASIC_LIMIT_INFORMATION) == 64` on a 64-bit interpreter. Seen to fail
  against declaring `DWORD` fields as `ctypes.c_ulong` (correct on Windows, 8 bytes on Linux) and
  against omitting the `IO_COUNTERS` member, both of which make `SetInformationJobObject` fail
  with `ERROR_BAD_LENGTH` while the daemon keeps running with no child containment.
- `test_kill_on_job_close_flag_value`: `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0x2000` and
  `JobObjectExtendedLimitInformation == 9`. Seen to fail against `0x1000`
  (`JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION`), which silently containment-does-nothing.
- `smoke_job_kills_asr_child_on_hard_kill`: run the daemon until the ASR worker has loaded the
  model (one dictation), record the worker PID, `Popen.kill()` the daemon, then assert within 5 s
  that the worker PID no longer exists and that no `stenographer` process remains. Repeat with
  `schtasks /End /TN stenographer` as the kill mechanism.
- Observable: after any daemon death, Task Manager shows no leftover `stenographer` process and no
  ~1.5 GB resident model.

### WIN-LIFE-05
- `test_task_xml_is_wellformed_and_escapes_paths`: `xml.etree.ElementTree.fromstring` parses the
  rendered document, and rendering with
  `command=r"C:\Users\A&B\Programs\stenographer\stenographer.exe"` yields `A&amp;B` in `<Command>`
  and still parses. Seen to fail against f-string interpolation without `xml.sax.saxutils.escape`,
  which makes `schtasks` reject the document with "The task XML is malformed" only for users whose
  profile path contains `&`.
- `test_task_xml_disables_battery_and_time_limits`: the parsed document has
  `ExecutionTimeLimit == "PT0S"`, `DisallowStartIfOnBatteries == "false"`,
  `StopIfGoingOnBatteries == "false"`, `MultipleInstancesPolicy == "IgnoreNew"`. Seen to fail
  against omitting the elements — Task Scheduler then applies its defaults (`PT72H`, battery stop),
  which kill a laptop daemon on unplug and every running daemon after three days.
- `test_task_xml_run_level_follows_elevated_flag`: `elevated=True` -> `HighestAvailable`,
  `elevated=False` -> `LeastPrivilege`, and the flag changes nothing else in the document (diff of
  the two renderings touches one element). Seen to fail against defaulting to `HighestAvailable`,
  which is exactly the default §D7 rejects.
- `test_task_xml_has_no_restart_settings`: the document contains no `RestartOnFailure`,
  `RestartCount`, or `RestartInterval` element (§D2, WIN-LIFE-P10).
- `test_build_commands_argv`: each builder returns a list whose first element is `"schtasks"`,
  whose `/TN` value is `TASK_NAME`, and which contains no shell metacharacter concatenation;
  `build_create_command` contains `/XML` and `/F`; `build_query_command` ends with
  `["/FO", "LIST", "/V"]`.
- `test_parse_run_level_roundtrips_rendered_xml`: rendering with `elevated=True` and parsing it
  back yields `"HighestAvailable"`, the `False` case yields `"LeastPrivilege"`, and unrelated XML
  or empty input yields `None`. This is the function WIN-DIAG reports from, so the roundtrip is
  the contract.
- `smoke_logon_task_register_query_delete`: on a real Windows machine, as a standard (non-admin)
  user, write the rendered document UTF-16LE with BOM to a temp path, run `build_create_command`,
  assert exit 0; run `build_query_xml_command` and assert the readback document has `PT0S`, both
  battery settings false, `LeastPrivilege`, and the installed exe path; then
  `build_delete_command` with `/F` and assert the task is gone. The test must leave no task behind.
- Observable: after the installer registers the task, logging off and back on starts the daemon,
  and it is still running three days later.

### WIN-LIFE-06
- `test_parse_query_list_running_task`: a captured real `/FO LIST /V` sample with
  `Status: Running` and `Scheduled Task State: Enabled` parses to `("enabled", "active")`.
- `test_parse_query_list_ready_and_disabled`: `Ready` -> `("enabled", "inactive")`;
  `Scheduled Task State: Disabled` with `Status: Disabled` -> `("disabled", "inactive")`. Seen to
  fail against passing schtasks' own words through (`("Enabled", "Ready")`), which makes
  `restart_eligible` never offer a restart and makes doctor print "Enabled, Ready".
- `test_parse_query_list_could_not_start_is_failed`: `Status: Could not start` ->
  `("enabled", "failed")`, so doctor renders `enabled, failed` exactly as it does for a failed
  systemd unit.
- `test_parse_query_list_localized_output_is_unknown`: a German sample (`Status: Bereit`,
  `Status des geplanten Tasks: Aktiviert`) parses to `(None, None)`. Seen to fail against a parser
  that splits on the first colon and returns the raw right-hand side, which would put a localized
  word into the wire vocabulary; `(None, None)` degrades to doctor's "unknown" line instead.
- `test_status_vocabulary_matches_core_branches`: every value the parser and `service_status()` can
  produce is a member of `{None, "enabled", "disabled"}` / `{None, "active", "inactive", "failed"}`,
  asserted against the literal branch constants imported from `cli.doctor` and `cli.setup`
  (`restart_eligible(..., service_active="active")` is `True`; the not-installed pair
  `(None, "inactive")` makes `format_service_status` return its "not installed" string). Seen to
  fail against mapping an unregistered task to `(None, None)`, which sends setup's quick-tryout to
  the "could not be determined" branch instead of "not installed".
- `smoke_service_status_registered` / `smoke_service_status_not_registered`: with the task
  registered and running, `WindowsPlatform().probe_host().service_active == "active"`; after
  `schtasks /Delete /F`, the pair is exactly `(None, "inactive")` and `stenographer doctor` prints
  the not-installed line. Both run against a real `schtasks.exe`; no `subprocess` is mocked.
- Observable: `stenographer doctor` reports the task's real state and never changes it.

### WIN-LIFE-07
- `test_restart_detail_from_failed_run`: the pure detail formatter turns
  `(returncode=1, stderr="ERROR: The system cannot find the file specified.")` into that stderr
  text, and an empty stderr into `"schtasks exited 1"`. Seen to fail against returning `""` on
  failure, which makes setup print "could not restart stenographer.service: " with no reason.
- `test_restart_settle_deadline_is_bounded`: `0 < SETTLE_SECONDS <= 5.0` and the poll interval
  divides it into at least 10 samples. Seen to fail against an unbounded "wait until stopped" loop,
  which hangs `stenographer setup` when a task is stuck.
- `smoke_restart_task_cycles_process`: with the task running, record the daemon PID, call
  `WindowsPlatform().restart_service()`, assert it returns `(True, "")` and that within 10 s a
  `stenographer` process exists with a different PID and holds the mutex. Then delete the task and
  assert `restart_service()` returns `(False, detail)` with a non-empty detail.
- Observable: setup's restart prompt visibly replaces the daemon; a second dictation uses the newly
  saved configuration.

### WIN-LIFE-08
- `test_windows_stub_directories_honour_xdg_then_windows_conventions` (extended): the existing
  `config_path` / `state_dir` assertions plus `state_dir({}, home)` ==
  `home / "AppData/Local/stenographer"`.
- `test_windows_runtime_dir_honours_xdg_runtime_home`: `runtime_dir({"XDG_RUNTIME_DIR": "/xdg"})` ==
  `Path("/xdg/stenographer")` and `runtime_dir({"LOCALAPPDATA": "C:/Users/alice/AppData/Local"})` ==
  `Path("C:/Users/alice/AppData/Local/stenographer")`. Seen to fail against today's implementation,
  which ignores `XDG_RUNTIME_DIR` outright.
- Both tests are collected on Linux and Windows, so the policy is proven on both CI hosts; this is
  the justification for the item's `Smoke: none` (§W) — the functions are pure and touch no host
  surface.
- Observable: `stenographer doctor` prints a config path under `%APPDATA%` and a log path under
  `%LOCALAPPDATA%` on a default Windows install, and honours `XDG_*` when a developer sets them.

## Risks

- **R-LIFE-1 — `schtasks` output is localized.** Likelihood: medium (any non-English Windows
  install). Impact: low — diagnostics only; registration, `/Run`, and `/End` are unaffected because
  they are keyed on exit codes, not text. Mitigation: `parse_query_list` is total and returns
  `(None, None)` when the English field labels are absent, which doctor already renders as
  "unknown"; the elevation readback uses the locale-independent `/XML` document instead.
  Covered by `test_parse_query_list_localized_output_is_unknown` (WIN-LIFE-06).
- **R-LIFE-2 — Orphaned ASR worker after a hard stop.** Likelihood: high without mitigation — both
  `schtasks /End` and the `CTRL_CLOSE` force-kill terminate only the top-level process, and Windows
  has no control-group equivalent to the systemd unit's kill semantics. Impact: high — a ~1.5 GB
  resident model per orphan, and the next daemon loads a second copy. Mitigation: the kill-on-close
  job object. Covered by `smoke_job_kills_asr_child_on_hard_kill` (WIN-LIFE-04).
- **R-LIFE-3 — `schtasks /Create` flag defaults silently kill the daemon.** Likelihood: high on
  laptops (`DisallowStartIfOnBatteries`) and certain after three days of uptime
  (`ExecutionTimeLimit PT72H`). Impact: high — dictation stops with no error the user can see, and
  §D2's accepted regression means it stays dead until next logon. Mitigation: register from a
  rendered task document that sets all three explicitly. Covered by
  `test_task_xml_disables_battery_and_time_limits` and the `/XML` readback in
  `smoke_logon_task_register_query_delete` (WIN-LIFE-05).
- **R-LIFE-4 — The 5 s close budget is smaller than `Daemon.stop()`'s worst case.** Likelihood:
  medium — it needs an in-flight transcription at close time, where the two 30 s joins dominate.
  Impact: low, because nothing lifetime-critical depends on the graceful path (WIN-LIFE-P7); the
  cost is one lost transcript, the same as a `SIGKILL` on Linux. Mitigation: a 4.0 s bounded wait
  and the three force-kill-safe properties (kernel handle cleanup, per-record log flush, job
  object). This is SCOPE.md §7.8 in its shutdown half. Covered by
  `smoke_console_close_stops_daemon_within_budget` (WIN-LIFE-03).
- **R-LIFE-5 — The windowless daemon receives no console control events at all.** Likelihood: high
  — this is the normal logon-task configuration, and `SetConsoleCtrlHandler` is inert without a
  console (SCOPE.md §7.8, windowless half). Impact: low — logoff and shutdown become force-kills,
  which WIN-LIFE-P7 already requires to be safe. Mitigation: the handler install failure is
  non-fatal and logged at debug; the console path remains fully functional for foreground
  `stenographer run`, which is where Ctrl+C and Ctrl+Break matter. Covered by WIN-LIFE-03's two
  smoke cases (foreground) and `smoke_mutex_free_after_hard_kill` (windowless equivalent).
- **R-LIFE-6 — No auto-restart leaves dictation dead after a transient crash.** Likelihood: low per
  crash, but the exposure window is until next logon. Impact: medium. This is §D2's explicitly
  accepted regression, not a new finding; mitigation is disclosure in the three places listed above
  plus the recorded supervisor deferral. Covered by the surfacing requirement on WIN-LIFE-05 and by
  WIN-DIAG's doctor/setup text items.
- **R-LIFE-7 — `elevated=True` registered by a non-administrator.** Likelihood: low (the flag is
  opt-in and WIN-DIAG states the trade). Impact: medium — the task registers but the action cannot
  obtain the elevated token, so the daemon never starts and the failure appears only in Task
  Scheduler's history. Mitigation: the smoke case reads the registered `RunLevel` back and
  `parse_run_level` is the single source WIN-DIAG reports from, so doctor shows the mode actually
  registered rather than the mode requested. This is the registration half of SCOPE.md §7.1 / §D7;
  UIPI itself is accepted scope and is not re-litigated here. Covered by
  `test_task_xml_run_level_follows_elevated_flag` and `smoke_logon_task_register_query_delete`
  (WIN-LIFE-05).
- **R-LIFE-8 — Mutex name squatting.** Likelihood: very low. Impact: medium — any process in the
  same session that creates `Local\stenographer` first makes every daemon start report contention
  and exit 1, with no diagnostic distinguishing it from a real second instance. Mitigation: none
  technical, and none is warranted: it requires local code execution in the user's own session, and
  the Linux flock has the identical exposure (any process may hold the lock file). Recorded rather
  than mitigated; `smoke_mutex_contention_between_processes` (WIN-LIFE-01) is what proves the exit
  path itself is correct.
- **R-LIFE-9 — A second writer breaks rotating-log rotation.** Likelihood: low while the
  single-instance mutex holds. Impact: medium — on Windows a rotation rename fails outright while
  another process has the file open, so the log stops rotating and grows unbounded. Mitigation: the
  single-owner rule above, and the supervisor deferral's third reconciliation. Covered indirectly by
  WIN-LIFE-01's contention smoke cases, which are what guarantee a single writer.
- **R-LIFE-10 — Antivirus heuristics on the registered task.** Likelihood: medium. Impact:
  distribution-level, not code-level. This is SCOPE.md §7.2; a logon task pointing at an unsigned
  bundle that installs a global keyboard hook adds to the same heuristic match. No mitigation in
  this domain — Authenticode signing is WIN-PKG's per §D7's closing note.
