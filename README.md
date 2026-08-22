<p align="center">
  <img src="src/stenographer/assets/icons/stenographer.png" width="128" alt="stenographer icon" />
</p>



# stenographer
> 1. A writer of shorthand
> 
> 2. A person employed chiefly to take and transcribe dictation
>
>    *\- [Merriam Webster](https://www.merriam-webster.com/dictionary/stenographer)*

[![release](https://img.shields.io/github/v/release/Harrison-Blair/stenographer?color=brightgreen)](https://github.com/Harrison-Blair/stenographer/releases)

Local, offline, Wayland push-to-talk / toggle dictation daemon. Press a
configurable hotkey, speak, get the text at your cursor and in your
clipboard. See [BUILD.md](BUILD.md) for the standalone-binary build
instructions.

> [!NOTE]
> This `README.md` was generated with AI, but reviewed for accuracy by a human

See [Install](#install) for the install steps and a [Quick start](#quick-start) for the post-install flow. Default hotkey: right-Ctrl (short press <0.5 s toggles recording; long press ≥0.5 s is push-to-talk).


<!--
DO NOT EDIT ABOVE THIS LINE.

The title and description above are user-owned and are preserved
verbatim by this project and by any automated tooling (including AI
assistants). Everything below this comment is generated / maintained
content. To change the project description, edit above this line.
-->

## What it is

Press a hotkey, speak, and the text appears at your cursor.

`stenographer` is a push-to-talk / toggle dictation daemon for any Wayland
session. It listens to Linux evdev keyboard events, records from the configured
microphone while the hotkey is held (or, with `hotkey.mode = "toggle"`, between
one press and the next), transcribes locally with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), and delivers the
utterance to the focused application: the transcript is copied to both
selections (via `wl-copy`, or via `xclip` under XWayland on compositors without
a data-control protocol, such as GNOME 46 and older), then pasted with a single
Shift+Insert chord sent through a kernel `uinput` virtual keyboard. Because injection is
display-server-independent, it works identically on wlroots compositors
(Hyprland, sway, …) and on GNOME/Mutter.

Everything is offline and English-only. Nothing is sent anywhere; the daemon
never touches the network (the model is fetched once, explicitly, with
`stenographer model download`).

The architecture and binding behavioral decisions are recorded in
[docs/reauthor.md](docs/reauthor.md).

## Quick start

```sh
git clone https://github.com/Harrison-Blair/stenographer
cd stenographer
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/stenographer setup --quick    # configure essentials, download, check capabilities
.venv/bin/stenographer run              # foreground daemon
```

`setup --quick` configures the hotkey, microphone, cues, and optional display
spectrum, offers the explicit ~1.5 GB model download when needed, and runs the
normal capability probe. Plain `setup` remains the complete 19-key review. You
can instead run `stenographer model download` and `stenographer doctor` directly.

Hold the hotkey (default: right-Ctrl), speak, release. The transcript is pasted
at your cursor and left on the clipboard. Prefer press-to-start,
press-again-to-stop? Set `hotkey.mode = "toggle"` — in that mode a forgotten
recording ends automatically at `audio.max_recording_seconds` as if you had
pressed again.

On a cold start, model loading begins as soon as recording starts and overlaps
your speech; only unfinished loading time remains after recording ends. By
default a small, click-through pill shows an 18-band live spectrum while
recording. A short cold recording changes directly to the same-width Transcribing
pill while the model finishes loading. While the load is active, a subtle amber
border breathes around whichever pill is visible; there is no loading label or
loading dot. Transcribing, Delivering, and Error are fixed states. Raw microphone
samples stay in the daemon; the isolated display helper receives only 18 quantized
levels and an active/inactive loading boolean, never pulse timing, transcript text,
model/device names, configuration values, or detailed errors. Set
`feedback.overlay = false` to disable the whole visual surface and its analysis;
sound cues, notifications, and dictation continue unchanged.

## Requirements

- Linux with any Wayland compositor.
- Read access to `/dev/input/event*` — membership in the `input` group
  (`sudo usermod -aG input $USER`, then re-login).
- Write access to `/dev/uinput` for the paste chord (a udev rule or the
  `uinput` group).
- `wl-clipboard` (for `wl-copy`) on compositors with a data-control protocol
  (wlroots, GNOME 47+); `xclip` on compositors without one (GNOME 46 and
  older) — `stenographer doctor` reports which backend was detected.
- A PortAudio input device (PipeWire or PulseAudio provide this).
- Optional: `canberra-gtk-play` (preferred), `pw-play`, or `paplay` for the sound
  cues, and `notify-send` for error notifications — both degrade to no-ops when
  absent.
- Optional visual feedback uses native Wayland layer-shell when the compositor
  provides it, otherwise a compatible XWayland server. If neither backend is
  usable, only the pill is disabled.

`stenographer doctor` probes all of the above and prints exactly one overlay
status (`disabled`, `layer-shell`, `XWayland fallback`, or an actionable
unavailable reason). Overlay availability is informational and never changes
the command's exit status; a missing required dictation capability still gives
exit code 78.

Python 3.12 or newer.

## Running as a service

```sh
scripts/install.sh
```

builds the standalone bundle (see [BUILD.md](BUILD.md)), copies it to
`~/.local/share/stenographer/`, symlinks `~/.local/bin/stenographer`, installs
`packaging/stenographer.service` as a systemd user unit, and enables + starts
it (`--no-enable` / `--no-start` to opt out, `--install-dir DIR` to relocate).
It also caches native Bash, Zsh, and Fish completion definitions under
`$XDG_DATA_HOME` (default `~/.local/share`) without changing shell configuration.
Equivalent manual steps:

```sh
cp packaging/stenographer.service ~/.config/systemd/user/
systemctl --user enable --now stenographer.service
journalctl --user -u stenographer -f
```

The unit's `ExecStart` points at `~/.local/share/stenographer/stenographer`;
edit the path if you run from a venv instead.

## Shell completion

Generate one deterministic native definition with:

```sh
stenographer completion bash
stenographer completion zsh
stenographer completion fish
```

The installer writes all three to the standard XDG locations:

- Bash: `$XDG_DATA_HOME/bash-completion/completions/stenographer`. Install and
  enable `bash-completion` so Bash discovers it.
- Zsh: `$XDG_DATA_HOME/zsh/site-functions/_stenographer`. Add that directory to
  `fpath` before `autoload -Uz compinit && compinit`; the installer prints the
  exact one-time lines but never edits `.zshrc`.
- Fish: `$XDG_DATA_HOME/fish/vendor_completions.d/stenographer.fish`, loaded
  automatically by Fish.

The definitions complete the public commands and flags plus local file paths
for `transcribe FILE`. They do not probe devices, models, configuration, audio,
or the network.

## Logging

Every command logs to stderr and to
`$XDG_STATE_HOME/stenographer/stenographer.log` (or
`~/.local/state/stenographer/stenographer.log` when `XDG_STATE_HOME` is unset).
The file rotates at 5 MiB and keeps three backups. Set
`STENOGRAPHER_LOG_LEVEL=debug` (level names are case-insensitive) for additional
diagnostics; the default and the fallback for an invalid value are `INFO`.

Logs contain timings, counts, negotiated audio settings, and transcript lengths,
never dictated text or audio. If the state directory cannot be created, the
command continues with stderr logging and reports the problem there.

## Configuration

`~/.config/stenographer/config.toml` is created with annotated defaults on
first run. Its four sections contain 19 supported keys:

| Section | Keys |
|---|---|
| `hotkey` | `binding` (evdev key/chord, default `KEY_RIGHTCTRL`), `device`, `mode` (`hold` \| `toggle`, default `hold`) |
| `audio` | `input_device`, `min_speech_rms`, `max_recording_seconds` |
| `asr` | `model`, `compute_type`, `beam_size`, `hotwords`, `initial_prompt`, `vad_filter`, `silence_threshold`, `idle_unload_seconds`, `cpu_threads` |
| `feedback` | `volume`, `mute`, `overlay` (default `true`), `spectrum_floor_dbfs` (scalar default `-45.0` or an 18-band calibrated profile) |

Note: `hotwords` require a full (non-distil) model — the default
`Systran/faster-whisper-medium.en` supports them.

### Interactive setup

Run `stenographer setup --quick` for the focused, rerunnable path. It selects an
automatic, detected, or manually entered hotkey device; captures one key or a
held chord live (without grabbing the keyboard), keeps the current binding, or
accepts validated evdev names typed by hand. Capture waits until every key is
released, times out after 15 seconds, and leaves Ctrl-C working. Quick setup then
chooses `hold` or `toggle`, the microphone, cue volume/mute, and the optional
overlay. Its review explicitly retains the audio gate, recording limit, and all
ASR settings.

Plain `stenographer setup` keeps the complete 19-key review: Hotkey, Audio, ASR,
and Feedback one section at a time. Detected microphone and hotkey devices are
offered while keeping automatic-device and manual-entry choices available. Enter
retains the displayed value; optional strings have an explicit clear choice. The
final review can save, cancel without making changes, or return to any section.
Both paths support only the documented `hold` and `toggle` trigger modes.

Setup materializes all 19 supported keys but preserves hand-written comments,
inline comments, ordering, unknown keys, and unrelated layout. Before writing,
it refuses to overwrite a file changed while the wizard was open and validates
the result with the same schema used by every other command. An existing file
gets an exact timestamped `.bak-…Z` copy; the replacement is atomic, retains the
file mode, and updates a symlink target without replacing the symlink. If the
rendered bytes are unchanged, neither the config nor a backup is written.

When the overlay is enabled, choose Keep, Manual, or Automatic for
`feedback.spectrum_floor_dbfs`; quick setup skips this step when the overlay is
disabled. When no profile exists, Automatic is recommended by default. It asks
for a quiet room,
counts down for three seconds, records five seconds from the selected microphone,
then records three seconds of normal speech to verify visibility. The silent
sample produces one fixed floor for each of the 18 bars; the voice sample only
checks the result and never changes it. Calibration never changes captured audio,
`audio.min_speech_rms`, speech detection, or transcription, and it cannot learn or
fade while the daemon runs. Recalibrate after changing microphones or input gain.

After saving, setup offers the network model download only if the selected
model is absent and then reports every result from `stenographer doctor`. Quick
setup defaults that explicit download prompt to yes; the full wizard retains its
existing no default. Setup does not restart when a required capability is missing.
If configuration bytes
changed and the standard systemd user service is already active, it offers to
restart it (default: yes). It never installs, enables, or starts an inactive
service, and it never restarts a service when `STENOGRAPHER_CONFIG` selects a
custom path; in those cases it prints the command to run yourself. A successful
quick setup ends with the configured hold/toggle tryout and the applicable
foreground, start, restart, install, and journal guidance for the observed
service state.

Setup requires an interactive terminal. A normal Cancel exits 0, Ctrl-C or EOF
exits 130, non-TTY use exits 2, invalid configuration or missing required
capabilities exits 78, and write/download/probe/restart failures exit 1. Once a
configuration is saved, a later setup failure does not roll it back.

### Overlay scope and limitations

The native layer-shell backend uses the overlay layer and has strong stacking
for normal, tiled, maximized, and fullscreen application windows. Its output is
chosen by the compositor at the start of each utterance. The XWayland fallback
chooses the connected RandR monitor under the pointer, falls back to the primary
monitor, and keeps that placement until the pill hides. Focused-monitor choice
and stacking over exclusive fullscreen windows are best-effort under XWayland.
Neither backend appears over lock screens or other protected shell surfaces.

The recording pill contains exactly 18 solid spectrum bars that animate only
while recording. `feedback.spectrum_floor_dbfs` is either one manual floor shared
by all bars or the 18 fixed floors produced by setup. Each band maps through a
30 dB visual range capped at `-12` dBFS. Input at or below its floor stays on the
4 px baseline tick; input at or above its ceiling reaches full height. A calibrated
bass-noise floor therefore cannot suppress quieter speech bands, and sustained
speech never becomes a new baseline. This display-only mapping never filters
recorded audio or changes transcription. The
only other animation is a 2-second amber border pulse while the model is actively
loading; it applies to any visible pill and is timed entirely inside the helper.
The overlay has no transcript preview, raw-audio IPC, controls, GTK dependency, or
success state, and it never takes keyboard or pointer input. Every visible pill is
280×64; all labels, dots, geometry, and post-recording pill interiors remain fixed.

## CLI

| Command | Purpose |
|---|---|
| `stenographer run` | the daemon |
| `stenographer transcribe FILE [--raw]` | batch-transcribe an audio file |
| `stenographer model download` | fetch the ASR model into the local cache |
| `stenographer doctor` | capability probe with fix hints |
| `stenographer devices` | list audio input devices |
| `stenographer setup [--quick]` | configure all keys or just essentials, then guide first-use checks |
| `stenographer completion {bash,zsh,fish}` | print one native shell completion definition |

## Development

```sh
.venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration"          # unit tests (pure logic)
STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest    # real smoke suite (this machine)
```

The integration suite genuinely creates a uinput device, writes the clipboard,
plays cues, and loads the model — run it on a real session before merging.

## License

GPL-3.0-or-later.
