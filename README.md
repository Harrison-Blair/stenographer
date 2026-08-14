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

Hold the hotkey (default: right-Alt), speak, release. The transcript is pasted
at your cursor and left on the clipboard.

## Requirements

- Linux with any Wayland compositor.
- Read access to `/dev/input/event*` — membership in the `input` group
  (`sudo usermod -aG input $USER`, then re-login).
- Write access to `/dev/uinput` for the paste chord (a udev rule or the
  `uinput` group).
- `wl-clipboard` (for `wl-copy`).
- A PortAudio input device (PipeWire or PulseAudio provide this).
- Optional: `pw-play` or `paplay` for the sound cues, `notify-send` for error
  notifications — both degrade to no-ops when absent.

`stenographer doctor` probes all of the above and prints an exact fix for
anything missing (exit code 78 when a required capability is absent).

Python 3.12 or newer.

## Running as a service

```sh
cp packaging/stenographer.service ~/.config/systemd/user/
systemctl --user enable --now stenographer.service
journalctl --user -u stenographer -f
```

The unit's `ExecStart` assumes the `stenographer` entry point is reachable at
`~/.local/bin/stenographer` — symlink it from your venv or edit the path.

## Configuration

`~/.config/stenographer/config.toml` is created with annotated defaults on
first run. Four sections:

| Section | Keys |
|---|---|
| `hotkey` | `binding` (evdev key/chord, default `KEY_RIGHTALT`), `device` |
| `audio` | `input_device`, `min_speech_rms`, `max_recording_seconds` |
| `asr` | `model`, `compute_type`, `beam_size`, `hotwords`, `initial_prompt`, `vad_filter`, `silence_threshold`, `idle_unload_seconds`, `cpu_threads` |
| `feedback` | `volume`, `mute` |

Note: `hotwords` require a full (non-distil) model — the default
`Systran/faster-whisper-medium.en` supports them.

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
