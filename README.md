<p align="center">
  <img src="src/stenographer/assets/icons/stenographer.png" width="128" alt="stenographer icon" />
</p>

# stenographer
> 1. a writer of shorthand 2. a person employed chiefly to take and transcribe dictation [Webster](https://www.merriam-webster.com/dictionary/stenographer)

Local, offline, Wayland push-to-talk / toggle dictation daemon. Press a
configurable hotkey, speak, get the text at your cursor and in your
clipboard. See [BUILD.md](BUILD.md) for the standalone-binary build
instructions.

## Quick start

```sh
# system deps (Debian/Ubuntu names; adjust for your distro)
sudo apt install wtype wl-clipboard pipewire-audio libevdev1 libportaudio2
sudo usermod -aG input $USER   # log out / back in

# build
git clone … && cd stenographer
python3 -m venv .venv && .venv/bin/pip install -e ".[build]"
scripts/build.sh

# one-command install: build + install + systemd (skip build step above)
scripts/install.sh

# download the ASR model
./dist/stenographer/stenographer model download

# check everything is wired up
./dist/stenographer/stenographer doctor

# run
./dist/stenographer/stenographer run
```

Default hotkey: right-Ctrl. Short press (<0.5s) toggles recording; long
press (≥0.5s) is push-to-talk. See `spec/01-hotkey.md` for the full
hybrid-trigger state machine.


<!--
DO NOT EDIT ABOVE THIS LINE.

The title and description above are user-owned and are preserved
verbatim by this project and by any automated tooling (including AI
assistants). Everything below this comment is generated / maintained
content. To change the project description, edit above this line.
-->

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

Three options, in order of preference:

```sh
pipx install stenographer        # recommended: isolated environment
pip install --user stenographer  # alternative: in ~/.local
```

Or, if you do not want a `pip install` at all, use the standalone
PyInstaller `--onedir` binary at `dist/stenographer/stenographer`
(canonical single-user install per `spec/10-packaging.md`). See
`BUILD.md` for the build / runtime-system-package requirements.

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

`scripts/install.sh` handles the full systemd setup by default: it
builds the binary, installs it to `~/.local/share/stenographer/`,
symlinks the launcher into `~/.local/bin/`, and installs + enables the
systemd user unit. Run with `--no-enable` to skip the enable step, or
`--no-start` to leave the daemon stopped.

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
