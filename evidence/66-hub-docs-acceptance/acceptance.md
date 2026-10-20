# Real-machine acceptance: stenographer hub

Run these checks on a supported Linux machine in a terminal. Use a local
installation that includes the hub changes. Do not add transcript text or audio
to the acceptance report. Record only pass/fail, counts, and any error message
that contains no transcript data.

## Prepare

1. Use a microphone and test files that you have permission to use. Keep three
   short speech files ready: WAV, MP3, and M4A. Prepare several minutes of
   non-sensitive speech with at least two voices to play through system audio.
   Step 2 saves it as the long session for the re-diarization check.
2. Confirm that the ASR, voice-activity, and speaker models are already cached.
   If they are not cached, download them only with the user's approval:

   ```sh
   stenographer model download --asr
   stenographer model download --live
   ```

3. Confirm that system `ffmpeg` is installed. M4A and AAC jobs need it:

   ```sh
   command -v ffmpeg
   ```

4. Use an isolated config and data folder so the checks do not change the
   normal config or saved sessions. Copy the current config, or create defaults
   if no config exists:

   ```sh
   mkdir -p "$HOME/.cache/stenographer-hub-acceptance"
   if [ -f "$HOME/.config/stenographer/config.toml" ]; then
     cp "$HOME/.config/stenographer/config.toml" \
       "$HOME/.cache/stenographer-hub-acceptance/config.toml"
   else
     STENOGRAPHER_CONFIG="$HOME/.cache/stenographer-hub-acceptance/config.toml" \
       stenographer setup --default
   fi
   export STENOGRAPHER_CONFIG="$HOME/.cache/stenographer-hub-acceptance/config.toml"
   export XDG_DATA_HOME="$HOME/.cache/stenographer-hub-acceptance/data"
   ```

## Checks

### 1. Open the hub

Run `stenographer`.

**Expected:** The terminal hub opens on Live. The sidebar lists Live, Files,
Sessions, Config, Setup, and Doctor as sections `1` through `6`. No recording
starts until you press `space`.

### 2. Start recording and change sections

Press `space` and speak while playing the prepared multi-voice audio through
the system output. Record for several minutes. While the recording is active,
press `2`, `3`, `4`, `5`, and `6`, then press `1` to return to Live.

**Expected:** The recording continues during navigation. On return to Live,
the recording timer has advanced and the live transcript and source meters
continue to update. No new recording starts when you change sections. The
saved recording has multiple system-speaker phrases for the later session test.

### 3. Show split view

While recording, press `v`, then press `v` again.

**Expected:** The first press shows separate MIC and SYSTEM columns in time
order. The second press restores the mixed transcript. `m` and `s` toggle their
respective sources; their status changes on screen.

### 4. Confirm quit during recording

While recording, press `q`. Press `escape` to cancel the prompt. Press `q`
again, then press `y` to confirm.

**Expected:** The first prompt leaves the session running. The second
confirmation stops and saves the session before the hub exits. The saved
session appears in Sessions when you open the hub again. If system speech was
recorded, the stop flow shows its speaker re-label progress and saves a revised
transcript.

### 5. Transcribe WAV, MP3, and M4A files

Open the hub again and press `2`. Keep diarization on, set speaker count to
`auto`, and queue each prepared WAV, MP3, and M4A file. Keep the output format
as `md`. Then queue one file with enough distinct voices again, this time with
speaker count set to a positive fixed number.

**Expected:** The queue runs one job at a time and shows its stage and progress.
Each successful job shows a preview and saves one Markdown file in the selected
output folder. The fixed-count job uses the requested number of speaker labels
when it has enough phrases. The M4A job completes through system `ffmpeg`.
There is no partial output for a failed or cancelled job.

### 6. Re-diarize a long saved session

Press `3`, select the long saved session with the arrow keys, and press `d`.
Wait for the re-diarization job to finish.

**Expected:** The hub remains usable while it works. It reports completion,
refreshes the session detail, and shows the revised speaker labels and talk
times. Earlier transcript revisions remain available. Treat the labels as
similarity estimates, not confirmed identities. A minor voice gets a separate
label only when it has at least 15 seconds of phrases of at least 2 seconds
within a 30-second window and at least two-thirds of its speech in those
phrases, or at least 20% of the top speaker's speech time; otherwise it merges
into the most similar voice.

### 7. Save Config and check its backup

Press `4`. Select a harmless setting, such as `feedback.volume`, and change it.
Press `ctrl+s` to save. Use the isolated config path from Prepare.

**Expected:** The hub reports a successful save and a timestamped
`config.toml.bak-<time>` backup. The copied config contains the change, and the
normal config remains unchanged. If the copied config has an explicit
`stenographer.asr.model`, that value remains unchanged.

### 8. Run Setup and Doctor

Press `5`. Use `t` to test the current Setup step, `enter` to advance, and `b`
to return. Check the input, microphone, hotkey, models, sounds, and system
service steps. The microphone test only lists devices; it does not record.
Then press `6` and `r` to run Doctor checks again. Select a check and press
`enter` to show its details.

**Expected:** Setup shows six steps and reports each test result. Its model
step reports cache state and does not download a model without confirmation.
Doctor shows grouped checks, details, fixes, and optional warnings, including
the `ffmpeg` status. Optional warnings do not make the existing doctor command
fail.

### 9. Request quit while start or save is finishing

Open the hub on Live and press `space`. While `Starting recording...` is
visible, press `ctrl+c` once. Wait for the start operation to finish. If the
hub remains open, press `q` and confirm the recording stop. While
`Saving recording...` is visible, press `ctrl+c` once and wait for the save to
finish.

**Expected:** The hub does not crash or print a traceback while either
operation finishes. It stays responsive during start. A confirmed save
finishes before the hub exits, and the saved session appears in Sessions after
you reopen the hub. If a quit key arrives while work is active, wait for the
status to clear and request quit again when the hub remains open.

## Cleanup

After you record the results, remove the isolated acceptance directory if you
no longer need its files. Do not remove user data outside that directory.
