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

Local, offline, Wayland push-to-talk, toggle, or hybrid dictation daemon.
Press a configurable hotkey, speak, get the text at your cursor and in your
clipboard. See [BUILD.md](BUILD.md) for the standalone-binary build
instructions.

> [!NOTE]
> This `README.md` was generated with AI, but reviewed for accuracy by a human

Default hotkey: Right Ctrl in hybrid mode. Tap it to latch, or hold it, speak,
and release; plain hold-to-talk and toggle modes are optional.


<!--
DO NOT EDIT ABOVE THIS LINE.

The title and description above are user-owned and are preserved
verbatim by this project and by any automated tooling (including AI
assistants). Everything below this comment is generated / maintained
content. To change the project description, edit above this line.
-->

## Quick install

On Linux x86_64 or AArch64 with a Wayland session and a systemd user manager:

```sh
curl -fsSL https://raw.githubusercontent.com/Harrison-Blair/stenographer/main/scripts/quick-install.sh | bash -s -- --no-start
```

This downloads the latest release's prebuilt bundle, verifies it against the
release's `SHA256SUMS`, installs `~/.local/bin/stenographer`, and installs and
enables the systemd user service — no Python or build tools needed.
`--no-start` leaves the service stopped until you have configured it and
downloaded the model; drop it (and everything after `bash`) when upgrading an
existing install. Any other `scripts/install.sh` option can be passed the same
way. The bundle is built on Ubuntu 24.04, so it needs a comparably recent
glibc; on older systems build from source instead (step 2 below).

After the quick install, check the permissions in step 1, skip step 2, and
continue from step 3.

## Quick start

### 1. Check the essentials

You need Linux with a Wayland session and a systemd user manager, Python 3.12+
and the build prerequisites described in [BUILD.md](BUILD.md). Dictation also
requires:

- A PortAudio-backed microphone and the system PortAudio library.
- Read access to `/dev/input/event*`, normally through the `input` group.
- Write access to `/dev/uinput`, through a udev rule or `uinput` group.
- `wl-copy` from `wl-clipboard`, or `xclip` plus XWayland on compositors without
  the Wayland data-control protocol.

For example, add yourself to the input group with
`sudo usermod -aG input $USER`, then log out and back in. Permission setup and
package names vary by distribution; `stenographer doctor` reports what is
missing.

### 2. Install the user service

Skip this step if you used the quick install above.

```sh
git clone https://github.com/Harrison-Blair/stenographer.git
cd stenographer
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,build]"
scripts/install.sh --no-start
```

The installer builds the standalone bundle, installs
`~/.local/bin/stenographer`, and installs and enables the systemd user service.
`--no-start` leaves it stopped while you configure it.

### 3. Configure

```sh
~/.local/bin/stenographer setup --quick
```

Use `setup --quick` for normal setup or `setup` to review every setting. Both
wizards offer the bundled and valid custom sound packs, then offer the separate,
approximately 1.5 GB model download and check the microphone, clipboard, model,
and input permissions.

Configuration lives at `~/.config/stenographer/config.toml`. Hybrid mode is the
default: a tap released inside `hybrid_threshold_seconds` (default `0.5`)
latches the recording until the next press, and a press held past it stops on
release. To use plain hold-to-talk or toggle mode and hide visual feedback,
set:

```toml
[stenographer.hotkey]
mode = "toggle"

[stenographer.feedback]
overlay = false
sound_pack = "minimal-ui"
```

`stenographer setup --default` rewrites `config.toml` with the annotated
defaults without prompting, backing the previous file up first and printing
where the backup went.

### 4. Start and dictate

```sh
systemctl --user start stenographer.service
systemctl --user status stenographer.service --no-pager
```

Hold Right Ctrl, speak, then release — or tap it to latch, speak, and tap again
to stop. The transcript is pasted at the cursor and remains on the clipboard.
In `hold` mode only the held press works; in `toggle` mode press once to start
and again to stop.

## CLI

| Command | What it does |
|---|---|
| `stenographer run` | Run the daemon in the foreground. |
| `stenographer transcribe FILE [--raw]` | Transcribe an audio file; optionally skip formatting. |
| `stenographer model download` | Download the configured ASR model into the local cache. |
| `stenographer doctor` | Check required capabilities and print fixes. |
| `stenographer devices` | List audio input devices. |
| `stenographer setup [--quick \| --default]` | Configure everything, only the common settings, or write the annotated defaults without prompting. |
| `stenographer sounds [PACK]` | List, preview, or select a whole sound pack. |
| `stenographer completion {bash,zsh,fish}` | Print a native shell completion definition. |

Add `--help` to any command for its full usage.

## Sound packs

Four packs ship in a fixed order: `legacy` preserves the original cues,
followed by `warm-desk`, `soft-electronic`, and the default `minimal-ui`. Use
`stenographer sounds` for the TTY selector, `stenographer sounds --list` to see
the effective selection, or preview without saving:

```sh
stenographer sounds --preview warm-desk
stenographer sounds soft-electronic
```

The selector always changes the complete four-cue pack; there are no per-cue
overrides or downloads. A custom pack lives at
`~/.config/stenographer/sounds/<pack>/` (or beside the active custom config) and
contains `record_start.wav`, `record_stop.wav`, `delivered.wav`, and `error.wav`.
Pack names use lowercase letters, digits, and hyphens. Each cue must be a
readable, nonempty, uncompressed PCM WAV shorter than 300 ms, with one or two
channels, an 8–192 kHz sample rate, and 8/16/24/32-bit samples. Other files are
ignored, but an incomplete or invalid pack is unavailable as a unit. Restart the
daemon after selecting or editing a custom pack.

## How it works and privacy

The flow is hotkey → microphone → local English transcription → clipboard →
paste chord at the cursor. The paste chord fires only after a confirmed
clipboard copy and physical hotkey release.

The core pipeline is platform-neutral and reaches every host-specific surface
through one boundary, `stenographer.platform`: the hotkey listener, clipboard
writer, paste injector, sound-cue player, notifier, single-instance lock, user
directories, and capability probes. The Linux backend (`platform/linux/`) is
evdev for the hotkey, a `uinput` Shift+Insert chord for the paste, `wl-copy` or
`xclip` for both clipboard selections, `canberra`/`pw-play`/`paplay` for cues,
`notify-send`, an `flock` under `$XDG_RUNTIME_DIR`, and XDG paths. Hotkey
bindings use evdev `KEY_*` names on every platform.

The model download is explicit, and dictation is offline: audio, transcripts,
configuration, and device or model names never leave the machine. The daemon's
only network access is the update notice — at most one request per 24 hours,
successful or not: a single metadata-only request for the latest GitHub release
tag, showing a desktop notification when a newer version exists and pointing
back at the quick-install command above. It never downloads anything; a failed
check is silent, and the next attempt waits for the 24-hour window. Turn it off
with `update_check = false` under `[feedback]`. Logs may contain timings and
counts, but never transcript text or audio. See [AGENTS.md](AGENTS.md) for the
binding behavioral and architecture decisions.

## Service and troubleshooting

```sh
~/.local/bin/stenographer doctor
journalctl --user -u stenographer.service -f
systemctl --user restart stenographer.service
~/.local/bin/stenographer setup --quick
```

Run plain `setup` when you need all settings. Use `stenographer sounds` when you
want to audition cue packs. Sound cues and desktop error notifications are
optional and become no-ops if no supported player or `notify-send` is available.

## Requirements and limitations

Required capabilities are a cached model, a working PortAudio input, readable
evdev keyboard devices, writable `/dev/uinput`, and the clipboard command chosen
for the current compositor. Stenographer is Wayland-focused and English-only.

Only the Linux backend exists today. The core installs and imports on other
platforms (the Linux-only dependencies carry `sys_platform` markers), but
`stenographer doctor` reports every required capability as missing there and
`stenographer run` refuses to start; a Windows backend would implement the same
`platform` protocols without changing the core or the config schema.

The optional, click-through lifecycle pill is failure-safe: if neither its
native layer-shell backend nor its XWayland fallback works, dictation continues
without it. It shows exactly 18 spectrum bars while recording and an amber
breathing border while the model loads; it never receives transcript text or
raw microphone audio.

## Development

See [BUILD.md](BUILD.md) for standalone builds. From the repository venv, run:

```sh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration"
scripts/check-completions.sh
.venv/bin/python scripts/cue_audition.py --verify-packaged
.venv/bin/stenographer --help
```

The completion checker runs every supported shell available locally and reports
missing shells as skipped; CI installs and checks Bash, Zsh, and Fish.

The integration suite and real dictation are the release gate and must run in a
real graphical session, not CI or a sandbox. `tests/platform/test_core_isolation.py`
guards the boundary: it imports the whole core with evdev, fcntl, termios, and the
Wayland/X11 libraries blocked, so a Linux-only import leaking into the core fails
on any machine. CI also runs the unit suite on Windows as a portability check.

## License

GPL-3.0-or-later.
