# Stenographer robust-logging plan (confirmed 2026-08-24)

Spec for the engineer agents. Governing constraints, unchanged: AGENTS.md rule 6
(metrics/lengths only), rule 7 (nothing new crosses IPC), the core-isolation
test (no subprocess/signal/raw fd I/O in core drivers), rule 4 (pure tests, each
seen failing first, no mocked subprocess/devices), Windows stub keeps importing.

## Decisions

| # | Branch | Decision |
|---|---|---|
| 1 | Audience | You now, others later. Rule 6 stays binding as written. |
| 2 | Exceptions | Tiered by audit via `log_failure(log, level, event, exc, *, safe, **fields)`. safe=True: `str(exc)` at level, full exc_info at DEBUG. safe=False: class + `traceback.format_tb` frames only, message never rendered at any level. |
| 3 | Sinks | `stenographer.log` unconditionally DEBUG (5 MiB x 3). stderr/journal threshold tunable. |
| 4 | Correlation | `utt=N` per daemon run, injected by a logging Filter, carried into the ASR child per job. One end-of-utterance INFO summary line. |
| 5 | Gate | Per-capture stats at INFO: peak_rms mean_rms frames_total frames_above threshold verdict. Computed after capture stops, on the pipeline thread, never in the callback. |
| 6 | Banner | Once at INFO: version, Python, platform + chosen overlay/clipboard backends, config path, every effective config key/value in section order, resolved cpu_threads. |
| 7 | Level control | New `feedback.log_level` (22nd key, default "info"); governs stderr/journal; `STENOGRAPHER_LOG_LEVEL` overrides per-process; invalid -> key-scoped ConfigError -> exit 78. Edit AGENTS.md rule 9 in the same commit. |
| 8 | Retrieval | `doctor` prints daemon + helper log path/size and last 10 WARNING/ERROR lines via pure `tail_errors(text, n)`. |
| 9 | Format | Keep `subsystem: event key=value`; pure `fmt_event(subsystem, event, **fields)`; parse-every-template test; omit asctime when `Platform.journal_attached(env)` (Linux: JOURNAL_STREAM; Windows: False). |
| 10 | Helper | Own rotating `overlay-helper.log` in state dir (1 MiB x 2, DEBUG) via `current_platform().state_dir`; transport appends helper stderr to the same file. `_select_backend` forwards the precise UnavailableReason; add `backend_dependency_missing`. Rule 7 untouched; v4-compatible vocabulary extension (note in AGENTS.md). |
| 11 | Threading | Daemon logger -> QueueHandler; one QueueListener thread owns stderr + file handlers. ASR child's listener targets the same real handlers. Timings captured as perf_counter under lock, emitted from pipeline thread. Flush on shutdown. |
| 12 | Tests | Pure tests per domain; UNIT privacy guard (Daemon + fakes + canary, caplog never contains it); daemon-smoke manual step 6 automated; helper smoke flipped. |
| 13 | transcribe parity | `stenographer transcribe <file>`: same downmix as Recorder, same gate + stats line, same formatter call (trailing_space=True unless --raw), same summary with utt=0 source=file, via a shared gate->decode->format core. |
| 14 | Sequencing | A first as one commit on dev; then B, C, D in parallel worktree-isolated code-engineer agents + code-quality-reviewer each; one PR per domain onto dev. |

Assumptions accepted: feedback.log_level in full setup not --quick; enum value
addition is not a protocol bump; helper log 1 MiB x 2, doctor tail N=10;
`_session_generation` is replaced by the utterance id.

## Domain A - logging core (lands first)
Files: utils/logging_setup.py, config.py, platform/base.py, platform/linux/{__init__,dirs}.py,
platform/windows/__init__.py, cli/setup.py (feedback section), AGENTS.md, tests/utils/, tests/test_config.py.
- QueueHandler/QueueListener; sink policy; `resolve_log_level` unchanged; `fmt_event`; `utt` Filter +
  `set_utterance(n)` / contextvar; `log_failure`; `journal_attached`; log-file-open failure logs
  path + errno.
- Config: `feedback.log_level` dataclass field, validator ("debug"|"info"|"warning"|"error",
  case-insensitive), default TOML template comment, setup feedback section.
- AGENTS.md: rule 9 -> 22 keys; rule 6 gains: file always DEBUG, the safe/unsafe tiering, the
  helper-local file; "already authorized" list; architecture-map rows (logging_setup, doctor,
  transcribe); update_check row untouched.
- Tests: fmt_event round-trip; template parser over src/; utt filter; log_failure(safe=False) canary
  absent; log_level validation -> exit 78; journal format choice; listener flush ordering.

## Domain B - daemon instrumentation
Files: daemon.py, audio.py, transcribe/{worker,model,format}.py, delivery/deliver.py,
delivery/feedback.py, platform/linux/{clipboard,hotkey,lock}.py, overlay/supervisor.py (daemon half),
cli/commands/transcribe.py, tests/test_daemon.py, tests/test_audio.py, tests/test_daemon_smoke.py.
- Banner (decision 6). Utterance id allocation replacing `_session_generation`
  (max-duration staleness guard keeps working off the same counter).
- Gate stats: pure companion to `speech_gate_passes` returning (verdict, stats) from one computation.
- Summary line fields: utt mode outcome activate_ms capture_s in_frames out_frames overflow capped
  gate peak_rms frames_above cold load_ms lock_wait_ms decode_ms vad_frames segments words chars_raw
  chars_out copy_ms release_wait_ms release_timeout total_ms. Absent fields on early exits.
  Existing under-lock `recorder: activated/captured` lines fold into it.
- Tiering: safe=False at worker.py:197, daemon.py:307/424, clipboard.py:163 (never .output/.args).
  PathologicalOutputError message kept. safe=True everywhere else, including promoting
  clipboard.py:128/168 to WARNING with argv + str(exc); supervisor.py:481/512 include ProtocolError
  text; feedback.py:115 logs which cue file failed WAV validation and why; hotkey.py:89/106/111/116/250
  log device path + str(exc); lock.py:54/62 carry errno; worker.py:180.
- Lifecycle gaps: DEBUG on every hotkey edge with reason when ignored; child logs
  `worker: child started model= compute_type= cpu_threads=`; release-wait elapsed on success;
  format in/out lengths.
- transcribe parity (decision 13).
- Tests: gate-stats math; summary assembly (pure); privacy guard unit test; daemon-smoke step 6
  automated (canary absent, summary present in stenographer.log).

## Domain C - helper diagnostics
Files: overlay/supervisor.py (helper half: run_overlay_helper/_select_backend), platform/linux/helper.py,
platform/linux/overlay.py, platform/linux/overlay_backends/{base,wayland,x11}.py, status.py
(UnavailableReason value), tests/overlay/test_overlay_helper_smoke.py, tests/platform/linux/.
- Helper-local logger + rotating file; stderr redirected by the transport into the same file.
- Reason propagation; `backend_dependency_missing`; probes distinguish ImportError.
- log_failure(safe=True) at wayland.py:250/301/312/323/340/350/477, the four `from None` construct
  sites (keep `from None` on the wire, log cause locally), x11.py:625, supervisor.py:550/579; log the
  missing Wayland globals tuple / X extension name.
- Smoke: helper creates overlay-helper.log*, not stenographer.log*.

## Domain D - doctor
Files: cli/doctor.py, platform/base.py (HostGuidance if any new noun), tests/cli/test_doctor.py.
- Log path + size for both files; `tail_errors(text, n=10)` pure; rendered under a "Logs" section.

## Acceptance before dev -> main
Integration suite green; real dictation hold + toggle; log inspection (metrics, no transcript);
kill helper -> dictation unaffected; `feedback.log_level = "debug"` changes journal output while the
file is unchanged; helper log shows backend startup on a real compositor.
