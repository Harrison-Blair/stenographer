<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 04 — Audio feedback

## Dependencies

- **Reads:** `00-overview.md` (Cue, Cue player definitions).
- **Reads:** `07-configuration.md` (`feedback.*` keys).
- **Reads:** `09-error-handling.md` (capability matrix for `pw-play` /
  `paplay`).
- **Reads:** `10-packaging.md` (asset packaging layout, `pw-play` /
  `paplay` system deps).
- **Blocks:** `01-hotkey.md` fires cues from the state machine.
- **Blocks:** `08-process-model.md` constructs the feedback player.

## Goal

Specify the cue system: which cues exist, what they sound like, where
they are loaded from, and how they are played. The component is
`stenographer.audio.feedback`.

## Cue catalogue (v1)

Eight cues, named exactly as below. The hotkey state machine
(`01-hotkey.md`), the error helper (`09-error-handling.md`), and the
Session orchestrator (`08-process-model.md`) refer to them by these names.

| Cue name          | Fired by                                  | Audio content (default)                          |
|-------------------|-------------------------------------------|--------------------------------------------------|
| `ptt_on`          | Hotkey state machine, on PTT keydown      | 1 high beep: 880 Hz, 80 ms, -12 dBFS             |
| `ptt_off`         | Hotkey state machine, on PTT keyup        | 2 high beeps: 880 Hz, 80 ms, 60 ms gap, -12 dBFS |
| `toggle_on`       | Hotkey state machine, on toggle-on (keyup)| 1 low beep: 440 Hz, 80 ms, -12 dBFS              |
| `toggle_off`      | Hotkey state machine, on toggle-off (keydown during rec) | 2 low beeps: 440 Hz, 80 ms, 60 ms gap, -12 dBFS |
| `error`           | `errors.notify_failure`                   | 1 low buzz: 220 Hz, 250 ms, -6 dBFS              |
| `transcribe_done` | Session, after successful injection       | (silent in v1)                                   |
| `model_loading`   | Session, on first hotkey press in lazy mode | 3 ascending tones: 440, 554, 660 Hz, 80 ms each, 60 ms gap, -12 dBFS |
| `model_ready`     | Session, when lazy-mode model load completes | 2 quick high beeps: 880 Hz, 60 ms, 40 ms gap, -10 dBFS |

`transcribe_done` is a stub in v1 — the cue exists in the catalogue
and the asset is bundled, but no code path fires it yet. The asset is
a no-op (a 10 ms silent WAV) so the file resolves cleanly.

`model_loading` and `model_ready` are used only when
`cfg.asr.mode == "lazy"`; in eager mode they are never fired.

`v1` ships **pre-rendered WAVs** at the parameters above. The
implementation MAY also generate them on the fly (numpy -> WAV
header) so the asset files are optional; the spec allows either. The
behaviour contract is the *audio content*, not the file format.

## Asset resolution

For a given cue name `N`, the path used is, in order:

1. `cfg.feedback.cues[N]` if non-null and the file is readable.
2. The bundled asset at
   `<site-packages>/stenographer/assets/sounds/<N>.wav`.

If neither exists, the cue is logged at WARNING level and treated as
a no-op for the rest of the session (per `09-error-handling.md`).

## Audio parameters for the bundled assets

| Field         | Value                              |
|---------------|------------------------------------|
| Format        | WAV, PCM, mono                     |
| Sample rate   | 44100 Hz                           |
| Bit depth     | 16-bit signed                      |
| dBFS          | -12 dBFS for beeps, -6 dBFS for the error buzz |
| Frequencies   | as per the catalogue above         |
| Durations     | as per the catalogue above         |
| Gap (multi-beep cues) | 60 ms                          |

The `feedback.volume` config key (0.0 .. 1.0, default 0.6) is
applied **at playback time** by the wrapper, not baked into the
assets.

## Player selection

Resolved once at startup by `Capabilities.probe` (see
`10-packaging.md`):

- If `pw-play` is on `PATH`, use it.
- Else if `paplay` is on `PATH`, use it.
- Else: no feedback. All cue calls are no-ops and log at DEBUG.

The selected player is stored on the `Feedback` instance as
`self._player: Literal["pw-play", "paplay"]`.

## Playback API

```python
# stenographer.audio.feedback
from typing import Literal, Optional
import pathlib

CueName = Literal[
    "ptt_on", "ptt_off", "toggle_on", "toggle_off",
    "error", "transcribe_done", "model_loading", "model_ready",
]

class Feedback:
    def __init__(
        self,
        *,
        player: Optional[Literal["pw-play", "paplay"]],
        asset_root: pathlib.Path,         # site-packages/.../sounds
        override_root: dict[CueName, pathlib.Path],  # from config
        volume: float,                    # 0.0 .. 1.0
        muted: bool,
    ) -> None: ...

    def play(self, name: CueName) -> None:
        """Resolve the cue, then spawn the player. Non-blocking."""

    def close(self) -> None: ...
```

### Non-blocking contract

`play()` MUST return within 50 ms on a warm path. It MUST NOT block
on the audio thread (the player is an out-of-process subprocess).
The implementation spawns the player with
`subprocess.Popen([...], stdout=subprocess.DEVNULL,
stderr=subprocess.DEVNULL, start_new_session=True)` and does not
`wait()`.

If two cues are fired in rapid succession, the second spawns a
second concurrent player. There is no queueing; the sounds
overlap. (Two `ptt_off` beeps back-to-back are intentionally
distinguishable from `toggle_off` by their frequency, not by
sequencing.)

### Subprocess invocation

```
pw-play --volume=<vol> <path>
paplay  <path>     # paplay does not take --volume; volume is applied
                   # by remixing the WAV on disk in a pre-step
```

For `paplay`, because the binary ignores `--volume`, the
implementation applies volume by reading the WAV with
`soundfile.read`, scaling the samples, and writing to a temp file in
`$XDG_RUNTIME_DIR/stenographer-cues/` (default
`/run/user/<uid>/stenographer-cues/`) before invoking `paplay`. The
temp file is unlinked after `paplay` exits (poll with a 100 ms
timeout, max 5 s, then unlink unconditionally).

For `pw-play`, `--volume` is passed directly. The WAV is played
unchanged.

### Volume and mute

- If `cfg.feedback.mute` is `true`, every `play()` call returns
  immediately and does not spawn a subprocess.
- Otherwise `cfg.feedback.volume` (0.0 .. 1.0) is mapped to
  `--volume` linearly (pw-play treats `--volume` as a linear
  multiplier).

## Cue firing policy (cross-reference)

| Trigger                                    | Cue fired        | Source doc           |
|--------------------------------------------|------------------|----------------------|
| Hotkey keydown, decided PTT at keyup       | `ptt_on` (on keydown) | `01-hotkey.md`  |
| Hotkey keyup after PTT                     | `ptt_off`        | `01-hotkey.md`       |
| Hotkey keyup after short press, was IDLE   | `toggle_on`      | `01-hotkey.md`       |
| Hotkey keydown while in toggle recording   | `toggle_off`     | `01-hotkey.md`       |
| `errors.notify_failure`                    | `error`          | `09-error-handling.md` |
| Successful transcript injected (v2)        | `transcribe_done` | `08-process-model.md` |
| First hotkey press in lazy mode            | `model_loading`  | `08-process-model.md` |
| Lazy-mode model load completes             | `model_ready`    | `08-process-model.md` |

## Out of scope (v1)

- Per-cue volume override.
- User-supplied cue packs beyond a single override path per cue.
- Cues triggered by transcription confidence.
- Audio ducking (lowering other apps while a cue plays).

## Open questions

- Should the bundled assets be generated at build time (numpy in a
  `gen_assets.py` script) or committed as binary files? v1: committed
  as binary, the script is optional and lives in
  `scripts/gen_cues.py` if anyone wants to regenerate.
- Should `transcribe_done` fire on every successful injection in v1
  to give the user closure? v1: no (silent in v1 by design).
