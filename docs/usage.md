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

The default ASR model is `dropbox-dash/faster-whisper-large-v3-turbo`. It is
about 1.6 GB and is downloaded only when you explicitly choose the model
download. Existing configurations keep their selected model.

The configuration file is:

```text
~/.config/stenographer/config.toml
```

For example, use toggle mode, keep Escape as the cancel key, and hide the
lifecycle pill:

```toml
[stenographer.hotkey]
mode = "toggle"              # hybrid, hold, or toggle
cancel_binding = "KEY_ESC"  # "" disables cancellation

[stenographer.feedback]
overlay = false
```

Hybrid mode is the default. Tap Right Ctrl to latch a recording, or hold it
while speaking and release to stop. In hold mode only the held press records;
in toggle mode press once to start and again to stop.

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
