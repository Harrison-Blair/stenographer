# Windows Feedback — Cue Player and Toast Notifier

Scope: the two host surfaces `Feedback` and the daemon's error path consume — `CuePlayer` and
`Notifier` — implemented for Windows and wired into `WindowsPlatform`. Blast area is contained
inside `platform/windows/`: no core module changes, no Protocol changes (§P3), no config or
sound-pack policy changes. Mute, volume, and pack resolution stay in `delivery/feedback.py`
untouched; this domain receives an already-resolved cue path and a linear gain. Read
[`README.md`](README.md) first — §D3 and §D4 are the settled mechanisms and are not re-argued.

## Designed source tree

| Path | Marker | Role |
|---|---|---|
| `src/stenographer/platform/windows/cues.py` | NEW | `prepare_cue` / `resample_cue_linear` (pure), `read_cue`, `detect_player`, `WindowsCuePlayer` — in-process playback per §D4. |
| `src/stenographer/platform/windows/notify.py` | NEW | `build_notify_command` / `notify_env` (pure), `TOAST_SCRIPT`, `PowerShellToastNotifier` — toast subprocess per §D3. |
| `src/stenographer/platform/windows/__init__.py` | EDIT | `cue_player()` and `notifier()` stop returning `None` / `NullNotifier`; lazy sibling imports only. |
| `tests/platform/windows/` | NEW | `conftest.py` collect gate plus this domain's pure and smoke suites; not collected off Windows. |

`tests/platform/windows/conftest.py` is shared infrastructure — one line mirroring
`tests/platform/linux/conftest.py` (`collect_ignore_glob = [] if sys.platform == "win32" else
["*.py"]`). WIN-FEED-01 creates it if no other domain has landed it yet; creating it is idempotent
and must not be duplicated. No CI edit is needed: `unit-windows` already runs
`pytest -m "not integration"` over the whole tree on `windows-latest`, so a new
`tests/platform/windows/` suite is collected there for free and skipped everywhere else.

## Architecture principles

- **WIN-FEED-P1 — `play()` does no work on the caller's thread.** `Daemon._play_cue` calls
  `Feedback.play` on the hotkey-edge path. `WindowsCuePlayer.play` writes one mailbox slot, signals
  an event, and returns; the file read, gain scaling, and PortAudio stream open all happen on the
  player's own thread. Inline `sounddevice.play()` in `play()` still works and still makes sound —
  it just charges a 5–30 ms WASAPI device open to the keypress that starts recording.
- **WIN-FEED-P2 — Latest cue wins; cues never queue.** The mailbox holds exactly one pending cue.
  A cue that is superseded before the worker picks it up is dropped, never played late; a cue that
  is superseded while playing is cut off by `sounddevice.stop()` before the new one starts. This is
  the visible divergence from Linux, where each spawned player is an independent process and two
  cues overlap. It is deliberate: a cue signals the *current* lifecycle state, so the newest is the
  only correct one, and §D4's singleton constraint makes overlap impossible anyway. The only
  reachable overlap is a hold or toggle tap shorter than the `record_start` cue (0.072 s bundled),
  which truncates `record_start`; `record_stop → delivered` and `record_stop → error` are always
  separated by transcription time.
- **WIN-FEED-P3 — The player touches only its own playback stream.** It never assigns
  `sounddevice.default.*` (process-global; `Recorder` reads it), never calls
  `query_devices(kind="input")`, never uses `sounddevice.rec`/`playrec`. Bare `sounddevice.stop()`
  is safe *only* because `Recorder` owns an explicit `InputStream` and is therefore never the
  library's `_last_callback` stream. If capture ever moves to `sounddevice.rec`, this rule breaks
  first and silently: a cue would abort live capture.
- **WIN-FEED-P4 — Cue failure never reaches the daemon and never reaches capture.** Every exception
  on the worker thread — `soundfile` refusing the file, `PortAudioError` on device open, an invalid
  sample rate after the one fallback — is caught there and logged at `log.debug` with the exception
  *type* only (no path, no config value: rule 6, §P9). The daemon thread observes nothing;
  `Daemon._play_cue`'s own `except Exception` stays a second belt, never the first. `preview()` is
  the single path that raises.
- **WIN-FEED-P5 — Nothing outlives the interpreter and nothing needs teardown.** The `CuePlayer`
  Protocol has no `close()` and `Feedback.close()` is a no-op, so the worker is a `daemon=True`
  thread started lazily on the first `play()` — never in `__init__`, so `doctor`, `sounds --list`,
  and `Daemon.build` create no thread and load no PortAudio. Adding a `close()` would be §P3
  Protocol work and is out of this domain.
- **WIN-FEED-P6 — `preview()` is bounded and honest.** It plays on the calling thread, waits for
  actual completion, and returns only after the stream goes inactive — bounded by
  `PREVIEW_TIMEOUT_SECONDS = 10.0` (the same constant and value as `platform/linux/cues.py`), after
  which it raises `TimeoutError`. A stalled or failed player must surface as an exception to
  `cli/sounds.py::_preview`, exactly as `CalledProcessError`/`TimeoutExpired` do on Linux; a
  `preview` that returns before the sound finishes breaks `preview_sound_pack`'s ordering.
- **WIN-FEED-P7 — The toast message never enters the command line.** `build_notify_command()` takes
  no message argument — the divergence from Linux's `build_notify_command(message)` is forced, not
  cosmetic: a `-Command` string is PowerShell source, so an interpolated message is arbitrary code.
  The text crosses only through the child environment (`STENOGRAPHER_TOAST_MESSAGE`), truncated to
  `MAX_MESSAGE_CHARS = 200` and stripped of control characters, and `TOAST_SCRIPT` reads
  `$env:STENOGRAPHER_TOAST_MESSAGE`. Per §P9 the message is a short caller-supplied error string;
  the truncation is the structural guarantee that nothing longer can ever reach a toast.
- **WIN-FEED-P8 — Selection stays in core.** The player receives a resolved `Path` and a linear
  gain. It never reads `feedback.sound_pack`, never looks in `<config>/sounds/`, never ranks packs,
  and never becomes a second WAV gate — `soundfile` accepts formats beyond the validated PCM subset
  of hard rule 8, and a file that core accepted but `soundfile` refuses is a P4 debug log, not a
  validation decision.
- **WIN-FEED-P9 — Windows-only names are literals, and audio imports are lazy.** `_CREATE_NO_WINDOW
  = 0x08000000`, not `subprocess.CREATE_NO_WINDOW` (absent off Windows, and the Linux bundle's
  `collect_submodules` walks this package). `import sounddevice` / `import soundfile` live inside
  method bodies, mirroring `audio.py`; module level carries `numpy` only, so the pure functions and
  their tests import with no PortAudio present (§P1).

## Functional criteria

### WIN-FEED-01 — Implement the in-process cue player
Phase: 1   Depends on: none
Files: `src/stenographer/platform/windows/cues.py` (NEW), `tests/platform/windows/conftest.py`
(NEW, shared), `tests/platform/windows/test_cues.py` (NEW),
`tests/platform/windows/test_cues_smoke.py` (NEW)
Pure tests: `tests/platform/windows/test_cues.py::test_prepare_cue_scales_linear_gain`,
`::test_prepare_cue_zero_volume_is_silent`, `::test_prepare_cue_clips_above_unity`,
`::test_prepare_cue_preserves_channel_layout`, `::test_prepare_cue_rejects_integer_samples`,
`::test_prepare_cue_returns_contiguous_float32`, `::test_prepare_cue_does_not_mutate_input`,
`::test_resample_cue_linear_identity_when_rates_match`,
`::test_resample_cue_linear_output_length_matches_rate_ratio`,
`::test_resample_cue_linear_preserves_constant_signal`,
`::test_resample_cue_linear_preserves_stereo_columns`,
`::test_resample_cue_linear_empty_input`
Smoke: `cue_playback_audible`, `cue_playback_during_capture`, `cue_preview_is_bounded`,
`cue_playback_without_output_device`
Done when: `WindowsCuePlayer().play(path, 0.6)` returns without blocking and the cue is audible at
the requested gain, and `preview(path, 0.6)` returns only after the sound has finished or raises
within `PREVIEW_TIMEOUT_SECONDS`.

Module surface, exactly:

- `PREVIEW_TIMEOUT_SECONDS = 10.0`.
- `prepare_cue(samples: np.ndarray, volume: float) -> np.ndarray` — **PURE**, the §P5 replacement
  for the deleted `build_play_command` named in §D4. Rejects integer and object dtypes with
  `TypeError` (an int16 buffer handed to a float32 stream plays at ±32767); accepts float32/float64
  and returns float32. Clamps `volume` to `>= 0.0`, multiplies, then hard-clips to `[-1.0, 1.0]`
  (`config.py` bounds `feedback.volume` to 0.0–1.0, but the function does not rely on it). Volume
  `0.0` returns silence of the same shape, never a log/divide guard. Preserves layout: 1-D mono
  stays 1-D, `(frames, channels)` stays 2-D, no mixdown and no up-mix. Returns a new
  C-contiguous array; never writes into the input.
- `resample_cue_linear(samples: np.ndarray, rate_in: int, rate_out: int) -> np.ndarray` — **PURE**,
  used only on the rate-fallback path below. Returns the input unchanged when the rates match;
  otherwise `np.interp` over `np.linspace(0, n - 1, round(n * rate_out / rate_in))`, per column for
  2-D, float32 and contiguous out. Empty input returns empty, no exception.
- `read_cue(path: pathlib.Path) -> tuple[np.ndarray, int]` — lazy `import soundfile`;
  `soundfile.read(str(path), dtype="float32", always_2d=False)`. The `dtype` is load-bearing:
  soundfile defaults to float64.
- `detect_player() -> str | None` — the host-probe half consumed by `WIN-DIAG: host probe`,
  mirroring `platform/linux/cues.detect_player`. Returns the PortAudio host-API name of the default
  output device (e.g. `"Windows WASAPI"`, `"MME"`), or `None` when `query_devices(kind="output")`
  raises or reports no output channels. Called only from the doctor path, never from
  `cue_player()`.
- `class WindowsCuePlayer` — `__init__` does no device I/O and starts no thread (P5).
  `play(path, volume)` stores `(path, volume)` in the one-slot mailbox under a `threading.Lock`,
  sets the wake event, starts the daemon worker if it is not yet alive, returns (P1, P2).
  The worker loops: wait, take-and-clear the slot, `read_cue`, `prepare_cue`,
  `sounddevice.stop()`, `sounddevice.play(data, rate)`. On `PortAudioError` whose
  `args[1] == -9997` (invalid sample rate — the `legacy` pack is 44100 while every other bundled
  pack is 48000) it retries exactly once with `resample_cue_linear(data, rate,
  int(query_devices(kind="output")["default_samplerate"]))`, mirroring `Recorder`'s
  one-recovery precedent; any second failure is a P4 debug log.
  `preview(path, volume)` runs the same read/prepare/play inline on the calling thread, then polls
  `sounddevice.get_stream().active` every 10 ms against a `PREVIEW_TIMEOUT_SECONDS` deadline,
  raising `TimeoutError` on expiry, and finally calls `sounddevice.wait(ignore_errors=False)` so a
  callback-level failure is raised rather than swallowed (P6). `play` and `preview` never run
  concurrently in one process: `run` never previews and `sounds` never starts a daemon.

### WIN-FEED-02 — Implement the PowerShell toast notifier
Phase: 1   Depends on: `WIN-LIFE: child env`
Files: `src/stenographer/platform/windows/notify.py` (NEW),
`tests/platform/windows/test_notify.py` (NEW), `tests/platform/windows/test_notify_smoke.py` (NEW)
Pure tests: `tests/platform/windows/test_notify.py::test_build_notify_command_exact_argv`,
`::test_build_notify_command_carries_no_message`,
`::test_toast_script_reads_message_from_environment`,
`::test_notify_env_passes_message_verbatim`,
`::test_notify_env_preserves_base_environment`,
`::test_notify_env_truncates_long_message`,
`::test_notify_env_strips_control_characters`
Smoke: `toast_visible`, `toast_never_blocks`, `toast_absent_powershell_is_noop`
Done when: `PowerShellToastNotifier().error("copy failed")` returns immediately and one toast
reading `copy failed` appears, and no message content is present anywhere in the child's argv.

Module surface, exactly:

- `MESSAGE_ENV = "STENOGRAPHER_TOAST_MESSAGE"`, `MAX_MESSAGE_CHARS = 200`,
  `_CREATE_NO_WINDOW = 0x08000000`, `_AUMID =
  "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"` (the
  shell-registered PowerShell AUMID §D3 accepts borrowing).
- `TOAST_SCRIPT` — a module constant, single-line-joined PowerShell:
  loads `[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,
  ContentType=WindowsRuntime]`, takes `GetTemplateContent(ToastTemplateType::ToastText02)`, sets
  text node 0 to `Stenographer` and text node 1 to `$env:STENOGRAPHER_TOAST_MESSAGE`, then
  `CreateToastNotifier(_AUMID).Show([Windows.UI.Notifications.ToastNotification]::new($t))`. It
  contains no format placeholder and no concatenation with caller data (P7).
- `build_notify_command() -> list[str]` — **PURE**, no arguments:
  `["powershell", "-NoProfile", "-NonInteractive", "-NoLogo", "-WindowStyle", "Hidden",
  "-Command", TOAST_SCRIPT]`. `-NoProfile` keeps user profile scripts out of the error path;
  `-NonInteractive` guarantees a prompt can never hang the child.
- `notify_env(base: Mapping[str, str], message: str) -> dict[str, str]` — **PURE**: a copy of
  *base* with `MESSAGE_ENV` set to *message* with control characters (including CR/LF/NUL) removed
  and the result truncated to `MAX_MESSAGE_CHARS`.
- `class PowerShellToastNotifier` — `probe()` staticmethod returning
  `shutil.which("powershell") is not None` (shared with `WIN-DIAG: host probe`, exactly as
  `NotifySendNotifier.probe` is on Linux); `__init__` caches it; `error(message)` returns
  immediately when unavailable, otherwise `subprocess.Popen(build_notify_command(),
  stdout=DEVNULL, stderr=DEVNULL, stdin=DEVNULL, creationflags=_CREATE_NO_WINDOW,
  env=notify_env(child_env(), message))` with `OSError` swallowed to `log.debug`. `child_env()`
  comes from `platform/windows/process.py` (`WIN-LIFE: child env`), mirroring the Linux import.

### WIN-FEED-03 — Wire the cue player and notifier into `WindowsPlatform`
Phase: 1   Depends on: WIN-FEED-01, WIN-FEED-02
Files: `src/stenographer/platform/windows/__init__.py` (EDIT),
`tests/platform/windows/test_provider_wiring.py` (NEW)
Pure tests:
`tests/platform/windows/test_provider_wiring.py::test_cue_player_returns_windows_cue_player`,
`::test_notifier_returns_toast_notifier`,
`::test_provider_import_does_not_load_audio_modules`
Smoke: `sounds_preview_end_to_end`, `daemon_error_toast`
Done when: `stenographer sounds --preview minimal-ui` plays four cues and exits 0 on Windows, and
neither `NullNotifier` nor a `None` cue player is reachable from `WindowsPlatform`.

`cue_player()` lazy-imports `WindowsCuePlayer` and returns it **unconditionally** — construction
does no device I/O (P5), so unlike Linux there is no `detect_player()` call on the daemon-start
path and no PortAudio output enumeration before the first cue. A machine with no output device
therefore gets a player whose cues degrade to debug logs (P4) and whose `preview` reports the
failure through `cli/sounds.py`. `notifier()` lazy-imports and returns `PowerShellToastNotifier()`.
Both methods keep their imports inside the body (§P1); the module docstring loses the "cues" and
"notifier" entries from its unavailable list.

## Acceptance criteria

Every pure test below must be **seen to fail** against the named broken behavior before the item is
complete (§P6). No criterion here is satisfiable by mocking `sounddevice`, `soundfile`, or
`subprocess`; the mechanisms that cannot be unit-tested are covered by named smoke cases, which run
on the real Windows merge machine under `STENOGRAPHER_INTEGRATION=1`, carry
`pytest.mark.integration`, and self-skip at module level exactly as
`tests/delivery/test_feedback_smoke.py` does.

### WIN-FEED-01

Pure — `prepare_cue`:

| Test | Catches |
|---|---|
| `test_prepare_cue_scales_linear_gain` | Gain ignored or interpreted as decibels: a 1.0-amplitude ramp at `volume=0.5` must come back at exactly 0.5. Breaks the `feedback.volume` config contract silently — the exact failure §D4 rejected `winsound` to avoid. |
| `test_prepare_cue_zero_volume_is_silent` | `volume=0.0` raising, or a `max(volume, eps)` guard copied from the Linux decibel conversion producing audible output where silence was asked for. |
| `test_prepare_cue_clips_above_unity` | Unclipped output: `volume=4.0` on a 0.5-amplitude buffer must peak at exactly 1.0, not 2.0. Out-of-range float32 samples distort or wrap in the audio engine, loudly. |
| `test_prepare_cue_preserves_channel_layout` | A `reshape(-1)` on a `(n, 2)` buffer — the cue then plays interleaved as double-rate mono (chipmunk pitch) — or an unrequested mixdown/up-mix. Mono `(n,)` must stay `(n,)`. |
| `test_prepare_cue_rejects_integer_samples` | An int16 array reaching a float32 stream at ±32767: full-scale noise at the user's ears. Must raise `TypeError`. |
| `test_prepare_cue_returns_contiguous_float32` | Passing a non-contiguous stereo column slice through: PortAudio raises at play time, so the failure appears only on stereo custom packs, only on Windows. Assert `dtype == float32` and `flags["C_CONTIGUOUS"]`. |
| `test_prepare_cue_does_not_mutate_input` | In-place `samples *= volume`: with any future buffer reuse the cue decays by `volume**n` on each replay. Assert the input array is bit-identical after the call. |

Pure — `resample_cue_linear`:

| Test | Catches |
|---|---|
| `test_resample_cue_linear_identity_when_rates_match` | Interpolating unconditionally, which detunes and lengthens every cue on the common path by a rounding sample. Must return the input array unchanged. |
| `test_resample_cue_linear_output_length_matches_rate_ratio` | An inverted ratio: 44100→48000 of 11025 samples must yield 12000, not 10126. Inverted, the `legacy` pack plays at the wrong pitch and speed — audible, but silently wrong in CI. |
| `test_resample_cue_linear_preserves_constant_signal` | Index arithmetic that walks off the end: a constant 0.5 buffer must resample to constant 0.5 with no zero tail and no ramp at either endpoint. |
| `test_resample_cue_linear_preserves_stereo_columns` | Flattening interleaved data before interpolation, which mixes the channels into one another. |
| `test_resample_cue_linear_empty_input` | `ZeroDivisionError` / `np.interp` on an empty `xp`, reached whenever a zero-frame file slips past core validation. Must return an empty float32 array. |

Smoke — `tests/platform/windows/test_cues_smoke.py`:

- `cue_playback_audible` (`::test_play_every_bundled_pack_audibly`) — for each of the four bundled
  packs, `preview_sound_pack(pack, WindowsCuePlayer(), 0.6)` from core, then `Feedback.play` for all
  four cues with 1 s sleeps. Operator confirms sixteen distinct sounds at moderate volume. The
  `legacy` pack is the rate-fallback case (44100 against a 48000 mix): it must play at the same
  pitch and duration as on Linux, not slowed, sped up, or missing.
- `cue_playback_during_capture` (`::test_cues_during_live_capture`) — construct a real `Recorder`,
  `prepare()`, `start()`, play `record_start` and `record_stop` while capturing, speak, `stop()`.
  Assert the returned array is non-empty, passes `speech_gate_passes`, and the recorder is back in
  `RecorderState.PREPARED`. This is the observable proof that the output stream cannot disturb the
  retained input stream (P3) and that an output-device failure is contained (P4); reauthor §4
  guarantees capture is already open before the first cue ever plays, so this ordering is the only
  one that occurs.
- `cue_preview_is_bounded` (`::test_preview_waits_for_completion_and_returns`) — time `preview()` on
  `error.wav` (0.246 s): elapsed must be `>= 0.2` (a fire-and-forget preview fails here, and would
  make `preview_sound_pack` play four cues on top of each other) and `< PREVIEW_TIMEOUT_SECONDS`.
- `cue_playback_without_output_device` — manual: disable every playback device in Windows sound
  settings, then (a) `stenographer sounds --preview minimal-ui` exits 1 printing
  `sound-pack preview failed: ...` and (b) `stenographer run` still completes a full dictation with
  text pasted, with only `cue_failed`/debug lines in the log. Covers P4 and the §D4 new-failure-
  surface concern; not automatable because it requires changing host device state.

### WIN-FEED-02

Pure:

| Test | Catches |
|---|---|
| `test_build_notify_command_exact_argv` | A dropped `-NoProfile` (user profile scripts execute on the daemon's error path, adding seconds and arbitrary behavior) or `-NonInteractive` (a credential prompt leaves an orphan PowerShell forever). Assert the full list identically. |
| `test_build_notify_command_carries_no_message` | Reintroducing message interpolation: assert a distinctive message string appears in no element of the argv for any call. |
| `test_toast_script_reads_message_from_environment` | A `TOAST_SCRIPT` rewritten to `%`/f-string formatting: assert it contains `$env:STENOGRAPHER_TOAST_MESSAGE` and `_AUMID`, and contains no `{`/`%s` placeholder. |
| `test_notify_env_passes_message_verbatim` | Quoting or escaping the message on the way in — the toast would show backslashes. `notify_env({}, msg)[MESSAGE_ENV] == msg` for a message containing `'`, `"`, backtick, `;`, `$(...)`. This is also the injection test: none of it is ever parsed as PowerShell source. |
| `test_notify_env_preserves_base_environment` | Replacing the environment instead of copying it, which strips `SystemRoot`/`PATH` and makes every toast fail to launch. |
| `test_notify_env_truncates_long_message` | An unbounded string reaching the toast: a 5000-char message must come back at exactly `MAX_MESSAGE_CHARS`. The structural §P9 guarantee. |
| `test_notify_env_strips_control_characters` | Embedded `\r\n\x00` surviving into the child environment. |

Smoke — `tests/platform/windows/test_notify_smoke.py`:

- `toast_visible` (`::test_error_toast_appears`) — `PowerShellToastNotifier().error("copy failed")`;
  operator confirms one toast titled *Stenographer* reading `copy failed` (branded Windows
  PowerShell per §D3) within ~2 s and that it lands in the Action Center. Then
  `error("a'b\"c;$(Write-Host pwned)`d")`: the literal text must appear and nothing must execute.
- `toast_never_blocks` (`::test_error_returns_immediately`) — `perf_counter` around `error()` must
  be under 50 ms. Catches a `subprocess.run`, which would park the daemon's error path for ~1 s.
- `toast_absent_powershell_is_noop` — manual: run with `powershell.exe` removed from `PATH`;
  `error()` returns, raises nothing, and the daemon completes a dictation. Not automatable without
  mutating `PATH` for a subprocess, which is the real-machine procedure, not an assertion.

### WIN-FEED-03

Pure:

| Test | Catches |
|---|---|
| `test_cue_player_returns_windows_cue_player` | The stub's `return None` surviving the merge: cues silently never play on Windows and nothing fails. Assert `isinstance(WindowsPlatform().cue_player(), WindowsCuePlayer)`. |
| `test_notifier_returns_toast_notifier` | The stub's `NullNotifier` surviving: every error notification is silently discarded. |
| `test_provider_import_does_not_load_audio_modules` | A module-level `import sounddevice`/`soundfile` in `cues.py`, which puts PortAudio initialization on `stenographer --help` and breaks §P1. Import `stenographer.platform.windows` in a fresh interpreter (`subprocess` on `sys.executable`, the pattern `tests/platform/test_core_isolation.py` already uses) with `sounddevice` and `soundfile` blocked in `sys.modules`, and assert it imports and `WindowsPlatform().cue_player()` still constructs. |

Smoke:

- `sounds_preview_end_to_end` — `stenographer sounds --preview legacy` then `--preview minimal-ui`
  on Windows: each plays four cues in order with the 0.35 s core pause and exits 0. Then
  `stenographer sounds` interactively: `P1` previews and re-prompts, a number selects and writes
  config. Proves the wiring reaches the core `preview_sound_pack` path and that §D4's blocking
  `preview` keeps the menu's ordering.
- `daemon_error_toast` — with `stenographer run` live, force a delivery failure (focus a window that
  rejects the paste chord, or run with the clipboard held by another process): the `error` cue plays
  and one toast appears; the log line carries an `error_type=` and no transcript text (§P9, rule 6).

## Risks

1. **No output device / output open fails** (SCOPE §7 does not list this; it is new with §D4).
   Likelihood medium — RDP sessions, headless boxes, and disabled endpoints are common. Impact low:
   cues are lost, dictation is unaffected. Mitigation: WIN-FEED-P4 confines the failure to the
   worker thread; `cue_player()` never probes, so a missing device cannot fail daemon start.
   Covered by `cue_playback_without_output_device`.
2. **Sample-rate rejection on WASAPI shared mode.** Likelihood medium and *certain* for the `legacy`
   pack on a 48000 mix (44100 source; the other three bundled packs are 48000). Impact low per cue,
   but a whole pack going silent looks like a broken install. Mitigation: the single
   `-9997` retry through `resample_cue_linear`, mirroring `Recorder`'s one-recovery precedent.
   Covered by `test_resample_cue_linear_output_length_matches_rate_ratio` and the `legacy` leg of
   `cue_playback_audible`.
3. **Output stream disturbing the retained capture stream.** Likelihood low — PortAudio full-duplex
   with independent streams is supported, and capture is always opened first (reauthor §4). Impact
   high: lost dictation. Mitigation: WIN-FEED-P3 forbids `sounddevice.default` mutation and
   `sd.rec`, which is the only way `sounddevice.stop()` could reach the capture stream. Covered by
   `cue_playback_during_capture`.
4. **Truncated cue on a short hold** (WIN-FEED-P2, the §D4 singleton). Likelihood high for taps
   under 0.072 s, impact cosmetic — the newest lifecycle state is still the one heard. Mitigation:
   documented in the module docstring as a stated Windows/Linux divergence; no code mitigation is
   wanted. Covered by `cue_playback_audible` (the operator hears the truncation and confirms it is
   the newer cue that survives).
5. **Toast never appears despite a clean `Popen`** — notifications disabled, Focus Assist, or a
   locked-down AUMID. Likelihood medium, impact low: the errors-only visual channel is lost while
   the error *cue* and the log still fire, and §D3 already accepts the borrowed-AUMID branding.
   Mitigation: `probe()` covers the absent-PowerShell half only; the rest is a documented limitation
   for `WIN-DIAG: host probe` to report. Covered by `toast_visible`.
6. **PowerShell launch latency (~1 s) on the error path.** Likelihood certain, impact none — §D3
   accepts it, and WIN-FEED-P7's non-blocking `Popen` keeps it off the daemon thread. Covered by
   `toast_never_blocks`.
7. **PowerShell absent or renamed** (`pwsh`-only images, constrained-language mode). Likelihood low
   on stock Windows 10/11. Impact low: notifications degrade to no-ops exactly as an absent
   `notify-send` does. Covered by `toast_absent_powershell_is_noop`.
8. **`detect_player()` initializing PortAudio inside `doctor`.** Likelihood certain, impact
   negligible — `doctor` already enumerates the input device. Mitigation: it is called only from
   `WIN-DIAG: host probe`, never from `cue_player()` (WIN-FEED-P5). No dedicated criterion; the
   `doctor` timing is observable in `sounds_preview_end_to_end`'s session.
