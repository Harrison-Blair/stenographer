<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Live transcription

`stenographer live` records speech from the microphone, system output, or both.
It transcribes each phrase in a terminal interface and saves the audio and
transcript in a private session folder. Live capture is local. The command does
not send audio or transcript text over the network.

## Prepare the models

Live uses your configured ASR model, plus separate voice-activity and speaker
models. Download each model only when you choose to:

```sh
stenographer model download --asr
stenographer model download --live
```

`--asr` downloads the configured speech-recognition model. `--live` downloads
the Silero voice-activity model and the English speaker model. `live` does not
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

System capture records the full mix from the current default output sink. It
does not capture separate applications. It requires PipeWire, `pw-record`, and
`pactl`. The command does not follow a change to the default output sink during
a session. If you do not need system audio, start with `--no-system` or press
`s`.

## Controls

- `space` pauses or resumes capture. Paused time does not advance the session
  clock.
- `m` turns microphone capture on or off.
- `s` turns system audio capture on or off.
- `r` opens the speaker rename screen.
- `q` stops the session and saves its files.

Microphone speech appears as `You`; system speech gets labels such as
`Speaker 1`. Speaker labels can split one person into multiple labels or merge
several people under one label. Press `r` and assign the same display name to
speakers to merge their displayed labels. This does not change their underlying
speaker IDs. The clustering threshold is 0.50; it was tested on only three
clips, so labels are estimates, not reliable identification.

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

These files are user data requested by the `live` command. `live` writes
transcript text and audio only to this session folder. Logs and analytics do
not contain transcript text or audio. See the [privacy notes](usage.md#understand-privacy-and-network-access)
for other Stenographer network behavior.

## Limits

A Whisper decode takes about two seconds per phrase with the default model in
the measured CPU benchmark. Microphone and system phrases share one processing
queue, so a backlog can delay lines. Running `stenographer run` and
`stenographer live` together is supported. Each command loads its own copy of
the configured ASR model, and both can compete for CPU time.

Echo cancellation is out of scope. System audio can also reach the microphone
and appear twice. Use headphones, or turn off the microphone with
`--no-mic` or `m`.
