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

## What it is

Press a hotkey, speak, and the text appears at your cursor.

`stenographer` is a push-to-talk dictation daemon for any Wayland session. It
listens to Linux evdev keyboard events, records from the configured microphone
while the hotkey is held, transcribes locally with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), and delivers the
utterance to the focused application: the transcript is copied to both Wayland
selections with `wl-copy`, then pasted with a single Shift+Insert chord sent
through a kernel `uinput` virtual keyboard. Because injection is
display-server-independent, it works identically on wlroots compositors
(Hyprland, sway, …) and on GNOME/Mutter.

Everything is offline and English-only. Nothing is sent anywhere; the daemon
never touches the network (the model is fetched once, explicitly, with
`stenographer model download`).

This is the reauthored v2 of the project — a deliberate clean-room rewrite of
the original ~9k-line tool down to ~2k lines. The design record lives in
[docs/reauthor.md](docs/reauthor.md).

## Quick start

```sh
git clone https://github.com/Harrison-Blair/stenographer
cd stenographer
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/stenographer model download   # ~1.5 GB, once
.venv/bin/stenographer doctor           # checks permissions, mic, model
.venv/bin/stenographer run              # foreground daemon
```

Hold the hotkey (default: right-Ctrl), speak, release. The transcript is pasted
at your cursor and left on the clipboard.

By default a small, click-through pill shows only the fixed lifecycle states
Recording, Loading model, Transcribing, Delivering, and Error. It receives no
transcript, audio, model/device names, configuration values, or detailed error
text. Set `feedback.overlay = false` to disable just this visual surface; sound
cues, notifications, and dictation continue unchanged.

## Requirements

- Linux with any Wayland compositor.
- Read access to `/dev/input/event*` — membership in the `input` group
  (`sudo usermod -aG input $USER`, then re-login).
- Write access to `/dev/uinput` for the paste chord (a udev rule or the
  `uinput` group).
- `wl-clipboard` (for `wl-copy`).
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
Equivalent manual steps:

```sh
cp packaging/stenographer.service ~/.config/systemd/user/
systemctl --user enable --now stenographer.service
journalctl --user -u stenographer -f
```

The unit's `ExecStart` points at `~/.local/share/stenographer/stenographer`;
edit the path if you run from a venv instead.

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
first run. Four sections:

| Section | Keys |
|---|---|
| `hotkey` | `binding` (evdev key/chord, default `KEY_RIGHTCTRL`), `device` |
| `audio` | `input_device`, `min_speech_rms`, `max_recording_seconds` |
| `asr` | `model`, `compute_type`, `beam_size`, `hotwords`, `initial_prompt`, `vad_filter`, `silence_threshold`, `idle_unload_seconds`, `cpu_threads` |
| `feedback` | `volume`, `mute`, `overlay` (default `true`) |

Note: `hotwords` require a full (non-distil) model — the default
`Systran/faster-whisper-medium.en` supports them.

### Overlay scope and limitations

The native layer-shell backend uses the overlay layer and has strong stacking
for normal, tiled, maximized, and fullscreen application windows. Its output is
chosen by the compositor at the start of each utterance. The XWayland fallback
chooses the connected RandR monitor under the pointer, falls back to the primary
monitor, and keeps that placement until the pill hides. Focused-monitor choice
and stacking over exclusive fullscreen windows are best-effort under XWayland.
Neither backend appears over lock screens or other protected shell surfaces.

The pill is status only: it has no transcript preview, live audio/FFT handling,
controls, animation, or success state, and it never takes keyboard or pointer
input.

## CLI

| Command | Purpose |
|---|---|
| `stenographer run` | the daemon |
| `stenographer transcribe FILE [--raw]` | batch-transcribe an audio file |
| `stenographer model download` | fetch the ASR model into the local cache |
| `stenographer doctor` | capability probe with fix hints |
| `stenographer devices` | list audio input devices |

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
