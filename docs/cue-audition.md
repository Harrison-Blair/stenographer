# Sound-pack generation and audition

The four production packs live under `src/stenographer/assets/sounds/` in this
fixed order: `legacy`, `warm-desk`, `soft-electronic`, and `minimal-ui`. The
four files in `legacy` are the original bundled WAVs, unchanged. The other 12
WAVs are original deterministic procedural renders from the checked-in
`scripts/cue_audition.py`; no external samples are loaded or incorporated.

Prove that all checked-in generated WAVs match a fresh in-memory render byte for
byte:

```sh
.venv/bin/python scripts/cue_audition.py --verify-packaged
```

To generate a scratch audition set and independently verify it:

```sh
.venv/bin/python scripts/cue_audition.py --generate --verify-bytes
```

Scratch output is ignored by Git under `build/cue-audition/`. Its `manifest.json`
records PCM format, durations, peak and RMS levels, SHA-256 checksums, generator
version, and the procedural-source declaration. The candidates contain no
external audio samples and are licensed `GPL-3.0-or-later` with the project.
The 48 kHz, mono, 16-bit PCM profile follows the broadly supported WAV profile
in the [freedesktop sound-theme specification](https://specifications.freedesktop.org/sound-theme/latest-single/).
[Kenney UI Audio](https://kenney.nl/assets/ui-audio) and the
[KDE Ocean Sound Theme](https://github.com/KDE/ocean-sound-theme) were listening
references only.

The production CLI previews the four cues in `record_start`, `record_stop`,
`delivered`, `error` order with silent pauses and never changes the selection:

```sh
for pack in legacy warm-desk soft-electronic minimal-ui; do
    .venv/bin/stenographer sounds --preview "${pack}"
done
```

It uses the configured volume. When cues are muted or volume is zero, explicit
preview uses 0.6 without changing either setting. The development tool can also
compare the original legacy pack with scratch renders at a chosen volume:

```sh
.venv/bin/python scripts/cue_audition.py \
  --family warm-desk \
  --output-directory build/cue-audition \
  --generate \
  --verify-bytes \
  --play
```

Every generated file is 48 kHz mono 16-bit uncompressed PCM and shorter than
300 ms. The more permissive custom-pack validator also accepts 1–2 channels,
8–192 kHz, and 8/16/24/32-bit PCM. Packaged and release guards require exactly
four bundled directories × exactly four cue names; manifests and scratch output
are never included below the production sound root.

Listen on headphones, laptop speakers, and desktop speakers. Check that each
four-cue family communicates start, stop, delivery, and error without becoming
sharp or tiring. Start should be the shortest and quietest; error should remain
distinctive without sounding substantially louder.

Before accepting a pack, select it and test its start cue through real microphone capture.
A silent press and release must still end quietly: no transcription, paste, or
error cue. Run the full integration smoke suite, including the real player check
for all four bundled packs and a filesystem custom pack, then perform real hold
and toggle dictation on the target machine before merging to `main`.
