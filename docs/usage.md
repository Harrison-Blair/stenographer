<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# User guide

This guide covers the settings and commands you may want after the first run.
For the shortest path from install to dictation, see the [README](../README.md).

## Configure a different workflow

Run the setup wizard to review every setting:

```sh
stenographer setup
```

For common settings only, use `stenographer setup --quick`. The wizard can
check the microphone, clipboard, model, and input permissions, and offers the
separate model download. The model is about 1.6 GB and is downloaded only when
you choose it.

The default ASR model is `deepdml/faster-whisper-large-v3-turbo-ct2`. The
[CPU model and context screen (2026-10-20)](transcription-experiments.md#cpu-model-and-context-screen-2026-10-20)
selected this model. It is about 1.6 GB and is downloaded only when you choose
the model download. Existing configurations keep their selected model. For
live capture, see the [live transcription guide](live.md).

The configuration file is:

```text
~/.config/stenographer/config.toml
```

For example, use toggle mode, keep Escape as the cancel key, and hide the
lifecycle pill:

```toml
[stenographer.hotkey]
binding = "KEY_RIGHTCTRL"          # Agent profile
general_binding = "KEY_RIGHTALT"  # General profile
mode = "toggle"              # hybrid, hold, or toggle
cancel_binding = "KEY_ESC"  # "" disables cancellation

[stenographer.feedback]
overlay = false
```

Hybrid mode is the default for both profile bindings. Right Ctrl selects Agent;
Right Alt selects General. Tap either to latch a recording, or hold it while
speaking and release to stop. In hold mode only the held press records; in
toggle mode press once to start and again to stop. Agent, General, and cancel
chords cannot be equal or subsets of one another.

Save changes through the CLI when possible: comments and settings the CLI does
not know about are preserved. Restart the service after saving:

```sh
systemctl --user restart stenographer.service
```

`stenographer setup --default` writes annotated defaults without prompting and
backs up the previous configuration first.

## Cancel a dictation

Press Escape while recording or while the result is being delivered. The audio
and transcript are discarded, and nothing is pasted. The focused application
still receives the Escape keypress. If cancellation happens during ASR decode,
the run finishes at the next decode boundary, but the result is still discarded.

Set `cancel_binding = ""` to disable this behavior, or choose another evdev
`KEY_*` name for the binding.

## Keep your clipboard

The daemon puts your previous clipboard item back after each paste. It saves
the clipboard before it copies the transcript, pastes, plays the delivered
sound, waits `restore_delay_ms`, and then writes the saved item back. The
primary selection keeps the transcript. The saved item is held in memory only
until it is restored, and it is never logged.

When Agent rewrites the text, the unrefined transcript is copied just before
the rewrite. A clipboard history manager therefore lists the original, then the
rewrite, and then your previous item again. General never copies the original.

```toml
[stenographer.delivery]
copy_original = true      # Agent only
restore_clipboard = true
restore_delay_ms = 500    # 0 to 60000
```

Limits:

- Only one type of the saved item comes back, preferring plain text. A copied
  file, or an image offered together with HTML, returns as its plain-text or
  first offered type only.
- An item that a password manager marks as secret is not saved. The
  transcript stays on the clipboard instead.
- The daemon stays busy for `restore_delay_ms` after each paste. A hotkey press
  in that window is ignored. Escape no longer cancels, because the text is
  already pasted.
- If an application reads the paste late and gets your previous item, increase
  `restore_delay_ms`.
- Saving waits at most one second and keeps at most 64 MiB. A slower or larger
  item is not restored.
- Restoring needs `wl-paste` from `wl-clipboard` (or `xclip` under XWayland).
  Without it the daemon still runs and leaves the transcript on the clipboard;
  `stenographer doctor` reports this on its `clipboard restore` line.

## Choose sound feedback

List or preview the bundled packs without changing the selection:

```sh
stenographer sounds --list
stenographer sounds --preview warm-desk
```

Select a pack for the daemon:

```sh
stenographer sounds soft-electronic
```

The bundled packs are `legacy`, `warm-desk`, `soft-electronic`, and
`minimal-ui`. A custom pack lives under
`~/.config/stenographer/sounds/<pack>/` and must contain these four files:

```text
record_start.wav
record_stop.wav
delivered.wav
error.wav
```

Each file must be a readable, nonempty, uncompressed PCM WAV shorter than 300
ms. Restart the service after selecting or editing a custom pack. An incomplete
or invalid pack is ignored as a unit.

## View or remove statistics

Statistics are local numeric records. View totals or export them:

```sh
stenographer stats
stenographer stats export --format json
stenographer stats export --format csv --output stats.csv
```

Preview a date-range deletion, then confirm it with `--yes`:

```sh
stenographer stats delete --since 2026-09-01 --until 2026-09-07
stenographer stats delete --since 2026-09-01 --until 2026-09-07 --yes
```

Preview removal of all sources with `stenographer stats reset`; add `--yes` to
confirm. No audio, transcript, prompt, or hotword text is retained in these
records. Disable collection with:

```toml
[stenographer.analytics]
enabled = false
```

Set `resource_profiling = false` if you want ordinary numeric statistics without
host resource sampling. Collection is asynchronous, so an application crash
can lose measurements that have not been committed yet.

## Understand privacy and network access

The model runs locally. Audio, transcripts, configuration, and device or model
names do not leave the machine. Logs contain timings and counts, never audio or
transcript text. The lifecycle pill does not receive raw audio or transcript
text.

By default the only network access that leaves the machine is an optional
metadata-only request for the latest GitHub release tag, at most once every
24 hours. It never downloads a model or release. Disable the check with:

```toml
[stenographer.feedback]
update_check = false
```

The [refine](refine.md) stage is the one setting that sends transcript text
anywhere. It is on by default, and its default host is loopback, so the text
stays on the machine; pointing `[stenographer.refine] host` at another machine
sends transcripts to it over the network.

It cleans filler words and self-corrections out of each transcript through a
local Ollama model. The default is `gemma4:e2b`, about a 7.2 GB download;
`qwen3.5:4b` is the documented alternative and needs
`structured_output = true`. Model reasoning is always disabled. See
[docs/refine.md](refine.md) for the whole feature.

## Open the terminal hub

Run `stenographer` with no arguments in a terminal to open the hub. It starts
on Live; press `space` when you want to start recording. If stdin or stdout is
not a terminal, the command prints help. Existing subcommands, including
`stenographer live`, keep their current behavior.

In the hub, press `2` to open Files. The browser starts in your home folder.
Use `/` to filter names in the current folder, `enter` to open a folder, and
`space` to select files. Press `enter` to queue the selected files. The queue
runs one file at a time and continues when you change sections.

Press `o` to focus the options. Use `up` and `down` to select an option and
`space` or `enter` to change it. Diarization starts on, refine starts off, and
Markdown is the default format. Set the speaker count to `auto` or a positive
number. The output folder defaults to the Stenographer data folder's `files`
subfolder. In the queue, use `tab` to focus the selected job, `up` or `down` to
select a job, and `x` to cancel it. The preview shows current or completed
transcript lines with speaker labels. Press `e` on a job with a saved result to
open its folder with `xdg-open`.

## Start live transcription

Run `stenographer live` to transcribe the microphone and full system mix in a
terminal session. Download its voice and speaker models with
`stenographer model download --live`; download the configured ASR model
separately with `stenographer model download --asr`. See the
[live transcription guide](live.md) for source controls, saved files, privacy,
and limits.

## Troubleshoot a running service

Start with the capability report:

```sh
stenographer doctor
```

Inspect service state and logs:

```sh
systemctl --user status stenographer.service --no-pager
journalctl --user -u stenographer.service -f
```

Common fixes:

- If the model is missing, run `stenographer model download`.
- If the keyboard is unavailable, check read access to `/dev/input/event*` and
  write access to `/dev/uinput`; `doctor` reports the required groups/rules.
- If delivery fails under Wayland, install `wl-copy` from `wl-clipboard`.
  `xclip` with XWayland is supported where Wayland data control is unavailable.
- If your previous clipboard item does not come back, install `wl-paste` from
  `wl-clipboard`, or increase `restore_delay_ms`; see
  [Keep your clipboard](#keep-your-clipboard).
- If a setting change has no effect, restart the user service.
- Sound cues and desktop error notifications are optional; missing players do
  not stop dictation.

For command-specific options, run `stenographer COMMAND --help`.

## Improve microphone capture

Start by checking which inputs Stenographer can see:

```sh
stenographer devices
```

Select the intended microphone in your audio settings or configuration. Keep a
headset or close microphone about 10–20 cm from your mouth, point it toward (but
slightly to the side of) your mouth, and avoid touching the desk or cable. Speak
normally while adjusting the input level: louder is not always better. Raise it
until ordinary speech is clear, then check a louder word for clipping or harsh
distortion. If words disappear only when you speak quietly, compare a modest
level increase; if background noise rises with it, move the microphone closer
instead of adding more gain.

Temporarily compare operating-system noise suppression, automatic gain control,
echo cancellation, and beamforming one at a time. A wired headset often gives a
cleaner signal than a distant array. Restore your original setting if a change
does not improve repeated, matched samples. The value shown by a mixer is not
enough to diagnose gain: the captured speech level and clipping must be checked.

### What normalization does

Digital RMS normalization rescales a recording so its measured speech energy
approaches a target level such as `-24 dBFS`. It can make consistently quiet
audio easier for a recognizer to use, but it cannot reconstruct a consonant that
the microphone never captured. It can also amplify background noise and expose
clipping or distortion. In the project's public-audio evaluation it improved
development clips but regressed the held-out clips, so it is not enabled by
default. Fix microphone placement and capture level first.
