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
leaves the service stopped so you can configure it and build the model. The
install needs no Python or build tools; the later model build needs the system
`python3-venv` package. For another architecture or a local build,
see [docs/building.md](docs/building.md).

## Requirements

You need Linux, Wayland, a systemd user manager, and:

- A PortAudio-backed microphone and the system PortAudio library.
- Read access to `/dev/input/event*`, normally through the `input` group.
- Write access to `/dev/uinput`, through a udev rule or `uinput` group.
- `wl-copy` from `wl-clipboard` (or `xclip` plus XWayland). `wl-paste`, also
  from `wl-clipboard`, lets the daemon restore your previous clipboard item.
- `python3-venv`, once, for the speech-model build. On Ubuntu, run
  `sudo apt install python3-venv`.

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
offers the separate ASR model download. Use plain `setup` to review every
setting.

## Speech model

Dictation, Live, and Files use one speech model: Underdog Bark 3.0 Pro by
Conway Research. It runs as int8 ONNX through sherpa-onnx, on the CPU only.
Stenographer does not host the model. Build it once on your machine:

```sh
sudo apt install python3-venv     # once; stenographer never runs sudo
stenographer model download --asr
```

The command downloads the pinned source weights and converter packages (about
1.6 GB), checks their sha256, and converts the model to int8 ONNX on your
machine. It also downloads the Silero voice-activity model. It needs 10 GiB of
free disk and about 10.2 GiB of RAM while it converts. On the test machine it
took about 2 minutes. The installed model uses about 653 MiB. A machine with
less RAM can run out of memory during the conversion. Speech-model settings
from earlier releases stay in your config file and are ignored; see the
[changelog](CHANGELOG.md).

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
  otherwise show help. The hub has three screens: press `1` for Record, `2`
  for Library, and `3` for Settings, and `?` for the keys of each screen. A
  sidebar on each screen shows navigation badges, an engine card with the
  model state and CPU and memory use, and one context card.
  On Record, press `space` to start and `enter` to stop and save; the hub stays
  open while the speaker relabel pass runs, and `o` opens the saved session in
  Library. Use `v` for mixed or split transcripts, `m` or `s` to toggle audio
  sources, and `d` to choose the input device for this run. Scroll with `up`/`down`,
  `pageup`/`pagedown`, `home`/`end`, or the mouse wheel; the view follows new
  lines at the bottom. Library lists recordings, file sessions, and file
  jobs; press `/` to search transcripts, `p` to play, `d` or `t` to
  re-diarize or re-transcribe, `x` to export, and `delete` to delete or cancel
  a job. Press `n` there to transcribe a file: the dialog browses from your
  home folder, sets Separate speakers, Speaker count, and Refine text, and
  queues one job that shows in the list at once. Settings has the General, Audio,
  Recognition, Live, and Checks tabs; `●` marks an unsaved change, `ctrl+s`
  saves it with a backup, and the Vocabulary row edits the refine terms.
  Checks groups the system checks,
  fixes and tests the selected check, and opens the Quick setup, Models, and
  Defaults dialogs. See the [terminal hub guide](docs/hub.md) for all screens, controls,
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

The [terminal hub](docs/hub.md) has three screens: Record, Library, and
Settings. Recording starts only when you press `space`; changing screens
does not stop a recording. File jobs run in the background, one at a time.

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
The [transcription-quality study](docs/transcription-experiments.md) records
earlier public-audio measurements and a microphone experiment catalog. It is
history; the speech model it measured is no longer used.

## License

GPL-3.0-or-later.

### Third-party models

Stenographer ships no model weights. You download each model explicitly. The
attribution files are in
[`src/stenographer/assets/licenses/`](src/stenographer/assets/licenses/).

| Model | Authors | License | Use |
| --- | --- | --- | --- |
| [Underdog Bark 3.0 Pro](https://huggingface.co/ConwayResearch/Underdog-Bark-3.0-Pro) | Conway Research | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Speech recognition. Converted to ONNX and quantized to int8 (weight-only) on your machine by stenographer. |
| [nvidia/parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | NVIDIA | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Base of Bark 3.0 Pro (named in its NOTICE). |
| [moondream/parakeet-ultra](https://huggingface.co/moondream/parakeet-ultra) | Moondream | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Base of Bark 3.0 Pro (named in its NOTICE). |
| [Silero VAD](https://github.com/snakers4/silero-vad) | Silero Team | [MIT](https://github.com/snakers4/silero-vad/blob/master/LICENSE) | Voice activity in dictation, Live, and Files. |
| [TitaNet small](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/titanet_small) | NVIDIA | NeMo Toolkit license ([Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)) | Speaker labels in Live and Files. |
