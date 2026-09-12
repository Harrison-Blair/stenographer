<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Changelog

These notes cover every published stable release. They describe observable
behavior and release packaging, with internal planning and generated commit
lists left out.

Each entry opens with a short synopsis, then lists changes under `### Added`,
`### Removed`, and `### Fixed`, in that order, omitting any section with
nothing in it. The release workflow validates this structure and publishes
the entry as the GitHub release body; see [docs/building.md](docs/building.md).

## [v0.13.1] - 2026-09-12

The default dictation key is now chosen by the host rather than fixed for
every platform.

### Added

- Windows installs now default to Right Alt as the dictation hotkey; Linux and
  macOS keep Right Ctrl, and an explicitly configured binding is unchanged.

## [v0.13.0] - 2026-09-11

This release adds a local cleanup stage, on by default, that turns dictated
speech into written text without leaving your machine. It also raises the
default speech model, backed by new transcription and refine benchmarks kept
in the repository.

### Added

- Adds refine: a stage, on by default but inert until Ollama and its model
  are installed, that sends each dictation of ten or more words to a local
  Ollama model, collapses self-corrections, removes hesitation fillers, and
  renders spoken lists as lines. Meaning is preserved; nothing is
  summarized, answered, or added. If the server has evicted the model, the
  stage waits up to two minutes for it to load again before timing the
  reply, so an utterance that arrives on a cold model still gets cleaned up
  instead of being handed back as-is. On any error or timeout, the original
  transcript is delivered unchanged — as it is when a reply adds, rewrites,
  or loses a number you did not take back.
- Defaults to `gemma4:e2b` over loopback. Any installed Ollama model can be
  configured; a non-loopback host is reported in the daemon banner.
- Stopping the daemon releases the model from VRAM instead of leaving it
  pinned until Ollama's own timer expires — which on `idle_unload_seconds = 0`
  is never.
- `stenographer model download` offers to fetch both the ASR and refine
  models when refine is on, and defaults its confirmation to No — a bare
  Enter downloads nothing rather than starting a multi-gigabyte pull. With
  refine off, it downloads just the ASR model immediately, the same as
  `--asr`. `--asr` and `--refine` always force one explicitly, regardless of
  the setting. `stenographer transcribe` gains its own explicit `--refine`
  flag.
- The overlay shows a Refining state; cancelling during it stops the stage
  at the end of whichever request is already open — up to two minutes if
  that is a cold load, seconds otherwise — rather than waiting out the
  utterance's full budget. Local analytics record refine timing and
  outcomes, including a `cancelled` outcome, as numbers only.
- Uses `dropbox-dash/faster-whisper-large-v3-turbo` as the new default ASR
  model (about 1.6 GB), while preserving existing configured model choices.
- Documents microphone placement, input-level checks, and digital
  normalization tradeoffs; normalization remains disabled by default.

## [v0.12.3] - 2026-09-11

This maintenance release strengthens reliability and test coverage. Around
seven hundred new unit tests drive previously uncovered logic through real
substitutes rather than mocked operating-system calls, and the suite is now
isolated from user directories and passes on Windows.

### Fixed

- A unit-test run no longer writes utterance rows into the real local
  analytics database, so it can no longer skew `stenographer stats`.

## [v0.12.2] - 2026-09-11

This release makes cancellation easier to reach and improves the project’s
documentation and distribution structure. The library, CLI, and overlay code
were reorganized, unused experimental code was dropped, and the packaged
distribution was simplified.

### Added

- Press `Escape` to cancel an active recording or delivery. The audio and
  transcript are discarded, and nothing is pasted.
- Adds the GitHub Pages site and a new user guide.

### Removed

- Removes the separate desktop settings application while preserving local
  configuration, models, analytics, and logs.

## [v0.12.1] - 2026-09-11

This release adds private numeric usage statistics and makes the default
hotkey workflow more flexible. It also rebuilds logging and diagnostics, and
tidies native packaging and Windows portability checks.

### Added

- Adds durable local analytics and the `stenographer stats` command for
  viewing, exporting, and deleting numeric dictation statistics.
- Adds an independent desktop settings and analytics application.
- Makes hybrid hotkey mode the default: hold to speak, or tap to latch a
  recording.
- Adds `setup --default` for writing an annotated default configuration.
- Adds queue-backed structured logging with a per-utterance record, a
  separate log for the overlay helper, and a doctor report that lists both
  log files and the daemon log's recent errors.

### Fixed

- The overlay now stays up as Transcribing from key release until the paste
  lands, instead of disappearing on a warm dictation and returning as
  Delivering.
- Corrects diagnostics reporting and Linux runtime behavior in the X11
  overlay backend, hotkey handling, and notifications, and tells an
  unreadable log file from a missing one.

## [v0.11.6] - 2026-08-24

Installing and keeping a Linux installation current is now simpler.

### Added

- Adds a curl-piped quick installer for verified Linux x86_64 and AArch64
  release bundles.
- The installer verifies SHA-256 checksums and supports leaving the service
  stopped for later configuration.
- Adds opt-out update notices based on a metadata-only GitHub release check,
  at most once per day. Dictation data is never sent.

## [v0.11.5] - 2026-08-24

This maintenance release consolidates host-specific behavior behind the
platform contract and prepares the project for broader portability. Linux
overlay backends, capability handling, CLI console behavior, and pure
decision logic were reorganized without changing intended behavior.

### Fixed

- The `doctor` summary of missing capabilities now uses the same labels as
  the report rows instead of raw internal field names.

## [v0.11.0] - 2026-08-22

This release improves feedback customization and isolates operating-system
integration from the dictation core. Linux integrations moved behind a
platform boundary, with a packaging guard that keeps every sound pack
complete in the wheel and the standalone bundle.

### Added

- Adds selectable sound packs, including `legacy`, `warm-desk`,
  `soft-electronic`, and `minimal-ui`, with preview and custom-pack support.

### Fixed

- Selects the X11 overlay backend when the Wayland probe does not succeed.
- Standardizes key-binding names across input providers, so the default
  `KEY_RIGHTCTRL` binding validates even where the provider previously
  supplied no key table.

## [v0.10.0] - 2026-08-22

This major release reauthors the dictation stack around a smaller, more
portable set of components. The legacy package tree, its development
automation, and the release tooling were replaced along the way.

### Added

- Adds the reworked audio capture, transcription worker, paste delivery,
  lifecycle overlay, daemon, `doctor`, and `devices` flows.
- Adds interactive setup with microphone spectrum-floor calibration.
- Adds hotkey hotplug recovery, safer modifier handling, and stronger runtime
  recovery boundaries.
- Ships a standalone per-user Linux bundle and installer, including native
  shell completions.

## [v0.9.5] - 2026-08-02

Incremental dictation is more responsive during pauses and more tolerant of
slow or failed decoding. The ASR, configuration, overlay, systemd, and
transcript delivery internals were restructured without changing intended
behavior.

### Added

- Adds `asr.cpu_threads` and timeout controls for incremental work.
- Adds `stenographer bench --incremental` for replaying and measuring
  incremental transcription.

### Fixed

- Skips redundant re-decodes during pauses, trims sustained silent tails, and
  reuses valid interim results when recording ends.
- Improves recovery from slow or failed incremental decoding and filters weak
  or hallucinated flushed tails.

## [v0.9.4] - 2026-07-24

This release makes silence handling and release installation safer.

### Added

- Adds an audio-energy gate, Silero VAD, hallucination protection, and bounded
  generation for speech surrounded by silence.
- Improves checksum and download reporting in the update and install flows.
- Adds opt-in startup update notices in the HUD, with desktop notification
  fallback.
- Adds `scripts/reinstall.sh` for rebuilding and reinstalling development
  bundles.

### Fixed

- A recording that ends in silence discards the provisional preview instead of
  delivering it.
- Forced shutdown hides the notification and reserves time for the
  transcription worker to stop, so a slow stop no longer strands work that was
  already submitted.
- A development build no longer offers a release that is not newer as an
  available update.

## [v0.9.3] - 2026-07-20

This maintenance release protects active dictation through shutdown and keeps
the HUD stable.

### Added

- Shows the running version in the HUD header.

### Fixed

- Drains active work during bounded shutdown so a final utterance is not lost.
- Clipboard-paste mode preserves the complete transcript beyond the configured
  output character cap.
- Keeps the HUD at one size, so a preview no longer resizes or repositions it.

## [v0.9.2] - 2026-07-19

This release adds live feedback while recording and more control over
transcription vocabulary.

### Added

- Adds incremental transcript previews and a GTK layer-shell HUD with a live
  microphone spectrum.
- Adds `stenographer status` for checking daemon state.
- Adds `asr.hotwords` and `asr.initial_prompt` for vocabulary biasing.
- Uses `faster-whisper-medium.en` as the default model; the default model
  download is about 1.5 GB.
- Renames the `output.injection_method` values to `type` and
  `clipboard_paste`; the pre-0.9.2 spellings `text` and `paste` still load,
  with a warning.

### Removed

- Removes `audio.silence_detection`, `audio.silence_rms_threshold`, and
  `audio.silence_duration_seconds`; silence-flushed segmentation is replaced
  by the always-on incremental decoding path, which bounds its own decode
  window.

### Fixed

- A recording that fails to start no longer wedges transcription, which left
  every later utterance silently untranscribed.
- The overlay no longer stays on the listening state after a failed recording.
- A failed final decode delivers the transcript committed so far instead of
  discarding the dictation.

## [v0.8.3] - 2026-07-17

Live streaming dictation is now available, with delivery and hotkey controls
built around it.

### Added

- Pastes confirmed words at the cursor while recording continues, with
  append-only spacing and capitalization formatting.
- Trims tail silence using the recording’s noise floor and bounds streaming
  decode windows.
- Adds configurable push-to-talk, toggle, and hybrid trigger modes, with
  push-to-talk as the default for this release.
- Uses Right Alt as the default dictation hotkey instead of Right Ctrl; an
  explicitly configured binding is unchanged.
- Defaults `formatting.paragraph_pause_seconds` to 0, so a pause while
  dictating no longer inserts a line break.
- Adds `transcribe --raw` for verbatim output that skips the formatting
  heuristics.

### Fixed

- Copies the full transcript to the clipboard when live delta delivery fails,
  instead of losing the text that could not be pasted.
- An error while stopping the recorder, or a shutdown mid-utterance, no longer
  wedges transcription and silently drops every later dictation.
- A failed final decode no longer discards the last committed words while the
  success cue plays.
- The output character cap no longer skips one long update and then resumes,
  which left a hole in the delivered text.
- Copying text no longer hangs, and only the paste path touches the primary
  selection, so dictating no longer clobbers a mouse selection.
- The frozen release binary resolves its dynamically imported submodules.
- `run stop` and `run disable` name the replacement top-level commands instead
  of failing with an argument error.

## [v0.7.7] - 2026-07-09

The default installation now uses a smaller speech model.

### Added

- Uses `faster-distil-whisper-medium.en` as the default model, reducing the
  default download from roughly 3 GB to roughly 800 MB.
- Offers a choice among the benchmarked models during installation, names the
  chosen model and its size in the download prompt, and writes the choice into
  the configuration.
- Adds desktop notification dependencies to the documented and automated
  installation setup.

## [v0.7.5] - 2026-07-09

Installing and managing the user service now happens from the release bundle.

### Added

- Adds a self-bootstrapping installer that downloads and verifies the
  standalone binary, configures the installation, offers dependency setup,
  downloads the model, and prepares systemd.
- Adds dedicated `enable`, `start`, `stop`, and `disable` commands.
- Adds `enable --no-start` for configuring an installation before starting the
  service.

### Removed

- Removes `run stop` and `run disable`; `run` is now only the foreground
  daemon, and the new top-level commands control the service.

## [v0.7.3] - 2026-07-08

This maintenance release fixes release-status reporting. No application
behavior changed.

### Fixed

- The release badge now updates after a successful release workflow completes,
  avoiding stale status caused by workflow timing.

## [v0.7.2] - 2026-07-08

This release adds tools for measuring transcription and begins the live
streaming work.

### Added

- Adds the `stenographer bench` command for comparing models, beam sizes,
  compute types, word error rate, and streaming behavior.
- Adds an experimental LocalAgreement streaming transcription API.
- Adds a combined `build-and-install.sh` helper and automatic release-build
  reporting.

## [v0.6.10] - 2026-07-06

Hotkey control and cancellation are more reliable for everyday dictation.

### Added

- Latches a recording with a double tap of the hotkey; holding the hotkey
  still speaks push-to-talk, and a single stray tap discards the tentative
  recording instead of latching one.
- Adds a configurable cancel chord, the hotkey plus `Escape` by default,
  that discards the recording in progress.
- Cancellation also aborts in-flight transcription and clears queued work,
  so nothing from the cancelled dictation is delivered.
- Adds bash shell completion, installed by the bundled installer.
- Adds cancel and discard audio cues.

### Fixed

- Recovers from a missed key release instead of leaving the hotkey chord
  wedged and unable to start another recording.
- Filters probable silence from streaming and clipboard output, so phrases
  hallucinated over silence no longer reach the cursor or the paste.

## [v0.6.9] - 2026-07-03

Long recordings and quiet input are handled more safely.

### Added

- Flushes the speech captured so far for transcription after a pause and
  keeps recording, so a long dictation arrives in pieces instead of
  waiting for the key release.
- Caps a single recording at ten minutes by default, configurable, and
  reports the truncation instead of letting the buffer grow without bound.
- Applies the silence threshold to every flushed chunk, so likely
  hallucinations produced over silence are dropped before injection or
  clipboard delivery.
- Delivers the transcript by copying it to the clipboard and sending
  Ctrl+V, the default for the new `output.injection_method` setting; set it
  to `text` to type at the cursor as segments decode instead.
- Adds the `devices` command for listing audio input devices.
- Sends desktop notifications from a background thread, so a slow
  notification daemon cannot stall recording, and updates the dictation
  notification in place.
- Rotates the log file at 5 MB and keeps three previous files.

### Fixed

- Hiding the dictation notification no longer dismisses another
  application's notification.
- When only some transcript segments reached the cursor, the full
  transcript is no longer typed again on top of them; the complete text is
  placed on the clipboard instead.
- `stenographer update` reports that the installation is already current
  instead of failing when no newer release exists.
- Installing an update moves the new bundle into place with a rename pair
  and restores the previous installation if the move fails.
- A pip or pipx installation is refused with a hint to upgrade through that
  tool, rather than overwriting unrelated files beside the launcher.
- Log files record how long a transcript was rather than what it said.

## [v0.6.8] - 2026-07-01

Idle model memory use is lower and model lifecycle state is easier to
follow.

### Added

- Loads the speech model on first daemon use and unloads it after a
  configurable idle period, returning the model's memory to the operating
  system.
- Reports model loading, readiness, and idle unloading through
  notifications and audio cues.

## [v0.6.7] - 2026-07-01

Audio setup now works across a wider range of devices.

### Added

- Falls back through other sample rates and channel counts when the device
  rejects the configured one, resampling the capture back to the
  configured rate before transcription.
- Shows a startup notification naming the hotkey to press.
- `doctor` reports the microphone device name instead of only whether a
  microphone was found.

### Fixed

- Desktop notifications recover on their own after a failed attempt
  instead of staying off for the life of the daemon.
- Standalone packaging keeps system PortAudio libraries external and finds
  them at runtime, so the bundled binary uses the host's audio stack.

## [v0.6.6] - 2026-07-01

Standalone HTTPS operations now use a bundled certificate authority
bundle, which ships inside frozen builds.

### Fixed

- Update checks and downloads verify TLS against the bundled authority
  bundle, so a standalone installation still reaches the release server on
  a host whose certificate store is incomplete.

## [v0.6.5] - 2026-07-01

Standalone builds and update validation are more tolerant of packaging
details. The build script now refreshes its editable install first, so the
bundle carries the current version.

### Fixed

- Accepts a valid frozen bundle whose internal PyInstaller layout differs
  from the layout the update check previously assumed, instead of
  rejecting the downloaded release.

## [v0.6.4] - 2026-07-01

Release update verification now handles archived assets correctly.

### Fixed

- Fixes checksum-file discovery when a release asset includes an archive
  suffix such as `.tar.gz`, so an update can be verified and installed.

## [v0.6.3] - 2026-07-01

Upgrades and installation guidance are clearer. The release-build workflow
and its status reporting were also cleaned up.

### Added

- `stenographer update` now displays the available release notes.
- Documents the bundled build-and-install path and systemd user-service
  setup.

## [v0.6.1] - 2026-07-01

Initial packaged release of local, offline Wayland dictation.

### Added

- Adds configurable hotkeys, Whisper transcription, clipboard and paste
  delivery, audio cues, notifications, and systemd user-service
  integration.
- Adds standalone binary packaging and installation support.
- Keeps dictation local while making model downloads explicit.
