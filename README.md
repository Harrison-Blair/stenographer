<p align="center">
  <img src="src/stenographer/assets/icons/stenographer.png" width="128" alt="stenographer icon" />
</p>

# stenographer
> *1. A writer of shorthand 2. A person employed chiefly to take and transcribe dictation [Merriam Webster](https://www.merriam-webster.com/dictionary/stenographer)*

Local, offline, Wayland push-to-talk / toggle dictation daemon. Press a
configurable hotkey, speak, get the text at your cursor and in your
clipboard. See [BUILD.md](BUILD.md) for the standalone-binary build
instructions.

> [!NOTE]
> This `README.md` was generated with AI, but reviewed for accuracy by a human

See [Install](#install) for the install steps and a [Quick start](#quick-start) for the post-install flow. Default hotkey: right-Ctrl (short press <0.5 s toggles recording; long press ≥0.5 s is push-to-talk — see `spec/01-hotkey.md`).


<!--
DO NOT EDIT ABOVE THIS LINE.

The title and description above are user-owned and are preserved
verbatim by this project and by any automated tooling (including AI
assistants). Everything below this comment is generated / maintained
content. To change the project description, edit above this line.
-->

[![release](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Harrison-Blair/stenographer/badges/release.json)](https://github.com/Harrison-Blair/stenographer/releases)

## Quick start

```sh
# system deps (Debian/Ubuntu names; adjust for your distro)
sudo apt install wtype wl-clipboard pipewire-audio libevdev1 libportaudio2
sudo usermod -aG input $USER   # log out / back in

git clone … && cd stenographer

# one-time build env (needed by scripts/install.sh's internal build step)
python3 -m venv .venv && .venv/bin/pip install -e ".[build]"

# build, install to ~/.local/share/stenographer/, symlink into
# ~/.local/bin/stenographer, enable + start the systemd user unit
scripts/install.sh

# one-time: fetch the ASR model
stenographer model download

# verify everything is wired up
stenographer doctor
```

The daemon is now running under systemd. To watch it:

```sh
journalctl --user -u stenographer.service -f
```

## What it is

`stenographer` is a Wayland-only, local-only push-to-talk / toggle
dictation daemon. Press a single configurable global hotkey, speak, and
the recognised text is typed at the cursor and copied to the Wayland
clipboard. A short audio cue confirms that recording has started and
stopped. One keybinding arbitrates both modes: a press of `0.5` s or
longer is push-to-talk, a shorter press is toggle. Offline, English
only, GPL-3.0-or-later.

## Requirements

- A Wayland session with a compositor that accepts
  `zwp-input-method-protocol-unstable-v1` (wlroots, Hyprland, Sway,
  KWin, Mutter).
- Membership in the `input` group, or a uaccess rule for the keyboard
  device, so the daemon can read `/dev/input/event*`.
- A running PipeWire or PulseAudio session.
- System packages:

  | Binary / capability | Debian / Ubuntu     | Fedora              |
  |---------------------|---------------------|---------------------|
  | `wtype`             | `wtype`             | `wtype`             |
  | `wl-copy`           | `wl-clipboard`      | `wl-clipboard`      |
  | `pw-play` (or `paplay`) | `pipewire-utils` / `pulseaudio-utils` | same |
  | `libevdev` runtime  | `libevdev1`         | `libevdev`          | (also `libevdev-dev` / `libevdev-devel` headers, required at install time to build the `evdev` wheel on Python 3.14) |
  | `libportaudio`      | `libportaudio2`     | `portaudio`         | (required by `sounddevice`; bundled in the `sounddevice` wheel on most distros, but a system dep for the PyInstaller binary) |

- Python ≥ 3.14 (pinned in `.python-version`).

## Install

The canonical single-user install is the onedir binary installed by
`scripts/install.sh` from a local source tree. It builds the binary,
copies it to `~/.local/share/stenographer/`, symlinks the launcher
into `~/.local/bin/stenographer`, and installs + enables the systemd
user unit (see `spec/10-packaging.md`).

```sh
# prereq: the system packages listed in Requirements above
python3 -m venv .venv && .venv/bin/pip install -e ".[build]"
scripts/install.sh             # full install + systemd enable+start
scripts/install.sh --no-start  # install the unit but don't start it
```

`scripts/install.sh` warns if `~/.local/bin` is not on your `PATH` and
prints the one-line `export PATH=…` for bash / zsh / fish. The systemd
user unit starts the daemon automatically.

### Alternatives

```sh
pipx install stenographer        # isolated env, no systemd integration
pip install --user stenographer  # in ~/.local
```

These install from PyPI via the `[project.scripts]` entry point; they
do not register a systemd unit. Run the daemon interactively with
`stenographer run`, or wire it up manually (see
[Run under systemd](#run-under-systemd)).

If you don't want a `pip install` of any kind, download a prebuilt
`stenographer-VERSION-linux-x86_64.tar.gz` from the GitHub Releases,
verify its SHA-256, and unpack it under `/opt/` (or wherever). See
`BUILD.md` for the full procedure.

### Shell completion (bash)

`scripts/install.sh` installs bash tab-completion automatically (to
`~/.local/share/bash-completion/completions/stenographer`, loaded
lazily by the `bash-completion` package). For pip/pipx installs,
add this to `~/.bashrc` instead:

```sh
eval "$(register-python-argcomplete stenographer)"
```

## First-run setup

```sh
stenographer model download      # one-time: fetch the ASR model (~3 GB)
stenographer doctor              # verify wtype / wl-copy / pw-play / input / mic / model
```

`doctor` prints the resolved config and a yes/no line for each
capability. It exits 78 if the hotkey, mic, or ASR model is missing —
fix what it lists, then re-run.

## Run

```sh
stenographer run                 # foreground daemon, Ctrl-C to stop
stenographer dictate             # one-shot: arm, dictate, exit
stenographer transcribe FILE     # batch: print transcript to stdout
stenographer model download      # fetch the ASR model
stenographer update [--check]    # self-update from GitHub Releases
stenographer doctor              # print capabilities + resolved config
stenographer --version
```

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
stenographer update --prerelease # include pre-release tags (e.g. v0.7.0-rc.1)
stenographer update --no-restart # leave the daemon stopped after the swap
```

`update` only self-updates the onedir binary built by `scripts/build.sh`.
A `pipx` / `pip install --user` install is not replaced; run
`pipx upgrade stenographer` or `pip install --upgrade stenographer`
instead. Configure the target repo / channel in
`~/.config/stenographer/config.toml` under `[stenographer.update]`.

## Configure

Resolution order:

1. `$STENOGRAPHER_CONFIG` (absolute path), if set and readable.
2. `$XDG_CONFIG_HOME/stenographer/config.toml` (default
   `~/.config/stenographer/config.toml`).

If neither exists, the daemon writes a default config to (2) on first
start, then loads it. The file is loaded once at startup; restart the
daemon to pick up edits. Bad values cause exit code 78
(`EX_CONFIG`) with a precise file / key / range message.

The keys most users will want to touch:

```toml
[stenographer]

# Hotkey: an evdev key name, or a `+`-separated chord.
hotkey.binding                       = "KEY_RIGHTCTRL"
hotkey.toggle_threshold_seconds      = 0.5     # >= 0.5s => PTT, < 0.5s => toggle
hotkey.device                        = ""      # "" => auto-detect first keyboard

# Audio capture
audio.input_device                   = ""      # "" => sounddevice default

# ASR
asr.model                            = "Systran/faster-whisper-large-v3"
asr.compute_type                     = "int8"             # opt into "int8_float16" on CPUs with float16 hardware

# Audio feedback
feedback.volume                      = 0.6     # 0.0..1.0
feedback.mute                        = false

# Clipboard
clipboard.enabled                    = true
```

See `spec/07-configuration.md` for the full schema and validation rules.

## Run under systemd

`scripts/install.sh` handles the full systemd setup by default (see
[Install](#install)). This section is for users who want to install
the unit manually — e.g. against a binary that was unpacked to a
non-default location like `/opt/`, or who want to skip
`scripts/install.sh` and wire up an existing onedir binary by hand.
`scripts/install.sh` builds the binary, installs it to
`~/.local/share/stenographer/`, symlinks the launcher into
`~/.local/bin/`, and installs + enables the systemd user unit. Run
with `--no-enable` to skip the enable step, or `--no-start` to leave
the daemon stopped.

```sh
scripts/install.sh              # full install
scripts/install.sh --no-start   # install unit but don't start
stenographer run                # or start manually (if --no-start used)
journalctl --user -u stenographer.service -f
```

The raw unit template is at `packaging/stenographer.service.in`. To
manually install it, copy it to
`~/.config/systemd/user/stenographer.service` (substituting `%h` with
your home directory), then `systemctl --user enable --now
stenographer.service`.

`Restart=on-failure`; binds to `graphical-session.target`. The daemon
is foreground; systemd handles daemonization.

## Logging

stderr, plus a tee'd file at
`$XDG_STATE_HOME/stenographer/stenographer.log` (default
`~/.local/state/stenographer/stenographer.log`). Override the level
with `STENOGRAPHER_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR`.

## License

GPL-3.0-or-later. See `LICENSE`.
