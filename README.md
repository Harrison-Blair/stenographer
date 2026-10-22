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

Default hotkeys: Right Ctrl selects the Agent profile; Right Alt selects
General cleanup. Both use hybrid mode: tap to latch, or hold, speak,
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
- `wl-copy` from `wl-clipboard` (or `xclip` plus XWayland). `wl-paste`, also
  from `wl-clipboard`, lets the daemon restore your previous clipboard item.

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
offers the separate ASR model download. The default is
`deepdml/faster-whisper-large-v3-turbo-ct2`, selected from the [CPU model and
context screen (2026-10-20)](docs/transcription-experiments.md#cpu-model-and-context-screen-2026-10-20).
Dictation, Live, and Files use the same ASR settings. An existing explicit
`stenographer.asr.model` value stays unchanged. Use plain `setup` to review
every setting, or run `stenographer model download` later.

For clearer recognition, first run `stenographer devices` and select the
intended microphone. Keep it about 10–20 cm from your mouth, aim it slightly
off-axis, and raise the input level only until normal speech is clear without
clipping. A close wired headset often beats a distant microphone. See the
[microphone and normalization guidance](docs/usage.md#improve-microphone-capture)
for troubleshooting steps.

Configuration lives at `~/.config/stenographer/config.toml`. For example:

```toml
[stenographer.hotkey]
binding = "KEY_RIGHTCTRL"          # Agent
general_binding = "KEY_RIGHTALT"  # General
mode = "toggle"       # or "hold"
cancel_binding = "KEY_ESC"  # "" disables cancellation

[stenographer.feedback]
overlay = false
sound_pack = "minimal-ui"

[stenographer.delivery]
copy_original = true      # Agent only
restore_clipboard = true
restore_delay_ms = 500    # 0 to 60000
```

CLI saves preserve comments and settings they do not know about. Restart the
service after editing it with `systemctl --user restart stenographer.service`.

## Dictate

Right Ctrl selects Agent, the universal default for agent-directed dictation.
Right Alt selects General, which retains the original transcript-cleanup
behavior. Both bindings share the configured mode:

- Hold it, speak, and release for push-to-talk.
- Tap it, speak, and tap again to stop a latched recording.
- Press Escape while recording or delivering to discard the audio and
  transcript. Nothing is pasted.

Otherwise the transcript is pasted at your cursor. About half a second later
your previous clipboard item is back on the clipboard. When Agent rewrites the
text, the unrefined transcript is copied just before the rewrite, so a
clipboard history keeps both. See
[Keep your clipboard](docs/usage.md#keep-your-clipboard).
Use `mode = "hold"` for push-to-talk only or `mode = "toggle"` for press/press.
Set `binding` (Agent) or `general_binding` to any `KEY_*` chord to rebind it.
Agent, General, and cancel chords may not be equal or subsets of one another.

## Common commands

- `stenographer` — open the terminal hub when stdin and stdout are terminals;
  otherwise show help. Live shows REC, MIC, and SYSTEM panels plus a sidebar
  card with the model, compute type, and system status. Config shows a group
  selector beside compact key/value rows, selected-setting details, and a
  separate hotwords value area. Short lists appear in full; long lists are
  truncated to fit with a word count. The sidebar shows the config path and
  unsaved-change count.
  Press `space` to start;
  use `v` for mixed or split transcripts, and `m` or `s` to toggle audio sources.
  Press `2` for Files;
  the browser opens in your saved Live recordings, so queue files there and use
  `x` to cancel a selected job. Sessions
  shows storage use in the sidebar and separates the session list from its
  detail. See the [terminal hub guide](docs/hub.md) for all sections, controls,
  and file formats.
- `stenographer doctor` — check capabilities and print fixes.
- `stenographer devices` — list audio input devices.
- `stenographer sounds [PACK]` — list, preview, or select sound feedback.
- `stenographer stats` — view, export, or delete local numeric statistics.
- `stenographer transcribe FILE [--raw] [--refine]` — transcribe an audio file.
- `stenographer model download [--asr|--refine|--live]` — fetch models explicitly.
- `stenographer run` — run the daemon in the foreground.
- `stenographer live` — open the standalone live app with its existing flags;
  it does not open the hub. After `q`, it keeps each renamed label on one voice
  and numbers unnamed voices by first appearance. Press `q` again to skip.
  `--diarize-mic` (or `live.diarize_mic = true`) labels the people on one
  microphone `Room 1`, `Room 2`, and so on instead of `You`. See the
  [live guide](docs/live.md).

Add `--help` to any command for full usage. See the [user guide](docs/usage.md)
for sound packs, statistics, and configuration examples.

## Troubleshooting

```sh
stenographer doctor
journalctl --user -u stenographer.service -f
systemctl --user restart stenographer.service
```

## Privacy and more

Model downloads are explicit and dictation runs locally. Audio, transcripts,
configuration, and device or model names stay on your machine. Logs never
contain transcript text or audio. `stenographer live` saves the requested
audio and transcript in a private session folder, then saves a new revision
with batch speaker labels; see the [live guide](docs/live.md).
The only automatic network request that leaves your machine is an optional,
metadata-only release check; disable it in
`[stenographer.feedback]` with `update_check = false`.

The [terminal hub](docs/hub.md) includes Live, Files, Sessions, Config, Setup,
and Doctor. Recording starts only when you press `space`; changing sections
does not stop a recording. Files jobs run in the background, one at a time.

A [refine](docs/refine.md) pass, on by default, provides exactly two built-in
profiles through one local Ollama model. Agent rewrites jumbled requests into
concise instructions. It can rephrase, reorder, group ideas, and remove
repetitions while the prompt requires every distinct fact, reason, request,
uncertainty, and authorization limit to survive. It never acts on the request.
Agent trusts the model to preserve meaning: it has no semantic or length-ratio
checks, so changed names, numbers, negations, uncertainty, or authorization can
reach the cursor. It retains response-format, empty-output, truncation, and
wrapper checks. Detected refinement failures deliver the original formatted
transcript. General retains its original length and numeral checks.
General keeps the original filler and self-correction cleanup behavior
(`gemma4:e2b` by default) on `127.0.0.1`, so the text still never leaves your
machine. Turn it off or point it elsewhere in `[stenographer.refine]`; a
non-loopback host sends transcripts there over the network. While a model
loads, the lifecycle pill's border breathes: in the amber Loading colour for
the speech model and in the Refining colour for the cleanup model, taking
turns one breath each when both are loading.

Read the [user guide](docs/usage.md) for privacy settings and more examples,
and the [live guide](docs/live.md) for live capture and saved sessions.

## Development

See [docs/building.md](docs/building.md) for standalone builds and contributor
checks. See [docs/architecture.md](docs/architecture.md) for code boundaries.
The [transcription-quality study](docs/transcription-experiments.md) contains
public-audio benchmark runners, measured results, and a microphone experiment
catalog. These diagnostics do not change the installed dictation settings.

## License

GPL-3.0-or-later.
