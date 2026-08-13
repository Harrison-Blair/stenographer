# Stenographer Reauthor — Reference Document

Status: **settled**. The decisions in §2 were made with the repo owner on 2026-08-12 —
do not relitigate them during implementation. Everything else in this document is
reference material extracted from the current codebase so it survives that code's
deletion.

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
4. **Personal-first, distribute-later.** Eventual distribution is a goal;
   distribution *machinery* is not a v1 deliverable. Cut now: self-update,
   release-channel logic, `-dev` version-stripping workflow, multi-distro
   `install.sh`, config-migration shims, argcomplete fast paths, PyInstaller
   packaging. v1 runs from the venv with a systemd user unit pointing at it.
   The only concession to future distribution is cheap: a clean config schema
   with good validation errors, and a codebase small enough that adding an
   updater later is trivial.
5. **Target: any Wayland session, GNOME included.** Not two specific machines —
   portable across Wayland compositors (wlroots-family and GNOME/Mutter alike).
   **Nothing may depend on layer-shell, virtual-keyboard, or any
   compositor-specific protocol.** That dependency is the trap the old design
   fell into.
6. **Injection mechanism: `uinput`** (kernel virtual input device via
   python-evdev's `UInput`). Display-server-independent — works on GNOME,
   Hyprland, X11, everywhere. One injection path, zero fallback axes. The old
   plan's "no ydotool/uinput" decision is explicitly overturned: the permission
   story (`input` group / udev rule) is the same one the evdev hotkey listener
   already requires.
7. **Delivery: single paste-chord path.** Copy the transcript to **both** Wayland
   selections (clipboard + primary) via `wl-copy`, then send **Shift+Insert** via
   uinput — the most broadly honored paste chord across toolkits. Per-character
   typing and `max_chars` are cut. The clipboard is always written and doubles as
   the recovery path when focus is wrong.
8. **Cut from v1** (see §3 for the full table): incremental decoding / live
   preview, the entire visualizer/HUD, `toggle` and `hybrid` trigger modes
   (**PTT only**), the cancel binding, `dictate`, `bench`, the five systemd
   wrapper subcommands, per-cue sound overrides.
9. **CLI surface: five subcommands** — `run`, `model download`, `doctor`,
   `devices`, `transcribe FILE`.
10. **ASR worker: child process kept, radically simplified.** One job at a time,
    audio in → transcript out, restarted if dead, killed on idle timeout. No job
    queue, no interim jobs, no supersession. Rationale: guaranteed memory release
    on idle unload (~1.5 GB), crash isolation from native-library segfaults, and
    the ability to abandon a stuck decode by killing the child. Results remain
    **word-timestamp-capable** so a streaming layer can be added on top later
    without rearchitecting.
11. **Config: 4 sections, ~16 keys** (schema in §5). Hard validation with
    key-scoped errors; **no migrations** (sole config holder). Formatting is
    fixed behavior with zero knobs.
12. **Testing policy** as codified in §6 — unit tests for pure logic only; a real
    non-mocked smoke suite is a first-class deliverable and a merge gate.
13. **Python floor drops to 3.12** (Ubuntu 24.04's system Python). Nothing needs
    3.14; the current code's PEP 758 syntax (`cli.py:693`) is an example of a
    3.14-only dependency to avoid. "Universally friendly" is a stated goal.
14. **The name stays `stenographer`.** License stays GPL-3.0-or-later; every
    source file keeps the SPDX header.

---

## 3. Feature disposition table

Every feature of the current tool, so nothing disappears silently.

| Current feature | Disposition | Notes |
|---|---|---|
| PTT trigger mode | **Keep** | The only mode. Key down = record, key up = stop. |
| `toggle` / `hybrid` modes | Cut → later | Hybrid was the state-machine complexity driver (`PENDING_TAP`, double-tap windows, generation-guarded timers). |
| Cancel binding (Esc discard) | **Cut** | Owner decision; release the key and don't paste — or just delete the pasted text. |
| evdev hotkey capture, auto-detect, hotplug rescan | **Keep (simplified)** | Multi-device auto-detect and rescan-on-error keep real value; see §4.9. |
| Audio capture (PortAudio), RMS gate, resample fallback | **Keep** | See §4.2, §4.10. |
| Silence/hallucination guard stack | **Keep** | VAD, no-speech gate, RMS gate, silence trimming, anti-hallucination decode settings — as fixed behavior. See §4.5–4.7. |
| Incremental decoding / live preview (`live.py`, `streaming.py`, interim jobs) | Cut → later | ~1,500–2,000 lines existed to show words mid-utterance. Flagship add-later; v1 keeps the worker word-timestamp-capable. |
| Visualizer / HUD (GTK helper, JSON-lines IPC, FFT spectrum) | **Cut entirely** | Cannot exist on GNOME anyway. Feedback = sound cues + notify-send. |
| Sound cues (11) | **Keep, trimmed to 5** | `record_start`, `record_stop`, `delivered`, `error`, `model_loading`. Bundled WAVs; global `volume`/`mute` only, no per-cue overrides. |
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
| PyInstaller onedir build, `install.sh` | **Cut** | venv + systemd unit. |
| Idle model unload | **Keep** | Via killing the worker child. |
| Eager/lazy model load knob | **Cut (always lazy)** | `model_loading` cue covers the first-use delay. |
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
8. **PortAudio callback discipline.** The audio callback must only copy the block
   and return. No FFT, no analysis, no allocation-heavy work, no locks shared
   with slow consumers. The old code's one-slot-queue + worker-thread pattern
   exists because violating this causes overflows/dropouts.
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
12. **Logging privacy.** Log metrics and transcript *lengths*; never audio, never
    transcript text. Rotating file at `$XDG_STATE_HOME/stenographer/` plus
    stderr; level via `STENOGRAPHER_LOG_LEVEL`.
13. **Permissions.** evdev listening requires `input` group membership; uinput
    injection requires write access to `/dev/uinput` (udev rule or `uinput`
    group). `doctor` must probe both and say exactly what to fix.
14. **Config ergonomics kept from the old loader.** Missing config file → write
    annotated defaults, then load. Defaults recursively merged under user values.
    Every validation failure is a key-scoped `ConfigError` → exit 78. (The old
    `null`→`""` regex rewrite is dropped; `""` is simply the documented "unset".)
15. **First-use latency is a feature decision.** Lazy load means the first
    utterance after start/idle-unload waits for model load (seconds). The
    `model_loading` cue is what makes that acceptable — don't drop it.
16. **The testing lesson (why §6 exists).** 489 unit tests stayed green while
    paste mode was dead for a year, because unit tests mocked `subprocess.run`
    and integration tests only ran by hand. Green ≠ working when every boundary
    is mocked.

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
  hotkey.py     ~150   evdev PTT listener: chord parse, keyboard auto-detect, rescan on error
  audio.py      ~150   Recorder: PortAudio stream, block-copy callback, RMS gate,
                       sample-rate fallback + resample, max-seconds cap
  worker.py     ~150   ASR child process: spawn, one request/response at a time,
                       restart-if-dead, kill-on-idle
  model.py      ~120   faster-whisper wrapper: decode settings from §4.5, word timestamps,
                       output validation, cpu_threads resolution
  format.py      ~60   fixed formatter: spacing ownership, sentence caps, "i"→"I",
                       trailing space; batch variant for transcribe
  deliver.py     ~80   wl-copy both selections → confirm → uinput Shift+Insert,
                       release-guard first
  feedback.py    ~60   5 cues via pw-play/paplay, volume/mute, no-op degrade
  doctor.py      ~80   capability probe + resolved-config dump; exit 78 contract
  notify.py      ~40   notify-send errors, no-op degrade
  assets/sounds/       5 WAVs (reuse current assets: ptt_on→record_start, ptt_off→record_stop,
                       transcribe_done→delivered, error, model_loading)
```

Flat package — no subpackages until a directory earns it.

### Config schema (complete)

```toml
[stenographer.hotkey]
binding = "KEY_RIGHTALT"     # evdev key/chord that triggers dictation
device = ""                  # explicit /dev/input/event* path; "" = auto-detect

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
```

Everything else that was configurable is now fixed behavior or gone.

### Worker contract

- Child process (spawn), one outstanding request at a time.
- Request: audio (float32 mono @ 16 kHz) + decode params. Response: formatted-input
  segments **with word timestamps**, or a typed error.
- Parent kills the child after `idle_unload_seconds` of no requests; next request
  respawns it (cue: `model_loading`).
- Child death mid-request → error cue + notify, respawn on next use. Never takes
  the daemon down.
- The word-timestamp requirement is the single constraint that keeps the
  streaming/preview door open (§7) without paying for it now.

### Daemon utterance lifecycle

```
key down  → record_start cue → Recorder starts
key up    → record_stop cue → Recorder stops → RMS gate
            └─ gate fails → done (silently)
          → worker.transcribe(audio)
            └─ empty/all-gated → done (silently)
          → format → wl-copy (both selections) → confirm
            └─ copy failed → error cue + notify; NO chord (§4.3)
          → wait for binding release (§4.2) → uinput Shift+Insert
          → delivered cue
```

One utterance at a time; a key-down during transcription of the previous utterance
is ignored (v1 keeps no utterance queue).

---

## 6. Testing policy (codified)

Motivated by §4.16. These are rules, not suggestions:

1. **Unit tests cover pure logic only** — formatter, config validation, RMS gate
   math, worker-protocol encode/decode, hotkey chord parsing. Fast, no mocks of
   external processes.
2. **No mocked-subprocess theater.** A test that mocks `subprocess.run` /
   `UInput` / `wl-copy` and asserts "we would have called it" is worse than no
   test: it costs maintenance and manufactures false confidence. Delete on sight.
3. **The smoke suite is a first-class deliverable.** A small set of tests that
   *really* create a uinput device, *really* write and read back the clipboard,
   *really* play a cue, *really* load the model on a tiny bundled WAV and check
   the transcript. Marked `integration`, run with one command
   (`STENOGRAPHER_INTEGRATION=1 pytest`), on the real machine.
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
| **Visualizer/HUD** | Daemon state transitions flow through one place (`daemon.py`); a status sink can subscribe there. If revived, software-render + per-compositor window backend (the superseded GUI plan's Pillow research applies) — never a compositor-specific protocol as a hard dependency. |
| **Toggle mode** | The PTT listener maps key events → start/stop through one small function; a second mode is a new mapping, not a new architecture. Skip hybrid unless truly missed. |
| **`bench`** | Standalone script in `scripts/`, driving the public `model.py` API. Does not re-enter the package. |
| **Distribution layer** (installer, self-update, packaging, completions) | Blocked on external users existing. Clean config validation and a small codebase are the only v1 prerequisites, and both are core goals anyway. |
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
