<p align="center">
  <img src="src/stenographer/assets/icons/stenographer.png" width="128" alt="stenographer icon" />
</p>



# stenographer
> 1. A writer of shorthand
> 
> 2. A person employed chiefly to take and transcribe dictation
>
>    *\- [Merriam Webster](https://www.merriam-webster.com/dictionary/stenographer)*

[![release](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Harrison-Blair/stenographer/badges/release.json)](https://github.com/Harrison-Blair/stenographer/releases)

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

## Quick start

For a released Linux x86_64 build:

```sh
curl -fsSL https://github.com/Harrison-Blair/stenographer/releases/latest/download/install.sh | bash
~/.local/bin/stenographer doctor
```

The installer verifies the release checksum, offers to install system
dependencies and add you to the `input` group, asks for a hotkey, microphone,
and ASR model, then installs and enables the systemd user service. If it adds
you to `input`, log out and back in before expecting the hotkey to work.

Follow the service log with:

```sh
journalctl --user -u stenographer.service -f
```

## What it is

`stenographer` listens to Linux evdev keyboard events, records from the
configured input device, transcribes locally with faster-whisper, and delivers
the completed utterance to the focused Wayland application. The default output
path copies the text to both Wayland selections and sends one `Shift+Insert`
chord with `wtype`.

Word-level decoding runs while recording. The GTK layer-shell HUD displays an
append-only stable transcript prefix, a fainter revisable tail, and a live
microphone spectrum. It does not send partial text to the application or
clipboard: final delivery happens once, after the final decode. When the GTK
overlay is unavailable, status falls back to `notify-send`; transcript previews
are only shown in the GTK HUD.

The generated default configuration uses right-Alt in push-to-talk mode and an
English-only model. The release installer asks for a hotkey (suggesting
right-Ctrl) and lets you choose from English and multilingual models.

## Hotkey behavior

Set `hotkey.trigger_mode` to one of:

- `ptt` (default): hold the hotkey to record and release it to transcribe.
- `toggle`: press once to start recording and press again to stop.
- `hybrid`: hold for at least `hotkey.toggle_threshold_seconds` for
  push-to-talk. To latch toggle recording, double-tap within
  `hotkey.double_tap_window_seconds`; a lone short tap is discarded.

While the main hotkey is held, press `hotkey.cancel_binding` (Escape by
default) to discard the active recording and cancel queued or in-flight
transcription. Set the cancel binding to `""` to disable it.

## Requirements

- Linux with a Wayland compositor on which `wtype` can inject keystrokes.
- Membership in the `input` group, or a uaccess rule for the keyboard
  device, so the daemon can read `/dev/input/event*`.
- A working PortAudio input device, normally provided through PipeWire or
  PulseAudio.
- System packages:

  | Capability | Debian / Ubuntu | Fedora | Purpose |
  |---|---|---|---|
  | `wtype` | `wtype` | `wtype` | Final typing or paste chord |
  | `wl-copy` | `wl-clipboard` | `wl-clipboard` | Clipboard and default paste transport |
  | `pw-play` or `paplay` | `pipewire-audio` or `pulseaudio-utils` | `pipewire-utils` or `pulseaudio-utils` | Audio cues |
  | `notify-send` | `libnotify-bin` | `libnotify` | Fallback status notifications |
  | libevdev | `libevdev1` | `libevdev` | Global hotkey |
  | PortAudio | `libportaudio2` | `portaudio` | Microphone capture |
  | GTK4 layer shell | `libgtk-4-1`, `libgtk4-layer-shell0`, `gir1.2-freedesktop`, `gir1.2-gtk4layershell-1.0` | `gobject-introspection`, `gtk4`, `gtk4-layer-shell` | HUD and transcript preview |

The audio cues, notifications, and GTK HUD degrade independently when their
optional runtime is absent. The default `clipboard_paste` output requires both
`wl-copy` and `wtype`; without `wtype`, the transcript remains recoverable on
the clipboard but is not pasted.

Python 3.14 or newer is required for source, wheel, and editable installs. The
prebuilt onedir release includes Python, but still needs the system CLIs and
libraries above.

## Install

### Quick install (prebuilt binary)

The release installer supports apt, dnf, and pacman systems. It installs to
`~/.local/share/stenographer/` and links
`~/.local/bin/stenographer`.

```sh
curl -fsSL https://github.com/Harrison-Blair/stenographer/releases/latest/download/install.sh | bash
```

Prompts read directly from the terminal even when the script is piped to
`bash`. To inspect it first, download `install.sh` from
[GitHub Releases](https://github.com/Harrison-Blair/stenographer/releases),
read it, and run it locally. Local-script options are:

```sh
./install.sh --version X.Y.Z   # install a specific release
./install.sh --yes             # accept all prompts (non-interactive)
./install.sh --no-deps         # skip the system-package step
```

`STENOGRAPHER_REPO=OWNER/REPO` and `STENOGRAPHER_VERSION=X.Y.Z` provide
equivalent environment overrides. If the model download is skipped or fails,
the installer enables but does not start the service; download the model and
run `stenographer start`.

### From source

Install the runtime packages above plus the compiler, GObject-introspection,
Cairo, and libevdev development headers required to build PyGObject and evdev.
On Debian/Ubuntu:

```sh
sudo apt install gcc pkg-config libcairo2-dev libgirepository-2.0-dev \
  libevdev-dev gir1.2-freedesktop gir1.2-gtk-4.0
```

Then build and install the PyInstaller onedir bundle:

```sh
git clone https://github.com/Harrison-Blair/stenographer.git
cd stenographer
python3.14 -m venv .venv
.venv/bin/pip install -e ".[dev,build]"
scripts/build.sh
scripts/install.sh
```

`scripts/install.sh` copies `dist/stenographer/` to
`~/.local/share/stenographer/`, installs bash completion, writes the systemd
user unit, and enables and starts it. It only invokes the build itself when
`dist/stenographer/stenographer` is absent, so run `scripts/build.sh` first
when reinstalling changed source.

Useful local-installer options:

```sh
scripts/install.sh --no-enable
scripts/install.sh --no-start
scripts/install.sh --install-dir /absolute/path
```

Both `--no-enable` and `--no-start` install the unit without enabling or
starting it. See [BUILD.md](BUILD.md) for standalone build and manual unpacking
details.

For development, the editable install created above can be run directly:

```sh
.venv/bin/stenographer doctor
.venv/bin/stenographer run
```

An editable or locally built wheel install provides the `stenographer`
console script, but does not install completion or a systemd unit. Use
`stenographer enable` if you want the installed console script to create its
user unit.

### Shell completion (bash)

`scripts/install.sh` installs bash tab-completion automatically (to
`~/.local/share/bash-completion/completions/stenographer`, loaded
lazily by the `bash-completion` package). The release installer and
wheel/editable installs do not set it up. With `argcomplete` installed, add
this to `~/.bashrc`:

```sh
eval "$(register-python-argcomplete stenographer)"
```

## First-run setup

```sh
stenographer devices             # list input device names and indices
stenographer model download      # fetch the model selected in the config
stenographer doctor              # probe the resolved configuration and runtime
```

Model size depends on `asr.model`. `doctor` creates the default configuration
if none exists, reports each required or optional capability, and exits 78
when `input` group membership, a microphone, or the configured ASR model is
missing.

## Run

```sh
stenographer run                 # foreground daemon, Ctrl-C to stop
stenographer dictate             # one-shot: arm, dictate, exit
stenographer transcribe FILE     # batch: print formatted transcript to stdout (default)
stenographer transcribe FILE --raw # batch: print the raw, unformatted transcript verbatim
stenographer devices             # list audio input devices
stenographer model download      # fetch the ASR model
stenographer bench FILE_OR_DIR   # benchmark a model/beam/compute matrix
stenographer bench --record 10 --save sample.wav
stenographer update              # update a prebuilt onedir installation
stenographer doctor              # print capabilities + resolved config
stenographer --version

# systemd user unit management
stenographer enable [--no-start] # install + enable the unit, then start it
stenographer start               # start an already-installed unit
stenographer stop                # stop the daemon (systemd or foreground)
stenographer status              # show daemon state, uptime, and systemd preview
stenographer disable             # stop + disable the unit
```

`-c/--config PATH` is a global option and must precede the subcommand, for
example `stenographer --config ./config.toml doctor`. Run
`stenographer SUBCOMMAND --help` for subcommand-specific options. The default
benchmark matrix may load or download several large models.

`stenographer run` holds a single-instance `fcntl.flock` on
`$XDG_RUNTIME_DIR/stenographer.lock`; a second `run` exits 1 with
`another instance is already running.`

## Updating

`stenographer update` checks GitHub Releases for a newer version of
the onedir binary, downloads the matching tarball, verifies its
SHA-256, and replaces the running install in place. If the daemon
is running under systemd, it is stopped before the swap and started
afterwards.

```sh
stenographer update              # check, prompt, install, restart
stenographer update --check      # only print whether an update is available
stenographer update --yes        # non-interactive
stenographer update --prerelease # include pre-release tags
stenographer update --no-restart # leave the daemon stopped after the swap
stenographer update --repo OWNER/REPO
```

`update` only self-updates the onedir binary built by `scripts/build.sh`.
A wheel, editable, pip, or pipx install is not replaced; upgrade it using the
same tool and package source that installed it. Configure the target repo / channel in
`~/.config/stenographer/config.toml` under `[stenographer.update]`.

## Configure

Resolution order:

1. `--config PATH`, which sets `$STENOGRAPHER_CONFIG` for the process.
2. `$STENOGRAPHER_CONFIG`, if set.
3. `$XDG_CONFIG_HOME/stenographer/config.toml` (default
   `~/.config/stenographer/config.toml`).

If the resolved path does not exist, the first configuration-aware command
writes the default file there, then loads it. The file is loaded once per
process; restart the daemon to pick up edits. Bad values cause exit code 78
(`EX_CONFIG`) with a precise file, key, and validation message.

The generated defaults are:

```toml
# stenographer configuration

[stenographer]

# Hotkey
hotkey.binding = "KEY_RIGHTALT"
hotkey.toggle_threshold_seconds = 0.5
hotkey.double_tap_window_seconds = 0.35
hotkey.cancel_binding = "KEY_ESC"
hotkey.device = ""
hotkey.trigger_mode = "ptt"

# Audio capture
audio.sample_rate = 16000
audio.frames_per_buffer = 1024
audio.input_device = ""
audio.max_recording_seconds = 600

# ASR
asr.model = "Systran/faster-whisper-medium.en"
asr.language = "en"
asr.beam_size = 5
asr.compute_type = "int8"
asr.silence_threshold = 0.6
asr.mode = "lazy"
asr.idle_unload_seconds = 300
# hotwords: proper nouns / jargon to bias recognition toward, e.g. "wtype, Wayland"
asr.hotwords = ""
# initial_prompt: free-text context prepended to decoding (style/domain hints)
asr.initial_prompt = ""

# Audio feedback
feedback.volume = 0.6
feedback.mute = false

# Bottom-center Wayland spectrum overlay
visualizer.enabled = true
visualizer.frequency_bands = 16
visualizer.min_frequency = 80.0
visualizer.max_frequency = 8000.0
visualizer.margin_bottom = 32

# Text output
output.injection_method = "clipboard_paste"
output.append_trailing_space = true
output.max_chars = 4096

# Clipboard
clipboard.enabled = true

# Incremental word-level decoding (always enabled).
# min_chunk_seconds / beam_size are the CPU knobs if re-decodes lag.
incremental.min_chunk_seconds = 1.0
incremental.agreement_n = 2
incremental.beam_size = null
incremental.max_buffer_seconds = 20.0

# Formatting heuristics (applies to all output modes)
formatting.paragraph_pause_seconds = 0.0
formatting.capitalize_sentences = true
formatting.normalize_spacing = true

# Update
update.repo = "Harrison-Blair/stenographer"
update.channel = "stable"
update.base_url = "https://api.github.com"
update.asset_pattern = "stenographer-{version}-linux-x86_64.tar.gz"
update.timeout_seconds = 60

[stenographer.feedback.cues]
ptt_on = ""
ptt_off = ""
toggle_on = ""
toggle_off = ""
cancel = ""
discard = ""
error = ""
segment = ""
transcribe_done = ""
model_loading = ""
model_ready = ""
```

An empty device or optional string selects the automatic/default behavior.
For compatibility, the loader also accepts a bare `null` for optional values,
although standard TOML represents these defaults as empty strings.

`asr.mode = "lazy"` loads the model on first use and unloads it after
`asr.idle_unload_seconds`; `0` disables idle unloading. Set the mode to
`"eager"` to load at daemon startup. `incremental.beam_size = null` inherits
`asr.beam_size`.

`output.injection_method` must be `"type"` or `"clipboard_paste"`. Paste mode
requires `clipboard.enabled = true`; type mode can leave a convenience copy on
the regular clipboard when clipboard support is enabled. In type mode,
`output.max_chars` caps what is typed while the full transcript remains on the
clipboard; in paste mode it caps the pasted and copied text. The pre-0.9.2
values `"text"` and `"paste"` are accepted with a deprecation warning and
mapped to their current names.

`asr.silence_threshold` drops segments that faster-whisper classifies as
probable silence from both batch and incremental decoding. If a final
incremental decode fails, already committed preview text is still delivered.
Legacy `streaming.*` tuning keys are migrated to `incremental.*` with warnings;
incremental decoding itself is always enabled.

See [`src/stenographer/config.py`](src/stenographer/config.py) for validation
ranges and the complete schema.

## Run under systemd

The quick installer and `scripts/install.sh` both set up the systemd
user unit for you. To manage it yourself, the binary can install and
control its own unit — no need to hand-edit unit files:

```sh
stenographer enable             # write the unit, enable it, and start now
stenographer enable --no-start  # write + enable, but don't start yet
stenographer start              # start an already-installed unit
stenographer stop               # stop the daemon
stenographer status             # inspect daemon and systemd status
stenographer disable            # stop + disable the unit
journalctl --user -u stenographer.service -f
```

`enable` writes `~/.config/systemd/user/stenographer.service` with an
`ExecStart` pointing at the running binary (backing up any existing unit
to `…stenographer.service.bak`), runs `daemon-reload`, then enables it.

`status` reports whether the daemon is running under systemd or in the
foreground, along with its PID, uptime, unit-file path, enabled state, runtime
lock, and systemd active state. It finishes with a plain-text
`systemctl --user status` preview containing up to 10 recent journal lines.
The command exits 0 only when it confirms a live daemon; stopped or
indeterminate states exit 1. Recent journal output can contain application
diagnostics and, when debug transcript logging is enabled, dictated text.

If you'd rather wire it up by hand — e.g. against a binary unpacked to a
non-default location like `/opt/` — the raw unit template is at
`packaging/stenographer.service.in`. Copy it to
`~/.config/systemd/user/stenographer.service` (substituting `%h` with
your home directory and adjusting `ExecStart` to your binary path), then
`systemctl --user enable --now stenographer.service`.

`Restart=on-failure`; binds to `graphical-session.target`. The daemon
is foreground; systemd handles daemonization.

## Logging

Logs go to stderr and a rotating file at
`$XDG_STATE_HOME/stenographer/stenographer.log` (default
`~/.local/state/stenographer/stenographer.log`). Override the level
with `STENOGRAPHER_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR`. INFO logs transcript
lengths; full transcript text is only logged at DEBUG.

## License

GPL-3.0-or-later. See `LICENSE`.
