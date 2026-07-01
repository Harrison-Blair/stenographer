<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 08 — Process model

## Dependencies

- **Reads:** `00-overview.md` (lifecycle, capabilities, all components).
- **Reads:** `07-configuration.md` (`Config` API).
- **Reads:** `09-error-handling.md` (exit codes, error helpers).
- **Reads:** `10-packaging.md` (systemd unit, capability probe).
- **Reads (in order):** all component docs (`01`, `02`, `03`, `04`,
  `05`, `06`). The Session wires them together here.
- **This is the LAST spec to implement.** A subagent assigned this
  doc should not start until every component module has at least a
  skeleton matching its spec.

## Goal

Specify the `Session` orchestrator, the CLI entry point, the daemon
lifecycle (boot, idle, signal handling, shutdown), and the
one-shot CLI subcommands.

## CLI surface

```
stenographer [--config PATH] <subcommand> [args]

Subcommands:
  run                       Start the daemon. Blocks until SIGINT/SIGTERM.
  transcribe FILE           Transcribe a WAV/FLAC/MP3 file, print to stdout.
  dictate                   One-shot dictation: arm hotkey, capture, output, exit.
  model download            Download the configured ASR model and exit.
  update [--check] [--yes] [--no-restart] [--prerelease] [--repo OWNER/NAME]
                            Check GitHub Releases for a newer version, download
                            and install it, and (re)start the daemon. See
                            spec/12-update.md.
  doctor                    Print capability probe + resolved config; exit 0/78.
  --version                 Print version and exit.
  --help                    Print help and exit.
```

### Exit codes

| Code | Meaning                                                              |
|------|----------------------------------------------------------------------|
| `0`  | Success.                                                             |
| `1`  | Generic runtime failure (uncaught exception, lost device, ...).      |
| `2`  | CLI usage error (bad subcommand / bad arguments).                    |
| `78` | Configuration / capability failure (per `09-error-handling.md`).     |

## The `Session` orchestrator

```python
# stenographer.session
import threading

class Session:
    def __init__(
        self,
        *,
        cfg: Config,
        capabilities: Capabilities,
        listener: "HotkeyListener",
        recorder: "Recorder",
        worker: "Worker",
        feedback: "Feedback",
        injector: "Injector",
        clipboard: "ClipboardManager",
    ) -> None: ...

    def run(self) -> None:
        """Block until stop() is called (e.g. by SIGTERM)."""

    def stop(self) -> None:
        """Stop the listener, drain in-flight work, return."""

    # -- internal transitions (called by HotkeyListener) --

    def on_recording_start(self) -> None: ...
    def on_recording_stop(self) -> None: ...
    def on_toggle_off(self) -> None: ...
```

`Session` is **single-threaded** except for the three
already-threaded components (HotkeyListener read-loop, Recorder
audio thread, Worker inference thread). All state transitions go
through `Session` methods, which are protected by a
`threading.Lock` so that a key event arriving concurrently with a
shutdown signal does not race.

### Transition sequence

1. **Boot** (daemon start):
   1. `Config.load`.
   2. `Capabilities.probe`.
   3. Construct the model. In `eager` mode: `Model(cfg.asr)` blocks
      for 5-30 s, then fires a desktop notification (`show_model_ready`).
      In `lazy` mode: `LazyModel(cfg.asr)` returns immediately; the
      actual `WhisperModel` is constructed later on the first hotkey
      press (see below).
   4. Construct `Feedback`, `Injector`, `ClipboardManager`,
      `Worker` (with the model), `Recorder`, `HotkeyListener`.
   5. Construct `Session` and call `session.start()` to launch the
      processor thread.
   6. `listener.start()`. Main thread blocks on `session.run()`.

2. **Recording (PTT or toggle-on)**: `listener` calls
   `session.on_recording_start()`. The session:
   - If `cfg.asr.mode == "lazy"` and the model has not been loaded
     yet: play the `model_loading` cue, show a persistent
     "Loading speech model — listening…" notification, and call
     `worker.ensure_model_loaded(on_loaded=…)`.  The `on_loaded`
     callback plays the `model_ready` cue and shows a transient
     "Model ready" notification when the load finishes.
   - Start the recorder (even in lazy mode — recording and model
     load run in parallel).
   - If the model was already loaded (or in eager mode): show the
     normal "Listening…" notification.
   - Return immediately.

3. **Recording stop (PTT keyup or toggle-off keydown)**: `listener`
   calls `session.on_recording_stop()`. The session:
   - Calls `recorder.stop()` to get the `numpy.ndarray`.
   - Enqueues the buffer into the utterance queue.
   - Returns immediately. The appropriate stop cue was already fired
     by the listener before calling `on_recording_stop` (see
     `01-hotkey.md`).

   The **processor thread** picks up the buffer, submits it to
   `worker.submit(buffer)`, and awaits the `Future[Result]`.  In
   lazy mode, if the model is still loading, the Worker thread
   blocks on `LazyModel.transcribe` until the load completes —
   the first utterance is only transcribed once the model is
   ready.  The load runs in a separate background thread, so it
   does not block the processor thread's `Future` wait.

   On `Result`, the processor calls `injector.type_text(result.text)`
   and `clipboard.copy(result.text)`.

   The session transitions to `IDLE` immediately after enqueuing.
   Transcription and output run concurrently with the next
   recording.

### Idle unload (lazy mode only)

When `cfg.asr.mode == "lazy"` and `cfg.asr.idle_unload_seconds > 0`,
the LazyModel schedules a timer after every successful
`transcribe()` call.  If the timer expires (no transcription for
`asr.idle_unload_seconds` seconds), the timer thread enqueues an
unload request onto the Worker's job queue; the **Worker thread**
then drops the inner `Model`, calls `gc.collect()`, and runs
`malloc_trim(0)` to return the freed weights and inference scratch
to the OS.  A "Speech model unloaded (idle)" desktop notification
is shown.

Disposal runs on the Worker thread (not the timer thread) because
CTranslate2 binds the model to that thread via a `thread_local`
replica slot; dropping the Python reference on a different thread
defers the C++ destructor — and the `munmap` of the model weights —
until the Worker thread next becomes active or exits.  A generation
counter on LazyModel invalidates stale unload requests (a transcribe
that happens between the timer firing and the Worker dequeuing bumps
the generation, and the Worker drops the stale request).

The next hotkey press triggers the same loading sequence as the
first press (cues + loading notification + recording in parallel).
This re-load → transcribe → idle-unload cycle repeats for the
lifetime of the daemon.

4. **Signal handling**: SIGINT and SIGTERM set a `threading.Event`.
   The main thread, currently blocked in `session.run()`, wakes
   up, calls `session.stop()`, and returns. The exit code is 0
   if no in-flight work was discarded, 1 otherwise.

5. **Error in any step**: the error is logged and, where
   applicable, `errors.notify_failure(reason)` is called. The
   session returns to `IDLE`; it does NOT exit on a runtime
   error (per `09-error-handling.md`).

### Drain on shutdown

When `SIGTERM` arrives:

1. The listener is stopped (no more hotkey events).
2. If a recording was in progress, `recorder.stop()` is called and
   the buffer is enqueued into the utterance queue.
3. A sentinel `None` is placed on the utterance queue.
4. The processor thread drains all remaining utterances
   (transcribing + injecting each in order) then exits.
5. The worker is stopped.
6. The feedback player, injector, clipboard, and recorder are closed.
7. The session returns from `run()`; `cli.main` exits 0.

If a toggle-mode recording was active (user hasn't pressed "toggle
off" yet), the shutdown drains the transcript and exits cleanly.
There is no "abandon the recording" code path in v1 — the transcript
is always produced.

## One-shot: `transcribe FILE`

```python
def cmd_transcribe(cfg: Config, path: pathlib.Path) -> int:
    capabilities = Capabilities.probe(cfg)
    if not capabilities.has_asr_model:
        fatal("ASR model not found; run `stenographer model download`")
    import soundfile  # local import; not a top-level dep of the daemon
    samples, sr = soundfile.read(str(path), dtype="float32", always_2d=True)
    if sr != cfg.audio.sample_rate:
        log.warning("transcribe: resampling from %d to %d", sr, cfg.audio.sample_rate)
        # faster-whisper handles resampling internally; pass through as-is
    model = Model(cfg.asr)
    text, _ = model.transcribe(samples, cfg.asr.language, cfg.asr.beam_size)
    if cfg.output.append_trailing_space:
        text = text.rstrip() + " "
    sys.stdout.write(text)
    sys.stdout.write("\n")
    return 0
```

- `transcribe` does NOT inject at the cursor and does NOT touch
  the clipboard. It only prints.
- Exit code: 0 on success, 78 if the model is missing, 2 if
  `soundfile.read` fails (corrupt / wrong-format file).

## One-shot: `dictate`

Same daemon flow, but exits after the first utterance is fully
processed (transcribed + injected + copied). The user runs
`stenographer dictate`, presses the hotkey, dictates, presses it
again. The second press stops recording and the process waits for
transcription to complete before exiting.

The implementation is: `cmd_dictate(cfg)` constructs a `Session`
with a `one_shot=True` flag, calls `session.run()` which blocks on
`_stop_event`. When the processor thread finishes processing the
first utterance, it sets `_stop_event`, unblocking `run()`. The
`finally` block then calls `session.stop()` to drain and tear down.

## `doctor`

```python
def cmd_doctor(cfg: Config) -> int:
    caps = Capabilities.probe(cfg)
    print("stenographer doctor")
    print("===================")
    print(f"config:        {config_path}")
    print(f"asr.model:     {cfg.asr.model}")
    print(f"hotkey:        {cfg.hotkey.binding}")
    print(f"wtype:         {'yes' if caps.has_wtype else 'NO  (cursor injection disabled)'}")
    print(f"wl-copy:       {'yes' if caps.has_wl_copy else 'NO  (clipboard disabled)'}")
    print(f"pw-play/paplay:{'yes' if (caps.has_pw_play or caps.has_paplay) else 'NO  (audio feedback disabled)'}")
    print(f"input group:   {'yes' if caps.has_input_group else 'NO  (hotkey disabled)'}")
    if caps.has_mic:
        mic_name = cfg.audio.input_device or f"default: {Recorder.default_input_device_name()}"
        print(f"mic device:    {mic_name}")
    else:
        print("mic device:    NO  (recording disabled)")
    print(f"asr model:     {'yes' if caps.has_asr_model else 'NO  (transcription disabled)'}")
    fatal_cap = not (caps.has_input_group and caps.has_mic and caps.has_asr_model)
    return 78 if fatal_cap else 0
```

`doctor` never constructs the model or opens the mic; it only
probes.

## systemd user unit (cross-reference)

The unit template is in `packaging/stenographer.service.in` and is
specified in `10-packaging.md`. The Session is **not** aware of
systemd; it just runs `run()` until a signal arrives.

The unit uses `Restart=on-failure` so an uncaught exception that
escapes the Session restarts the daemon after `RestartSec=2`. The
session's `run()` catches all exceptions, logs them, and returns —
the daemon does not normally exit on a runtime error.

## PID file (single-instance)

`Session.__init__` acquires an `fcntl.flock` on
`$XDG_RUNTIME_DIR/stenographer.lock` (default
`/run/user/<uid>/stenographer.lock`). If the lock is already held,
the second `stenographer run` exits 1 with:

```
stenographer: another instance is already running.
```

`one-shot` subcommands do NOT take the lock; they can run
concurrently with the daemon.

## Logging

Configured in `capabilities.py.__init__`:

```python
import logging, os, pathlib
state_dir = pathlib.Path(os.environ.get("XDG_STATE_HOME",
    pathlib.Path.home() / ".local/state")) / "stenographer"
state_dir.mkdir(parents=True, exist_ok=True)
log_file = state_dir / "stenographer.log"

logging.basicConfig(
    level=os.environ.get("STENOGRAPHER_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),                  # stderr
        logging.FileHandler(log_file, mode="a"),  # append
    ],
)
```

## PyInstaller compatibility (binary build)

When the project is packaged as a PyInstaller `--onedir` binary
(`packaging/stenographer.spec`; see `spec/10-packaging.md` for the
distribution layout), `cli.main()` MUST call
`multiprocessing.freeze_support()` as its first line, before any
other work:

```python
def main(argv: Sequence[str] | None = None) -> int:
    import multiprocessing
    multiprocessing.freeze_support()
    _configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    ...
```

This is required because `faster-whisper` / CTranslate2 spawn
multiprocessing resource-tracker children at inference time. Without
`freeze_support()`, each child re-executes the entire `main()`
function (passing the resource-tracker's command line through
`argparse`), producing the error
`argument subcommand: invalid choice: 'from multiprocessing.resource_tracker import main;main(<N>)'`.
The same is true of any Python code that uses
`multiprocessing.Process` from a frozen binary.

## Out of scope (v1)

- D-Bus IPC (clients cannot query the daemon or trigger dictation
  out of band).
- A control socket (no `stenographerctl`).
- Auto-update of the ASR model.

## `update` subcommand (cross-reference)

The `update` subcommand is **not** part of the daemon lifecycle. It
is a one-shot command that:

1. Stops the running daemon (if any) via the systemd user service
   (`spec/10-packaging.md`).
2. Replaces the onedir binary in place with the latest release
   tarball from GitHub.
3. Starts the daemon again (unless `--no-restart`).

The daemon's single-instance lock (`$XDG_RUNTIME_DIR/stenographer.lock`)
is **not** taken by `update`; the daemon is stopped via systemd
instead, and the binary is replaced by `os.replace` on its install
directory. See `spec/12-update.md` for the full flow, exit codes,
and error policy.

`update` does **not** stop one-shot commands (`transcribe`,
`dictate`); they do not take the daemon lock and are not
coordinated with the systemd unit. If a `dictate` is mid-recording
when `update` runs, it completes normally and the process exits;
the new binary takes effect on the next daemon start.

## Open questions

- Should the daemon expose a `--foreground` flag that disables
  `Restart=on-failure`-style daemonization (in case the user
  wants to run it in a terminal for debugging)? v1: the daemon
  is always foreground; systemd handles the daemonization. A
  `--no-daemonize` flag is unnecessary.
- Should `dictate` block on the first `ptt_off` (PTT keyup) AND
  any subsequent `toggle_off`? v1: it accepts exactly one
  utterance, regardless of mode, and exits.
