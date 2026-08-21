# Stenographer Reauthor — Reference Document

Status: **settled**. The decisions in §2 were made with the repo owner on 2026-08-12,
and the spectrum monitor details in §2.15/§4.17 were revised on 2026-08-19 and
2026-08-20 — do not relitigate them during implementation. Everything else in this
document is reference material extracted from the current codebase so it survives
that code's deletion.

---

## 1. Mission & motivation

### Mission

> **Press a hotkey, speak, and the text appears at your cursor.**

That sentence is the razor. Anything that does not directly serve
hotkey → record → transcribe → deliver is presumed cut and must argue its way back
in individually (see the disposition table in §3 and the add-later ledger in §7).

### Why a reauthor

The current codebase is **8,901 lines of source across 41 modules plus 8,578 lines
of tests** — nearly 1:1 — for a one-sentence tool. It carries 13 CLI subcommands,
10 config sections (~50 keys), 11 sound cues, 3 trigger modes, 2 injection methods,
a GTK helper process, a job-queueing inference child process, a self-updater, and a
WER benchmark harness.

The proximate trigger: the GUI-reauthor plan (`workflows/gui-reauthor-plan.md`,
now **superseded by this document**) attempted to replace the GTK HUD stack and
failed on contact — the attempt exposed immense technical debt and code that could
not be understood or safely modified. You cannot trim a codebase you don't
understand; every trim inherits the old architecture's assumptions. Hence:
**clean-room greenfield rewrite**, old code used only as a behavioral reference and
then deleted.

Secondary trigger, inherited from the GUI plan's findings: the current tool cannot
work on stock GNOME at all — Mutter implements neither `wlr-layer-shell` (no
overlay, ever) nor `zwp_virtual_keyboard_manager_v1` (no `wtype`, ever). The old
design was built on compositor-specific protocols; the new one must not be.

---

## 2. Decision record (settled — do not relitigate)

1. **Mission** is the one-sentence statement above; it is the cut criterion for
   every feature question.
2. **Python stays**, same STT stack: faster-whisper / CTranslate2, same `Systran/*`
   models. The size problem is feature surface, not language; changing both at
   once is two risky projects in one.
3. **Clean-room greenfield, same repo.** New source tree written from scratch
   against this document. Old code is a behavioral reference only and is deleted
   at the end (after real-dictation validation). Git history and memory notes are
   part of the reference material — no fresh repo.
4. **Personal-first, distribute-later.** Eventual distribution is a goal. The
   owner restored a local PyInstaller onedir build and single-machine per-user
   installer in 2026-08 as development-machine conveniences. They are not a
   release channel: self-update, version-stripping workflows, multi-distro or
   curl-pipe-bash installers, config migrations, and completions remain cut.
5. **Target: any Wayland session, GNOME included.** Not two specific machines —
   portable across Wayland compositors (wlroots-family and GNOME/Mutter alike).
   Dictation and delivery never depend on a display-overlay protocol. A small,
   best-effort lifecycle surface may prefer layer-shell, fall back to XWayland,
   and disable itself when neither works; failure of that optional surface must
   never affect recording, transcription, or delivery.
6. **Injection mechanism: `uinput`** (kernel virtual input device via
   python-evdev's `UInput`). Display-server-independent — works on GNOME,
   Hyprland, X11, everywhere. One injection path, zero fallback axes. The old
   plan's "no ydotool/uinput" decision is explicitly overturned: the permission
   story (`input` group / udev rule) is the same one the evdev hotkey listener
   already requires.
7. **Delivery: single paste-chord path.** Copy the transcript to **both**
   selections (clipboard + primary), then send **Shift+Insert** via
   uinput — the most broadly honored paste chord across toolkits. Per-character
   typing and `max_chars` are cut. The clipboard is always written and doubles as
   the recovery path when focus is wrong.
   *Amended 2026-08:* the clipboard write has two backends, selected **once at
   daemon startup** by compositor capability — this is still one path per
   session, not a per-utterance fallback. Compositors offering a data-control
   protocol (`ext-data-control-v1` / `zwlr-data-control`: wlroots, GNOME ≥ 47)
   get `wl-copy`. Without data-control (GNOME ≤ 46), `wl-copy` must map an
   invisible focus-grabbing popup for a selection serial, and focus-stealing
   prevention blocks that popup when the requester is a background daemon —
   `wl-copy` hangs until timeout and delivery always fails. There the daemon
   uses `xclip` under XWayland instead: X11 selection ownership needs no focus,
   and Mutter bridges X11 CLIPBOARD/PRIMARY to the Wayland selections. The
   xclip write is confirmed by a byte-exact read-back (`xclip -o`) before the
   chord may fire, preserving §4.3 copy-confirmed-before-paste.
8. **Cut from v1** (see §3 for the full table): incremental decoding / live
   preview and the old GTK HUD, the `hybrid`
   trigger mode (hold PTT is the default), the cancel binding, `dictate`, `bench`, the five
   systemd wrapper subcommands, per-cue sound overrides. The sole visual
   exception is the isolated, noninteractive lifecycle pill from decision 15.
   *Amended 2026-08-19:* `toggle` returned through the §7 ledger as
   `hotkey.mode = "toggle"` — one pure press-edge mapping in the daemon
   (`toggle_action`) plus a generation-guarded `audio.max_recording_seconds`
   stop that ends a forgotten recording through the normal stop path; `hybrid`
   stays cut.
9. **CLI surface: five subcommands** — `run`, `model download`, `doctor`,
   `devices`, `transcribe FILE`.
10. **ASR worker: child process kept, radically simplified.** One request at a
    time: either load-only or audio in → transcript out. An accepted recording
    start sends the load-only request on a background thread so cold model load
    overlaps capture; decode waits for that same request if recording ends first.
    The worker is restarted if dead and killed on idle timeout, with eviction
    held from recording start through pipeline completion. No job queue, no
    interim jobs, no supersession. Rationale: guaranteed memory release on idle
    unload (~1.5 GB), crash isolation from native-library segfaults, and the
    ability to abandon a stuck decode by killing the child. Results remain
    **word-timestamp-capable** so a streaming layer can be added on top later
    without rearchitecting.
11. **Config: 4 sections, ~19 keys** (schema in §5). Hard validation with
    key-scoped errors; **no migrations** (sole config holder). Formatting is
    fixed behavior with zero knobs.
12. **Testing policy** as codified in §6 — unit tests for pure logic only; a real
    non-mocked smoke suite is a first-class deliverable and a merge gate.
13. **Python floor drops to 3.12** (Ubuntu 24.04's system Python). Nothing needs
    3.14; the current code's PEP 758 syntax (`cli.py:693`) is an example of a
    3.14-only dependency to avoid. "Universally friendly" is a stated goal.
14. **The name stays `stenographer`.** License stays GPL-3.0-or-later; every
    source file keeps the SPDX header.
15. **Isolated lifecycle overlay with a narrow recording spectrum.** A default-on,
    click-through pill may display only `recording`, `transcribing`, `delivering`,
    or `error`; `hidden` removes it. Every visible state uses one 280×64 pill.
    Recording is spectrum-first, with the feather, exactly 18 solid white bars,
    and a red dot. The 5 px bars have 4 px gaps and range from a 4 px baseline to 44 px.
    The bars animate only while the daemon is recording — the physical key-hold in
    hold mode; in toggle mode, from the start press until the stop press or the
    max-duration stop. The other states retain their fixed interiors. While
    the model is actively loading, whichever pill is visible has a 4 logical px
    inset `#F59E0B` border whose opacity follows a 25%–85% sinusoid over two seconds,
    capped at 60 fps. The border has no glow, scaling, or movement; its timing is
    entirely helper-local. The daemon-side supervisor analyzes all microphone
    input with a rolling 32 ms Hann window at 60 fps, zero-padded to at least 4096
    FFT points, and sends only 18 quantized levels plus a model-loading boolean
    through strict protocol v4. Each band maps continuously from the configured
    `feedback.spectrum_floor_dbfs` (default −45.0, valid −96 through −13 dBFS) to a
    fixed −12 dBFS ceiling using 0.7 gamma and 2.5/22.5 ms attack/release. Input at
    or below the floor maps to protocol level zero and input at or above the ceiling
    maps to 255; less-negative floor values suppress more input. There is no rolling
    calibration, learned per-band history, bootstrap delay, or display gate. Samples
    and smoothing reset when recording starts. Raw samples and the internal stream
    epoch never cross into the helper. There is no speech classification, voice gate,
    transcript preview, controls, GTK dependency, or configurable visualizer
    surface. Native layer-shell is preferred and XWayland is a best-effort fallback.
    Helper/backend failure stops visualization work, degrades to sound and
    notifications, and cannot fail or block dictation. Lock
    screens and protected shell surfaces are out of scope.

---

## 3. Feature disposition table

Every feature of the current tool, so nothing disappears silently.

| Current feature | Disposition | Notes |
|---|---|---|
| PTT (hold) trigger mode | **Keep (default)** | `hotkey.mode = "hold"`: key down = record, key up = stop. |
| `toggle` / `hybrid` modes | Toggle **added back 2026-08-19**; hybrid stays cut | Toggle is `hotkey.mode = "toggle"`: press to start, press again — or the `audio.max_recording_seconds` timer — to stop. Hybrid was the state-machine complexity driver (`PENDING_TAP`, double-tap windows) and remains cut. |
| Cancel binding (Esc discard) | **Cut** | Owner decision; release the key and don't paste — or just delete the pasted text. |
| evdev hotkey capture, auto-detect, hotplug rescan | **Keep (simplified)** | Multi-device auto-detect and rescan-on-error keep real value; see §4.9. |
| Audio capture (PortAudio), RMS gate, resample fallback | **Keep** | See §4.2, §4.10. |
| Silence/hallucination guard stack | **Keep** | VAD, no-speech gate, RMS gate, silence trimming, anti-hallucination decode settings — as fixed behavior. See §4.5–4.7. |
| Incremental decoding / live preview (`live.py`, `streaming.py`, interim jobs) | Cut → later | ~1,500–2,000 lines existed to show words mid-utterance. Flagship add-later; v1 keeps the worker word-timestamp-capable. |
| Lifecycle overlay | **Keep (isolated, optional)** | Click-through pill; native layer-shell with XWayland fallback. Exactly 18 spectrum bars animate only while recording; a helper-local amber border breathes only while the model loads. State interiors remain fixed. Failure never affects dictation. |
| Old HUD (GTK helper, transcript preview, controls, general visualizer) | **Cut entirely** | The narrow recording spectrum and loading border are not a door to transcript preview, raw-audio IPC, controls, GTK, or additional animated states. |
| Sound cues (11) | **Keep, trimmed to 4** | `record_start`, `record_stop`, `delivered`, `error`. Bundled WAVs; global `volume`/`mute` only, no per-cue overrides. Model-loading activity is visual only. |
| Desktop notifications (`notify-send`) | **Keep** | Errors only. No-op when absent. |
| `type` injection via wtype | **Cut** | Replaced by decision 6/7. wtype dependency is gone entirely. |
| `clipboard_paste` via wtype chord | **Replaced** | Same shape, chord now via uinput. |
| Clipboard copy (`wl-copy`, both selections) | **Keep** | Always on; no config section. |
| Formatter (spacing, sentence caps, trailing space) | **Keep, zero knobs** | Fixed behavior; batch variant serves `transcribe`. Paragraph-pause breaks and raw-passthrough mode are cut. |
| `run` (daemon, single-instance lock) | **Keep** | |
| `transcribe FILE` (+ `--raw`?) | **Keep** | `--raw` optional; keep only if free. |
| `model download` | **Keep** | Models are never bundled. |
| `doctor` | **Keep (small)** | Probe: uinput access, input group, mic, model cache, `wl-copy`, audio player. Exit 78 on missing required capability. |
| `devices` | **Keep** | ~20 lines serving `audio.input_device`. |
| `dictate` (one-shot) | **Cut** | Niche. |
| `bench` (WER matrix, incremental replay) | Cut → later | Real value when choosing models; can return as a standalone `scripts/` script. |
| `enable`/`disable`/`start`/`stop`/`status` | **Cut** | Ship the unit file; document three `systemctl --user` one-liners in the README. |
| `update` (self-update) + `[update]` config | **Cut** | Distribution machinery. `git pull && reinstall`. |
| Config migrations (`text`/`paste`, `[streaming]`) | **Cut** | No migrations, ever, until there are external users. |
| argcomplete fast path + bash completion | **Cut** | |
| PyInstaller onedir build, `install.sh` | **Keep (local only)** | Development-machine build and single-user install; no release workflow, updater, or multi-distro installer. |
| Idle model unload | **Keep** | Via killing the worker child. |
| Eager/lazy model load knob | **Cut (always press-lazy)** | A cold model starts loading on the first accepted recording start, not daemon startup; its border follows the load from Recording onto Transcribing when the post-recording wait remains. |
| Single-instance flock | **Keep** | `$XDG_RUNTIME_DIR/stenographer.lock`, PID written into it. |
| Rotating log file, privacy-safe logging | **Keep** | See §4.12. |
| Error taxonomy + exit 78 convention | **Keep (smaller)** | One `StenographerError` base, `ConfigError`, a `fatal()` helper; exit 78 (`EX_CONFIG`) for config/capability failure. |
| Hotwords + initial_prompt | **Keep** | Proven load-bearing; see §4.4. |

---

## 4. Behavioral knowledge inventory

Hard-won operational knowledge that must survive the old code's deletion. Each item
is a constraint on the new implementation.

1. **Quiet-mic RMS.** The owner's speech can fall below RMS 0.01. Never gate audio
   on absolute RMS defaults tuned for "normal" mics. The `min_speech_rms` knob
   exists precisely because absolute defaults betray quiet setups; current default
   is 0.0005, and the gate requires **two consecutive 50 ms frames** above
   threshold so isolated clicks and dead air are rejected without eating soft
   speech onsets. `0` disables.
2. **Modifier release-guard before the paste chord.** The hotkey binding is
   typically a modifier (owner uses Right Ctrl). Delivery MUST wait for the
   physical binding to be released before sending the paste chord — a still-held
   modifier mutates Shift+Insert into something else. On release-wait timeout,
   proceed anyway: the clipboard already holds the transcript, so the user can
   paste manually.
3. **Copy-confirmed-before-paste.** Fire the paste chord only after the clipboard
   write has been confirmed. A failed copy followed by a chord pastes *stale*
   clipboard content into the focused app — worse than doing nothing.
4. **Hotwords break distil models.** `asr.hotwords` silently *deletes words* on
   distil-whisper variants. Hotword support requires a full model — this is why
   the default is `Systran/faster-whisper-medium.en` rather than a distil model.
   If the model is ever made swappable in docs/examples, carry this warning.
5. **Anti-hallucination decode stack.** Whisper hallucinates on silence. The
   current guards, all kept as fixed behavior: Silero VAD pre-filter with
   conservative speech/padding settings (`vad_filter`, default on); post-decode
   no-speech-probability gate per segment (`silence_threshold`, default 0.6);
   a ~2-second hallucination-silence guard; repeated-3-gram blocking; trailing-
   silence trimming before decode. Token ceiling (`max_new_tokens` ≈ 128
   internally) is **dynamically reduced for short audio** — a fixed large ceiling
   lets short clips hallucinate paragraphs.
6. **Output validation.** The current code validates decode output and raises
   (`PathologicalOutputError`) on degenerate transcripts rather than delivering
   garbage. Keep an equivalent check: it is the last line of defense before text
   lands in a focused window.
7. **Empty result is success-shaped, not error-shaped.** Recording with no speech
   (all gates fired) should end quietly — no paste, no error cue spam.
8. **PortAudio callback discipline.** The audio callback must only copy the mono
   block, publish that existing copy through a bounded latest-only handoff, and
   return. No FFT, smoothing, rendering, IPC, allocation-heavy work beyond the
   required copy, or locks shared with slow consumers. The supervisor-thread
   analyzer exists because violating this causes overflows/dropouts.
9. **Sample-rate fallback.** Not every device opens at 16 kHz. The current
   Recorder falls back through supported rates and polyphase-resamples to the
   ASR rate. Keep this — it is the difference between "works on my mic" and
   "works".
10. **cpu_threads auto-detect.** `0` means: affinity-visible *physical* cores,
    capped at 8. CTranslate2 scales badly past that; hyperthread counting makes
    it slower.
11. **Model presence probe.** Check the HF cache with
    `huggingface_hub.try_to_load_from_cache(repo_id, "config.json")`;
    transcription must open the **local cache only** — the daemon must never
    reach the network. `model download` uses `snapshot_download` with an
    allow-list (`*.json`, `model.bin`, `tokenizer.json`, `vocabulary.*`,
    `preprocessor_config.json`).
12. **Logging privacy and ownership.** Log numeric/structural metrics and
    transcript *lengths*; never audio, samples, transcript text, or result
    representations. Every command configures stderr plus a 5 MiB rotating file
    (three backups) at `$XDG_STATE_HOME/stenographer/stenographer.log`, falling
    back below `~/.local/state`. `STENOGRAPHER_LOG_LEVEL` is case-insensitive and
    defaults (including invalid values) to `INFO`. Setup owns and marks only its
    own handlers, preserving host handlers, and a file failure warns once before
    continuing stderr-only. Worker-child records cross a multiprocessing queue
    to the parent's handlers; the child never opens or rotates the file, and the
    queue/listener lifetime matches the child across idle unload, crash, respawn,
    and shutdown.
13. **Permissions.** evdev listening requires `input` group membership; uinput
    injection requires write access to `/dev/uinput` (udev rule or `uinput`
    group). `doctor` must probe both and say exactly what to fix.
14. **Config ergonomics kept from the old loader.** Missing config file → write
    annotated defaults, then load. Defaults recursively merged under user values.
    Every validation failure is a key-scoped `ConfigError` → exit 78. (The old
    `null`→`""` regex rewrite is dropped; `""` is simply the documented "unset".)
15. **First-use latency is a feature decision.** Press-lazy load means the first
    accepted recording after daemon start/idle-unload begins loading the model
    immediately while audio is captured. Only the portion still unfinished at
    recording end delays transcription. Model loading is intentionally silent so
    no loading cue can contaminate captured audio; the optional pill border shows
    activity from load start through ready or failure.
16. **The testing lesson (why §6 exists).** 489 unit tests stayed green while
    paste mode was dead for a year, because unit tests mocked `subprocess.run`
    and integration tests only ran by hand. Green ≠ working when every boundary
    is mocked.
17. **Overlay isolation and privacy.** Lifecycle state is published only after
    the corresponding operation becomes true: recording after capture starts,
    transcription after the speech gate passes (early only when a cold load is
    unfinished, otherwise immediately before decode), and delivery only for
    non-empty formatted output. A cold load may run during recording, but
    `recording` remains the authoritative display state so a loading-activity edge
    cannot invalidate spectrum frames. The amber border surrounds the recording
    pill during a cold warm-up. If loading remains unfinished when recording ends
    and the speech gate passes, the same-width `transcribing` state appears and the
    same border carries across. The border is removed immediately after ready or
    load failure. There is no loading display state, loading label/dot, or overlay
    model-ready lifecycle record. Silence,
    empty output, and confirmed paste hide immediately; operational errors show a
    fixed `error` state for 2.5 seconds while detailed notifications remain
    unchanged. When recording ends (key-up in hold mode; the stop press or
    max-duration timer in toggle mode), analysis deactivates and `hidden` is
    queued before sample finalization, so recording frames cannot survive into
    transcription.
    Variable IPC is limited to exactly 18 integer spectrum levels in `[0,255]`,
    tied to the current recording generation and ordered by sequence, plus a strict
    active/inactive model-loading boolean. Loading activity neither advances nor
    resets recording generations, and pulse phase/timing never crosses IPC.
    IPC never contains transcript text, formatted text, raw audio/samples, the
    recorder stream epoch, detailed errors, model names, device names, or user
    configuration. Spectrum input is not speech-gated or classified. The fixed
    floor affects only display levels; the microphone signal remains untouched, and
    energy above the floor may affect the overlay without affecting capture,
    transcription, or delivery.
    Analysis, rendering, and IPC stay off the PortAudio callback and daemon lock.

---

## 5. Target architecture

### Line budget

**~1,500–2,000 lines of source total.** The budget is a design constraint, not a
prediction — if a module wants to blow past its estimate, that is a signal to cut,
not to grow the budget.

### Module map

```
src/stenographer/
  __init__.py          version re-export
  _version.py          single version string (no -dev gymnastics in v1)
  cli.py        ~150   argparse + dispatch: run / transcribe / model download / doctor / devices
  config.py     ~150   TOML load, frozen dataclasses, key-scoped validation, default writer
  daemon.py     ~200   orchestrator: hotkey → record → transcribe → deliver; single-instance
                       lock; signal handling; the only module holding cross-component state
  hotkey.py     ~150   evdev hotkey listener: chord parse/edges, keyboard auto-detect, rescan
                       on error; the daemon maps edges to actions per hotkey.mode
  audio.py      ~150   Recorder: PortAudio stream, block-copy/latest-only handoff,
                       RMS gate, sample-rate fallback + resample, max-seconds cap
  worker.py     ~150   ASR child process: spawn, one request/response at a time,
                       restart-if-dead, kill-on-idle; queue logs to parent
  spectrum.py          pure fixed-range FFT, band mapping, smoothing, quantization
  status.py            lifecycle states, strict protocol v4, pure coalescing/generation policy
  overlay.py           isolated helper supervision, analyzer ownership, backend selection
  logging_setup.py     stderr + rotating state file, level resolver, worker log queue
  model.py      ~120   faster-whisper wrapper: decode settings from §4.5, word timestamps,
                       output validation, cpu_threads resolution
  format.py      ~60   fixed formatter: spacing ownership, sentence caps, "i"→"I",
                       trailing space; batch variant for transcribe
  deliver.py     ~80   wl-copy both selections → confirm → uinput Shift+Insert,
                       release-guard first
  feedback.py    ~60   4 cues via canberra/pw-play/paplay, volume/mute, no-op degrade
  doctor.py      ~80   capability probe + resolved-config dump; exit 78 contract
  notify.py      ~40   notify-send errors, no-op degrade
  assets/sounds/       4 WAVs (record_start, record_stop, delivered, error)
```

Flat package — no subpackages until a directory earns it.

### Config schema (complete)

```toml
[stenographer.hotkey]
binding = "KEY_RIGHTCTRL"    # evdev key/chord that triggers dictation
device = ""                  # explicit /dev/input/event* path; "" = auto-detect
mode = "hold"                # hold = push-to-talk; toggle = press to start, press again to stop

[stenographer.audio]
input_device = ""            # PortAudio device name/index; "" = system default
min_speech_rms = 0.0005      # pre-decode energy gate; 0 disables (see §4.1)
max_recording_seconds = 600

[stenographer.asr]
model = "Systran/faster-whisper-medium.en"
compute_type = "int8"        # int8 | int8_float16 | float16 | float32 | default
beam_size = 1
hotwords = ""                # comma-separated proper nouns (full models only, §4.4)
initial_prompt = ""          # style/domain context prepended to decoding
vad_filter = true
silence_threshold = 0.6      # post-decode no-speech-probability gate
idle_unload_seconds = 900    # kill worker child after idleness; 0 disables
cpu_threads = 0              # 0 = auto (§4.10)

[stenographer.feedback]
volume = 0.6
mute = false
overlay = true                 # best-effort lifecycle pill; dictation is independent
spectrum_floor_dbfs = -45.0    # less-negative values suppress more spectrum input
```

Everything else that was configurable is now fixed behavior or gone.

### Worker contract

- Child process (spawn), one outstanding request at a time.
- Load-only request: no audio; response is the metadata-only `model_ready` event
  or a typed error. Decode request: float32 mono audio at 16 kHz; response is
  formatted-input segments **with word timestamps**, or a typed error.
- Parent kills the child after `idle_unload_seconds` of no requests; the next
  request respawns it. Idle eviction is held while a recording and
  its pipeline own the model, even when the timeout is shorter than the capture.
- Child death mid-request → error cue + notify, respawn on next use. Never takes
  the daemon down.
- On an accepted recording start, a background thread sends the cold load-only
  request. Parent observers receive loading start, then `model_ready` after the
  child confirms the model, then loading finish. A failed load also reports finish
  after its error response. A decode serializes behind an unfinished load and
  publishes `transcribing` immediately before sending audio. Warm starts perform
  no worker request until decode.
- Model-load and decode records travel over a per-child logging queue to the
  parent's handlers. Idle unload, crash recovery, respawn, and shutdown stop the
  listener and close its queue; no child process owns a file handler.
- The word-timestamp requirement is the single constraint that keeps the
  streaming/preview door open (§7) without paying for it now.

### Daemon utterance lifecycle

```
after lock → Recorder prepares a stopped stream → hotkey listener starts
start (key down; toggle: first press)
          → Recorder starts → hold idle eviction → overlay `recording` baseline + spectrum
          → record_start cue → cold worker load-only request in background
            └─ while loading: amber border on whichever pill is visible
stop (key up; toggle: second press or the max_recording_seconds timer)
          → overlay `hidden` → Recorder stops + secures samples → record_stop cue → RMS gate
            └─ gate fails → remain `hidden` (silently)
          → overlay `transcribing`
            ├─ if cold load is unfinished: show while waiting
            └─ otherwise: show immediately before decode
          → worker result
            └─ empty/all-gated → overlay `hidden` (silently)
          → format non-empty result → overlay `delivering`
          → wl-copy (both selections) → confirm
            └─ copy failed → overlay `error` (2.5 s), error cue + notify;
              NO chord (§4.3)
          → wait for binding release (§4.2) → uinput Shift+Insert
          → overlay `hidden` → delivered cue
all outcomes → release idle-eviction hold
```

The Recorder has three states: unprepared, prepared/stopped, and capturing.
Preparation negotiates channels and sample-rate fallbacks without starting
callbacks or retaining samples. A normal stop keeps the selected microphone and
stopped stream for the next press. If startup preparation fails, the daemon logs
one warning and retries on the next press. If a retained stream has gone stale,
activation closes it and performs exactly one renegotiate-and-start retry; a
first on-demand preparation gets only its normal attempt. Any uncertain stop or
mid-capture failure invalidates the stream and discards all buffered audio, so a
later press prepares fresh and no partial transcript can be pasted. Cue failures
cannot delay these capture boundaries or orphan a recording.

One utterance at a time; a start press during transcription of the previous
utterance is ignored (toggle mode neither starts nor queues; v1 keeps no
utterance queue).

---

## 6. Testing policy (codified)

Motivated by §4.16. These are rules, not suggestions:

1. **Unit tests cover pure logic only** — formatter, config validation, RMS gate
   and spectrum math, protocol encode/decode and ordering, renderer geometry,
   hotkey chord parsing. Fast, no mocks of external processes.
2. **No mocked-subprocess theater.** A test that mocks `subprocess.run` /
   `UInput` / `wl-copy` and asserts "we would have called it" is worse than no
   test: it costs maintenance and manufactures false confidence. Delete on sight.
3. **The smoke suite is a first-class deliverable.** A small set of tests that
   *really* create a uinput device, *really* write and read back the clipboard,
   *really* play a cue, *really* load the model on a tiny bundled WAV and check
   the transcript. Marked `integration`, run with one command
   (`STENOGRAPHER_INTEGRATION=1 pytest`), on the real machine.
   It also exercises real rotating/fallback logging and verifies that a spawned
   worker forwards decode metrics without exposing the fixture transcript.
4. **The smoke suite is a merge gate.** No dev → main merge without a green smoke
   run on a real box — the existing habit, now written down.
5. **Mock-only testability is a design smell.** If a component can only be tested
   by mocking everything it touches, restructure the component (extract the pure
   part), don't write the mock.
6. **Test budget follows the source budget.** ~2,000 lines of source does not
   justify 8,000 lines of tests. If the test:src ratio creeps past ~1:1, the
   tests are re-testing the same logic through different layers.

---

## 7. Add-later ledger

Features deliberately deferred, each with the v1 constraint that keeps its door
open. When one is added, it must still pass the §1 razor at that time.

| Feature | Door kept open by |
|---|---|
| **Live preview / incremental decoding** (flagship) | Worker returns word timestamps; formatter is append-only by construction; a streaming driver layers *above* the worker exactly as `IncrementalDriver` did. Old references: LocalAgreement-N committer (`asr/streaming.py`), coalescing + single-final-decode design. |
| **Transcript preview / general audio visualizer** | Remains cut. The approved exceptions are exactly 18 locally analyzed bars while recording and the helper-local model-loading border. Adding text, raw-audio IPC, controls, more animated states, or interim decoding requires revising this record. |
| **Toggle mode** | *Done 2026-08-19.* Landed exactly through the door kept open: the listener still maps key events through `edge()`; toggle is one pure daemon-side mapping (`toggle_action`) plus a generation-guarded max-duration timer that ends a forgotten recording through the normal stop path. Hybrid remains skipped. |
| **`bench`** | Standalone script in `scripts/`, driving the public `model.py` API. Does not re-enter the package. |
| **Distribution layer** (installer, self-update, completions) | Blocked on external users existing. Clean config validation and a small codebase are the only v1 prerequisites, and both are core goals anyway. *Partially reintroduced 2026-08: the local PyInstaller onedir build (spec + hooks under `packaging/`, `scripts/build.sh`, BUILD.md) and a single-machine per-user installer (`scripts/install.sh`: bundle → `~/.local/share/stenographer`, symlink → `~/.local/bin`, systemd user unit from `packaging/stenographer.service`) — no CI release, no multi-distro/curl-pipe-bash installer, no completions, no self-update. Passed the §1 razor as a dev-machine convenience; the rest of this row stays gated.* |
| **`dictate` one-shot** | Trivial recomposition of daemon pieces if ever wanted. |

---

## 8. Build order

Each milestone ends green (`ruff check`, unit tests) and independently verifiable
on the dev machine. Old code stays in place until M6 — it is the behavioral
reference.

- **M0 — Scaffold.** New package skeleton beside the old one (e.g.
  `src/stenographer_v2/` during transition, renamed at M6 — or a branch-level
  swap; implementer's choice, document it). `pyproject.toml`: py3.12 floor, deps
  = faster-whisper, sounddevice, soundfile, evdev, huggingface_hub. ruff + pytest
  config. *Verify: venv installs, empty CLI runs.*
- **M1 — Model + batch path.** `config.py`, `model.py`, `format.py`,
  `cli.py: transcribe, model download`. *Verify: `transcribe` on a known WAV
  matches old tool's output; hotwords honored.*
- **M2 — Capture.** `audio.py` with RMS gate, fallback rates. *Verify: record a
  clip via a temporary CLI hook, inspect WAV; quiet-mic gate test at low RMS.*
- **M3 — Worker.** `worker.py` child process, idle kill, restart. *Verify: smoke
  test — transcribe through the child, kill it mid-idle, transcribe again.*
- **M4 — Delivery.** `deliver.py` (wl-copy + uinput chord + release guard),
  `feedback.py`. *Verify: smoke test pastes into a focused terminal on Hyprland
  AND on a GNOME Wayland session; clipboard readable via `wl-paste`.*
- **M5 — Daemon.** `hotkey.py`, `daemon.py`, single-instance lock, signals,
  cues wired, `notify.py`; systemd unit file in `packaging/`. *Verify: real
  dictation end-to-end on both compositor families; this is the acceptance test.*
- **M6 — Doctor + deletion.** `doctor.py`, `devices`; smoke suite complete;
  README rewritten (three `systemctl --user` one-liners); **delete** the old
  package, old tests, `update.py`-era workflows, GUI-reauthor workflow files;
  reconcile `CLAUDE.md`. *Verify: full smoke suite green; fresh-venv install from
  scratch works.*

Real-dictation validation (M5) precedes any dev → main merge, per §6.4.

The overlay acceptance on both Hyprland/wlroots and GNOME/Mutter verifies that
the baseline recording pill maps immediately after recording starts (successful
key-down, or the toggle start press). Steady fan and room noise at or below the
configured floor stay on the 4 px baselines immediately, including on a newly
opened stream, while quiet speech above the floor promptly affects the expected
parts of its 18-band spectrum. The pill disappears when recording ends (physical
key-up, the toggle stop press, or the max-duration stop). With
`hotkey.mode = "toggle"`, the spectrum animates with no key held, and a short
`max_recording_seconds` ends the session with the stop cue and a delivered
transcript. On a cold press, the 4 px amber border begins breathing immediately
while spectrum frames continue. A short recording carries the same border onto
the same-width Transcribing pill without an intermediate loading state; it
disappears if the model becomes ready while recording or after a load failure.
No Loading model label or amber loading dot appears. Warm recordings show no
border, and it returns after idle unload. All visible pills remain 280×64, with
fixed labels, dots, geometry, and interiors; visible-state transitions and border
repaints must not replace the layer surface/XWayland window or move or resize its
304×88 transparent canvas. Disabling, killing, or losing the overlay never changes
recording, transcription, or delivery success. The real XWayland smoke additionally
checks the in-place Recording-to-Transcribing transition, spectrum and border
repaint, and the empty input region. These checks require the opt-in integration
suite and real hardware.

### Cold-start and logging acceptance

Before a dev → main merge, perform the following on the real target machine in
addition to the GNOME/wlroots checks above:

1. On three consecutive cold service starts, dictate “Opening words must remain
   in this transcription” immediately on the start cue. Each result must retain
   at least “Opening words must remain.”
2. Repeat once with cues muted and once after a forced short ASR idle unload.
3. Disconnect/reconnect the microphone or restart PipeWire, then confirm the
   next press recovers and a failed capture never pastes partial text.
4. Inspect the journal, `stenographer.log`, and rotated backups. Confirm startup,
   capture, recovery, ASR/VAD, and transcript-length metrics are present, and
   that neither the dictated canary phrase nor any transcript/audio content is.
5. Run the complete opt-in integration suite and the existing GNOME/wlroots
   real-dictation acceptance.
