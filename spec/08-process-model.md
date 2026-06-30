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
   3. Construct the model (`faster_whisper.WhisperModel(...)`) —
      this blocks for 5-30 s on first run.
   4. Construct `Feedback`, `Injector`, `ClipboardManager`,
      `Worker` (with the model), `Recorder`, `HotkeyListener`.
   5. `listener.start()`. Main thread blocks on `session.run()`.

2. **Recording (PTT or toggle-on)**: `listener` calls
   `session.on_recording_start()`. The session:
   - Fires the appropriate start cue (via `Feedback.play`).
   - Calls `recorder.start()`.
   - Returns immediately (the listener thread continues to read
     evdev events).

3. **Recording stop (PTT keyup or toggle-off keydown)**: `listener`
   calls `session.on_recording_stop()`. The session:
   - Calls `recorder.stop()` to get the `numpy.ndarray`.
   - Submits the buffer to `worker.submit(buffer)` and awaits
     the `Future[Result]` with a 5-minute timeout (so a wedged
     worker cannot block the daemon forever).
   - On `Result`, calls `injector.type_text(result.text)` and
     `clipboard.copy(result.text)` in any order.
   - Fires the appropriate stop cue (already done by the listener
     before calling `on_recording_stop`, see `01-hotkey.md`).
   - Returns to `IDLE`.

4. **Signal handling**: SIGINT and SIGTERM set a `threading.Event`.
   The main thread, currently blocked in `session.run()`, wakes
   up, calls `session.stop()`, and returns. The exit code is 0
   if no in-flight work was discarded, 1 otherwise.

5. **Error in any step**: the error is logged and, where
   applicable, `errors.notify_failure(reason)` is called. The
   session returns to `IDLE`; it does NOT exit on a runtime
   error (per `09-error-handling.md`).

### Drain on shutdown

When `SIGTERM` arrives during a recording:

1. The session completes the in-flight utterance: `recorder.stop()`
   -> `worker.submit` -> inject + clipboard.
2. The listener is stopped.
3. The worker's sentinel `None` is enqueued; the worker thread
   exits.
4. The recorder is closed.
5. The feedback player is closed.
6. The session returns from `run()`; `cli.main` exits 0.

If the recording was the result of a toggle-mode press (i.e. the
user has not yet said "toggle off"), the shutdown drains the
transcript and exits cleanly. There is no "abandon the recording"
code path in v1 — the transcript is always produced.

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

Same daemon flow, but in a child process. The user runs
`stenographer dictate`, presses the hotkey, dictates, presses it
again. When the second press ends the recording, the transcript is
injected and copied, then the process exits.

The implementation is: `cmd_dictate(cfg)` constructs a `Session`
with a `one_shot=True` flag, calls `session.run_until_toggle_off()`,
and exits 0. The flag causes the session to exit after the first
toggle-off rather than looping back to `IDLE`.

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
    print(f"mic device:    {'yes' if caps.has_mic else 'NO  (recording disabled)'}")
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

## Out of scope (v1)

- D-Bus IPC (clients cannot query the daemon or trigger dictation
  out of band).
- A control socket (no `stenographerctl`).
- A GUI notification on startup / shutdown.
- Auto-update of the ASR model.

## Open questions

- Should the daemon expose a `--foreground` flag that disables
  `Restart=on-failure`-style daemonization (in case the user
  wants to run it in a terminal for debugging)? v1: the daemon
  is always foreground; systemd handles the daemonization. A
  `--no-daemonize` flag is unnecessary.
- Should `dictate` block on the first `ptt_off` (PTT keyup) AND
  any subsequent `toggle_off`? v1: it accepts exactly one
  utterance, regardless of mode, and exits.
