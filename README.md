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

[Release notes](https://github.com/Harrison-Blair/stenographer/releases)

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
curl -fsSL https://harrison-blair.github.io/stenographer/install.sh | bash
```

The same command installs and updates. It verifies and installs the latest
prebuilt bundle and user service. A new install leaves the service stopped and
prints the setup step, so you can configure it and build the model. An update
keeps the service state: a running service restarts on the new version, a stopped
service stays stopped, and a disabled service stays disabled. The install needs no Python or build tools; the
later model build needs the system `python3-venv` package. For another
architecture or a local build,
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
offers the separate ASR model download. Use plain `setup` to
review the hotkey, audio, ASR, feedback, and refine settings. Use hub Settings
or the configuration file for the remaining settings. If room noise changes
during spectrum calibration, keep the room quiet and retry. If overlay backend
imports fail, reinstall using the installation method above.

## Speech model

Dictation, Record, and file jobs use one speech model: Underdog Bark 3.0 Pro by
Conway Research. It runs as int8 ONNX through sherpa-onnx, on the CPU only.
Stenographer does not host the model. Build it once on your machine:

```sh
sudo apt install python3-venv     # once; stenographer never runs sudo
stenographer model download --asr
```

The command downloads the pinned source weights and converter packages (about
1.6 GB), checks their sha256, and converts the model to int8 ONNX on your
machine. It needs 10 GiB of
free disk and about 10.2 GiB of RAM while it converts. On the test machine it
took about 2 minutes. The installed model uses about 653 MiB. A machine with
less RAM can run out of memory during the conversion. Speech-model settings
from earlier releases stay in your config file and are ignored; see the
[release notes](https://github.com/Harrison-Blair/stenographer/releases).

For clearer recognition, first run `stenographer devices` and select the
intended microphone. Keep it about 10–20 cm from your mouth, aim it slightly
off-axis, and raise the input level only until normal speech is clear without
clipping. A close wired headset often beats a distant microphone. See the
[microphone and normalization guidance](docs/usage.md#improve-microphone-capture)
for troubleshooting steps.

Configuration defaults to `~/.config/stenographer/config.toml`. Set
`STENOGRAPHER_CONFIG` to choose a file, or `XDG_CONFIG_HOME` to change the
default configuration directory. For example:

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

Otherwise the transcript is pasted at your cursor. By default, when clipboard
capture and restoration are available, your previous item is restored about
half a second later unless you copied something newer. Configure this with
`restore_clipboard` and `restore_delay_ms`. When Agent changes the text and
`stenographer.delivery.copy_original` is enabled, the app attempts to copy the
original immediately before the rewritten text. This copy is best effort; a
clipboard history can keep both. See
[Keep your clipboard](docs/usage.md#keep-your-clipboard).
Use `mode = "hold"` for push-to-talk only or `mode = "toggle"` for press/press.
The formatter capitalizes the pronoun `i`, including when surrounded by punctuation.

Set `binding` (Agent) or `general_binding` to any `KEY_*` chord to rebind it. Binding errors identify the setting that contains the invalid chord.
Agent, General, and cancel chords may not be equal or subsets of one another.

## Common commands

- `stenographer` — open the terminal hub when stdin and stdout are terminals;
  otherwise show help. The hub has three screens: press `1` for Record, `2`
  for Library, and `3` for Settings, and `?` for the keys of each screen. One
  top line on each screen shows navigation badges, the model state, and CPU and
  memory use. Transcripts use the full width, under a horizontal speaker bar.
  On Record, press `space` to start and `enter` to stop and save; the hub stays
  open while the speaker relabel pass runs; a skipped or failed
  pass saves the speakers and names shown on screen, numbered from 1, and a failure
  shows the reason. When a recording stops, when a file job ends, and on Re-diarize
  and Re-transcribe, a bundled model finds the speech in the saved audio and the
  speakers come from it. A line where another voice holds at least 1 second is split
  into separate lines. The live view does not change.
  `o` opens the saved session in
  Library. Use `v` for mixed or split transcripts, `m` or `s` to toggle audio
  sources, and `d` to choose the input device for this run. Scroll with `up`/`down`,
  `pageup`/`pagedown`, `home`/`end`, or the mouse wheel; the view follows new
  lines at the bottom. Library lists recordings, file sessions, and file
  jobs; press `/` to search session IDs, times (including displayed recording
  dates), file names, and transcripts, `p` to play, `d` or `t` to
  re-diarize or re-transcribe, `x` to export, and `delete` to delete or cancel
  a job; confirm with `y` or cancel with `n`. Press `n` there to transcribe a file: the dialog browses from your
  home folder, including hidden folders; search with a leading dot to find hidden audio. Folder read errors show their reason. The dialog sets Separate speakers, Speaker count, and Refine text, and
  queues one job that shows in the list at once. Speaker count is ignored when
  separation is off. Help and quit appear first in the footer. Settings values wrap when long. Settings has the General, Audio,
  Recognition, Live, and Checks tabs; `●` marks an unsaved change, `ctrl+s`
  saves it with a backup, and the Vocabulary row edits the refine terms.
  Checks shows fix guidance and per-check test results, groups the system checks,
  fixes and tests the selected check, and opens the Quick setup, Models, and
  Defaults dialogs. See the [terminal hub guide](docs/hub.md) for all screens, controls,
  and file formats.
- `stenographer doctor` — check capabilities and print fixes.
- `stenographer devices` — list audio input devices.
- `stenographer sounds [PACK]` — list, preview, or select sound feedback.
- `stenographer stats` — view, export, or delete local numeric statistics; the summary defaults to hotkey dictations (`--source all` includes file transcriptions).
- `stenographer transcribe FILE [--raw] [--refine]` — transcribe an audio file; `--raw` skips refinement even when `--refine` is supplied.
- `stenographer model download [--asr] [--refine]` — fetch selected models explicitly; flags combine.
  The voice-activity and speaker models ship with the app and need no download.
- `stenographer run` — run the daemon in the foreground.

Add `--help` to any command for full usage. See the [user guide](docs/usage.md)
for sound packs, statistics, and configuration examples. Stats reset deletes all records; use stats delete for filtered deletion.

## Troubleshooting

```sh
stenographer doctor
journalctl --user -u stenographer.service -f
systemctl --user restart stenographer.service
```

## Privacy and more

Model downloads are explicit and dictation runs locally. Audio, transcripts,
configuration, and device or model names stay on your machine by default; a
configured remote refine host receives transcripts. Logs never
contain transcript text or audio. The hub Record screen saves the requested
audio and transcript in a private session folder, then saves a new revision
with batch speaker labels; see the [hub guide](docs/hub.md#record). Revisions
require readable, valid session metadata when `session.json` exists.

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
non-loopback host sends transcripts there over the network. Loopback refine
requests bypass environment proxies. While a model
loads, the lifecycle pill's border breathes: in the amber Loading colour for
the speech model and in the Refining colour for the cleanup model, taking
turns one breath each when both are loading.

On Hyprland, the pill opens under the mouse pointer; elsewhere it opens at the
bottom center of the screen.

Read the [user guide](docs/usage.md) for privacy settings and more examples,
and the [hub guide](docs/hub.md#record) for live capture and saved sessions.

## Development

See [docs/building.md](docs/building.md) for standalone builds and contributor
checks. See [docs/architecture.md](docs/architecture.md) for code boundaries.

## License

GPL-3.0-or-later.

### Third-party models

Stenographer ships one model, pyannote segmentation 3.0. You download each other
model explicitly. The attribution files are in
[`src/stenographer/assets/licenses/`](src/stenographer/assets/licenses/).

| Model | Authors | License | Use |
| --- | --- | --- | --- |
| [Underdog Bark 3.0 Pro](https://huggingface.co/ConwayResearch/Underdog-Bark-3.0-Pro) | Conway Research | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Speech recognition. Converted to ONNX and quantized to int8 (weight-only) on your machine by stenographer. |
| [nvidia/parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | NVIDIA | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Base of Bark 3.0 Pro (named in its NOTICE). |
| [moondream/parakeet-ultra](https://huggingface.co/moondream/parakeet-ultra) | Moondream | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Base of Bark 3.0 Pro (named in its NOTICE). |
| [Silero VAD](https://github.com/snakers4/silero-vad) | Silero Team | [MIT](https://github.com/snakers4/silero-vad/blob/master/LICENSE) | Voice activity in dictation, Record, and file jobs. Bundled in the app ([MIT text](src/stenographer/assets/licenses/silero-vad-MIT.txt)). |
| [pyannote segmentation 3.0](https://huggingface.co/pyannote/segmentation-3.0) | CNRS | [MIT](src/stenographer/assets/licenses/pyannote-segmentation-3.0-MIT.txt) | Finds speech when a recording or file is saved. Bundled in the app as the [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) ONNX export. |
| [WeSpeaker ResNet34-LM](https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md) | WeSpeaker team (wenet-e2e) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); trained on VoxCeleb, which is offered for research purposes ([NOTICE](src/stenographer/assets/licenses/wespeaker-resnet34-LM-NOTICE.txt)) | Speaker labels in Record and file jobs. Bundled in the app, with mean subtraction added to the ONNX graph by stenographer. |
