<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Live transcription

`stenographer live` records speech from the microphone, system output, or both.
It opens the standalone live app, keeps its existing flags, and saves the audio
and transcript in a private session folder. It does not open the hub. Bare
`stenographer` opens the [terminal hub](hub.md) on Live and waits for `space`
before it records. In the hub, recording continues when you change sections;
`v` switches between mixed and split transcript views, and `m` and `s` toggle
the audio sources. The hub asks you to confirm before it stops and saves a
recording when you quit. Live capture is local. Neither command sends audio or
transcript text over the network.

## Prepare the models

Live uses the same speech model as dictation and Files: Underdog Bark 3.0
Pro, int8 ONNX on the CPU. Live also uses separate voice-activity and speaker
models. Download each model only when you choose to:

```sh
stenographer model download --asr
stenographer model download --live
```

`--asr` builds the speech model on your machine and downloads the Silero
voice-activity model. It needs `python3-venv`, 10 GiB of free disk, and about
10.2 GiB of RAM; see [build the speech model](usage.md#build-the-speech-model).
`--live` downloads the Silero voice-activity model and the English speaker
model. `live` does not
download models for you.

## Start a session

```sh
stenographer live
```

The microphone and system audio are enabled by default. Choose a microphone
with `--device DEV`, or disable either source:

```sh
stenographer live --device DEV
stenographer live --no-system
stenographer live --no-mic
```

`--mic` and `--system` enable their sources. `--no-mic` and `--no-system`
disable them. The `m` and `s` keys also toggle the microphone and system audio
while a session is open.

### Separate the speakers in a room

When several people share one microphone, turn on microphone diarization:

```sh
stenographer live --diarize-mic
```

`--diarize-mic` and `--no-diarize-mic` override the
`stenographer.live.diarize_mic` setting (default `false`) for one session.
The hub Live section uses the setting; change it on the hub Config board.
You cannot change it during a session.

With the setting on, microphone speakers get labels such as `Room 1` and
`Room 2` (speaker IDs `room-1`, `room-2`). System speakers keep `Speaker 1`,
`Speaker 2`. Microphone and system voices are never clustered together, so a
room voice and a system voice never share a label. When you stop, the same
relabel pass runs on the microphone phrases separately from the system
phrases. Press `r` to rename a room speaker. With the setting off, every
microphone line is `You`.

Limits:

- Labels are per phrase. Voice-activity detection splits phrases at pauses, so
  a speaker change without a pause stays in one phrase under one label.
- Room labels are similarity estimates, like system labels. They can split one
  person or merge several people.
- System audio that leaks into the microphone can appear as a room speaker. Use
  headphones to avoid this.

System capture records the full mix from the current default output sink. It
does not capture separate applications. It requires PipeWire, `pw-record`, and
`pactl`. The command does not follow a change to the default output sink during
a session. If you do not need system audio, start with `--no-system` or press
`s`.

## Controls

- `space` pauses or resumes capture. Paused time does not advance the session
  clock.
- `up` and `down` scroll one line. `pageup` and `pagedown` scroll one page.
  `home` moves to the start; `end` moves to the latest line. The mouse wheel
  also scrolls the transcript.
- The transcript follows new lines while it is at the bottom. When you scroll
  up, new lines do not move the view. Scroll to the bottom or press `end` to
  follow new lines again.
- `m` turns microphone capture on or off.
- `s` turns system audio capture on or off.
- `r` opens the speaker rename screen.
- `q` stops the session and saves its files. Stenographer then re-labels the recognized system phrases, and the microphone phrases when microphone diarization is on. Press `q` again to skip this pass.

Microphone speech appears as `You`, or as `Room 1`, `Room 2`, and so on with
[microphone diarization](#separate-the-speakers-in-a-room); system speech gets
labels such as `Speaker 1`. Speaker labels are similarity estimates. They can split one person
into multiple labels or merge several people under one label. Phrases shorter
than 1.2 seconds reuse a known speaker and do not change its embedding mean.
When you stop a session, Stenographer shows progress while it clusters the
saved system phrases and writes a new transcript revision. A minor voice gets
its own label only if it has at least 15 seconds of phrases that are each at
least 2 seconds long within a 30-second window, or if it has at least 20% of
the top speaker's speech time. The 15-second condition also requires at least
two-thirds of that voice's speech to be in those sustained phrases. Otherwise,
the voice is merged into the most similar speaker. Short or sparse phrases can
remain under another speaker's label. Each user-renamed label can go to only
one cluster; when a label appears in several clusters, it stays with the
cluster with the most shared speech time. The pass numbers clusters without a
user name `Speaker 1`, `Speaker 2`, and so on, in order of first appearance in
the session. Press `q` again during the pass to keep the live labels. If
relabeling fails, the live labels remain and the command reports the reason.
Press `r` and assign the same display name to speakers to merge their displayed
labels. This does not change their underlying speaker IDs. The clustering
threshold is 0.50; it was tested on only three clips, so labels are not reliable
identification.

## Saved session files

Sessions are saved under
`$XDG_DATA_HOME/stenographer/sessions/<UTC YYYYMMDDTHHMMSSZ>/`. If
`XDG_DATA_HOME` is not set, the directory is
`~/.local/share/stenographer/sessions/<UTC YYYYMMDDTHHMMSSZ>/`.

The session directory has mode `0700`. Each file has mode `0600`. Files are
created only for sources that were active during the session:

- `mic.flac` and `system.flac` contain 16 kHz, mono, FLAC `PCM_24` audio.
  Audio is flushed as the session runs. A source that is off during part of
  the session has silence for that time in its file.
- `transcript.jsonl` contains one JSON object per recognized phrase. Each
  object has `start`, `end`, `wall` (UTC), `source`, `speaker_id`, `label`, and
  `text` fields. Speaker rename events are also recorded.
- `transcript.md` is written when the session stops. It contains the saved
  transcript and the final display labels.
- `session.json` records the current transcript revision. A session recorded
  with microphone diarization has it from the start, with `"diarize_mic": true`.

These files are user data requested by the `live` command. `live` writes
transcript text and audio only to this session folder. Logs and analytics do
not contain transcript text or audio. See the [privacy notes](usage.md#understand-privacy-and-network-access)
for other Stenographer network behavior.

## Limits

Each phrase is decoded on the CPU. Microphone and system phrases share one
processing queue, so a backlog can delay lines. Running `stenographer run` and
`stenographer live` together is supported. Each command loads its own copy of
the configured ASR model, and both can compete for CPU time.

Echo cancellation is out of scope. System audio can also reach the microphone
and appear twice. Use headphones, or turn off the microphone with
`--no-mic` or `m`.
