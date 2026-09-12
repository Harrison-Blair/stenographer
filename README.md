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

[Release notes](CHANGELOG.md)

Local, offline, Wayland push-to-talk, toggle, or hybrid dictation daemon.
Press a configurable hotkey, speak, get the text at your cursor and in your
clipboard. See [BUILD.md](BUILD.md) for the standalone-binary build
instructions.

> [!NOTE]
> This `README.md` was generated with AI, but reviewed for accuracy by a human

Default hotkey: Right Ctrl in hybrid mode. Tap it to latch, or hold it, speak,
and release; plain hold-to-talk and toggle modes are optional. Press Escape at
any point during an utterance to cancel it; nothing is transcribed or pasted.


<!--
DO NOT EDIT ABOVE THIS LINE.

The title and description above are user-owned and are preserved
verbatim by this project and by any automated tooling (including AI
assistants). Everything below this comment is generated / maintained
content. To change the project description, edit above this line.
-->

## Quick install

On Linux x86_64 or AArch64 with Wayland and a systemd user manager:

```sh
curl -fsSL https://raw.githubusercontent.com/Harrison-Blair/stenographer/main/scripts/quick-install.sh | bash -s -- --no-start
```

This verifies and installs the latest prebuilt bundle and user service. It
leaves the service stopped so you can configure it and download the model. No
Python or build tools are needed. For another architecture or a local build,
see [docs/building.md](docs/building.md).

## Requirements

You need Linux, Wayland, a systemd user manager, and:

- A PortAudio-backed microphone and the system PortAudio library.
- Read access to `/dev/input/event*`, normally through the `input` group.
- Write access to `/dev/uinput`, through a udev rule or `uinput` group.
- `wl-copy` from `wl-clipboard` (or `xclip` plus XWayland).

Stenographer is English-focused. Run `stenographer doctor` for missing
capabilities and fixes; for example, input access may require:

```sh
sudo usermod -aG input "$USER"
```

## Install from source

Use this when a prebuilt bundle is unavailable:

```sh
git clone https://github.com/Harrison-Blair/stenographer.git
cd stenographer
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,build]"
scripts/install.sh --no-start
```

## Configure and start

```sh
~/.local/bin/stenographer setup --quick
systemctl --user start stenographer.service
```

The wizard checks your microphone, clipboard, model, and input permissions, and
offers the separate large-v3-turbo model download (about 1.6 GB). Use plain
`setup` to review every setting, or run `stenographer model download` later.

For clearer recognition, first run `stenographer devices` and select the
intended microphone. Keep it about 10–20 cm from your mouth, aim it slightly
off-axis, and raise the input level only until normal speech is clear without
clipping. A close wired headset often beats a distant microphone. See the
[microphone and normalization guidance](docs/usage.md#improve-microphone-capture)
for troubleshooting steps.

Configuration lives at `~/.config/stenographer/config.toml`. For example:

```toml
[stenographer.hotkey]
mode = "toggle"       # or "hold"
cancel_binding = "KEY_ESC"  # "" disables cancellation

[stenographer.feedback]
overlay = false
sound_pack = "minimal-ui"
```

CLI saves preserve comments and settings they do not know about. Restart the
service after editing it with `systemctl --user restart stenographer.service`.

## Dictate

Right Ctrl is the default hybrid binding:

- Hold it, speak, and release for push-to-talk.
- Tap it, speak, and tap again to stop a latched recording.
- Press Escape while recording or delivering to discard the audio and
  transcript. Nothing is pasted.

Otherwise the transcript is pasted at your cursor and remains on the clipboard.
Use `mode = "hold"` for push-to-talk only or `mode = "toggle"` for press/press.
Set `binding` to any `KEY_*` name to rebind. A fresh config picks the key from
the host, so Windows starts from Right Alt rather than Right Ctrl; rebind it if
you type with AltGr.

## Common commands

- `stenographer doctor` — check capabilities and print fixes.
- `stenographer devices` — list audio input devices.
- `stenographer sounds [PACK]` — list, preview, or select sound feedback.
- `stenographer stats` — view, export, or delete local numeric statistics.
- `stenographer transcribe FILE [--raw] [--refine]` — transcribe an audio file.
- `stenographer model download [--asr|--refine]` — fetch a model explicitly.
- `stenographer run` — run the daemon in the foreground.

Add `--help` to any command for full usage. See the [user guide](docs/usage.md)
for sound packs, statistics, and configuration examples.

## Troubleshooting

```sh
stenographer doctor
journalctl --user -u stenographer.service -f
systemctl --user restart stenographer.service
```

## Privacy and more

The model download is explicit and dictation runs locally. Audio, transcripts,
configuration, and device or model names stay on your machine. Logs never
contain transcript text or audio. The only network request that leaves your
machine is an optional, metadata-only release check; disable it in
`[stenographer.feedback]` with `update_check = false`.

A [refine](docs/refine.md) pass, on by default, cleans filler words and
self-corrections out of each transcript through a local Ollama model
(`gemma4:e2b` by default) on `127.0.0.1`, so the text still never leaves your
machine. Turn it off or point it elsewhere in `[stenographer.refine]`; a
non-loopback host sends transcripts there over the network.

Read the [user guide](docs/usage.md) for privacy settings and more examples.

## Development

See [docs/building.md](docs/building.md) for standalone builds and contributor
checks. See [docs/architecture.md](docs/architecture.md) for code boundaries.
The [transcription-quality study](docs/transcription-experiments.md) contains
public-audio benchmark runners, measured results, and a microphone experiment
catalog. These diagnostics do not change the installed dictation settings.

## License

GPL-3.0-or-later.
