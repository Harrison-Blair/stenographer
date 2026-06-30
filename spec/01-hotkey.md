<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 01 — Hotkey

## Dependencies

- **Reads:** `00-overview.md` (HotkeyListener, Session, glossary).
- **Reads:** `07-configuration.md` (`hotkey.*` keys).
- **Reads:** `09-error-handling.md` (capability matrix for `input`
  group, runtime error policy).
- **Reads:** `10-packaging.md` (`python-evdev` dep, system deps for
  `/dev/input/event*`).
- **Calls into:** `04-audio-feedback.md` (fires `ptt_on`, `ptt_off`,
  `toggle_on`, `toggle_off` cues).
- **Calls into:** `02-audio-capture.md` (starts / stops Recorder).
- **Blocks:** `08-process-model.md` constructs the HotkeyListener.

## Goal

Specify the `HotkeyListener` component and the hybrid PTT / toggle
state machine that decides what a press means. A single keybinding is
arbitrated by the press duration:

- press duration **< 0.5 s** => **toggle mode** (one beep low on,
  two beeps low off).
- press duration **>= 0.5 s** => **push-to-talk mode** (one beep high
  on keydown, two beeps high on keyup).

The default threshold `0.5` is `cfg.hotkey.toggle_threshold_seconds`.

## Hotkey binding grammar

`cfg.hotkey.binding` is a string parsed by `hotkey/binding.py`. v1
accepts either a single evdev key name or a chord.

### Single key

```
"KEY_RIGHTCTRL"        # default
"KEY_F9"
"KEY_PAUSE"
```

### Chord (two or more keys held together)

A chord is a `+`-separated list of evdev key names. The chord is
considered pressed when **all** keys are down and considered released
when **any** key is released.

```
"KEY_LEFTCTRL+KEY_LEFTALT"
"KEY_RIGHTMETA+KEY_SPACE"
```

### Valid key names

The full set of evdev key names from
`python_evdev.UINPUT_KEY_NAMES` is accepted. The parser MUST reject
unknown names at config load time (see `07-configuration.md`
validation rules).

Mouse buttons, gamepad buttons, and consumer keys are rejected in v1.

## Device discovery

The HotkeyListener scans `/dev/input/event*` for a device that:

1. Is a keyboard (`evdev.ecodes.EV_KEY` is in the device's capabilities
   and the device has at least one `KEY_*` capability), AND
2. The user can read (i.e. is in the `input` group, or the device has
   a uaccess tag).

If `cfg.hotkey.device` is set to a specific path, that device is
used instead. If it is `null` (the default) and **no** keyboard
device is accessible, the daemon logs the install hint and exits 78:

```
stenographer: no readable keyboard device found.
  Add your user to the 'input' group:
    sudo usermod -aG input $USER
  then log out and back in.
  Or set stenographer.hotkey.device in your config to a specific
  /dev/input/event* path.
```

### Grabbing

The listener **does NOT** `EVIOCGRAB` the device by default. Doing
so would prevent the user from typing in any application while
stenographer is running, which is wrong: the hotkey is a chord, so
non-chord keystrokes should pass through to the focused window
unmodified.

The listener instead:

1. Opens the device with `evdev.InputDevice(path)`.
2. Reads events in a loop (`device.read_loop()`) on a dedicated
   `threading.Thread`.
3. Filters events to the configured chord; non-chord events are
   ignored.

This is the standard pattern for evdev-based global hotkeys on
Wayland.

## State machine

States: `IDLE`, `RECORDING`.
Variables:
- `press_start: float | None` — wall-clock time of the current
  keydown, or `None` if not pressed.
- `chord_active: bool` — whether all keys of the chord are currently
  held.
- `recording_mode: Literal["ptt", "toggle"]` — only meaningful in
  `RECORDING`.

### Transitions

| Event              | From       | To          | Side effects                                                                                                                                        |
|--------------------|------------|-------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| `keydown` (chord starts) | `IDLE`     | `RECORDING` | `press_start = now`; `recording_mode = "ptt"` (tentative); `recorder.start()`; `feedback.play("ptt_on")`                                            |
| `keyup` (chord ends) | `RECORDING` (ptt) | `IDLE`     | `duration = now - press_start`; if `duration >= threshold`: `recorder.stop()`; `feedback.play("ptt_off")`; `press_start = None`                   |
| `keyup` (chord ends) | `RECORDING` (toggle) | `IDLE`     | `duration = now - press_start`; if `duration < threshold`: this is **toggle-on**; `recording_mode = "toggle"`; `feedback.play("toggle_on")`; do NOT stop recording |
| `keydown` (chord starts) | `RECORDING` (any) | `IDLE`     | `recorder.stop()`; `feedback.play("toggle_off")`; `press_start = None`                                                                              |
| Any `keydown` outside chord | any        | (unchanged) | ignored                                                                                                                                              |
| Any `keyup` of a non-chord key | any        | (unchanged) | ignored (the chord is not complete yet; see below)                                                                                                    |

**Chord bookkeeping.** A chord with N keys is considered "started"
on the N-th keydown (the moment all N keys are down) and "ended" on
the first keyup of any of the N keys. If the user releases one chord
key and re-presses it without releasing the others, the chord stays
down and the `keydown` / `keyup` events for that key are debounced
(ignored) until the chord truly ends. This is the same logic most
DE shortcut handlers use.

**Mode arbitration on keyup.** The threshold is evaluated at keyup
of the chord. If `duration >= cfg.hotkey.toggle_threshold_seconds`,
the press is PTT. Otherwise it is toggle.

- In PTT, the cue `ptt_on` was already played on the original
  keydown; the cue `ptt_off` is played now.
- In toggle, the press is the toggle-on event: the recording
  continues, the mode is set to `"toggle"`, and `toggle_on` is
  played. The recording ends on the next chord `keydown`
  (which plays `toggle_off` and transitions to `IDLE`).

### Anti-repeat

`evdev` reports a continuous stream of "key held" events while a
key is held down. The state machine tracks the **chord**, not
individual keys, so anti-repeat at the chord level is implicit:
`keydown (chord starts)` fires exactly once per press, and
`keyup (chord ends)` fires exactly once per release.

The listener MUST ignore `keydown` events that arrive while
`chord_active` is already `True` (debouncing the stream of repeats
from a stuck key).

### Ignored events

- Mouse movement, mouse buttons, gamepad events.
- `EV_REL` and `EV_ABS` events.
- `EV_MSC` (sync) events.
- `KEY_*` events for keys not in the configured chord.
- `keyup` events for chord keys received while `chord_active` is
  `False` (e.g. an `EV_KEY` event arriving in an unexpected order
  at startup).

## Cue firing summary (cross-reference)

| Transition                                 | Cue fired        | When           |
|--------------------------------------------|------------------|----------------|
| `IDLE -> RECORDING` (chord starts)         | `ptt_on`         | keydown        |
| `RECORDING (ptt) -> IDLE` (chord ends, PTT)| `ptt_off`        | keyup          |
| `RECORDING (ptt) -> RECORDING (toggle)`    | `toggle_on`      | keyup (short)  |
| `RECORDING (any) -> IDLE` (chord restarts) | `toggle_off`     | keydown        |

The recorder's `start()` / `stop()` calls and the cue plays are
synchronous calls into the Session main thread; the state machine
itself runs on the evdev read-loop thread, so all Session methods
MUST be thread-safe. v1 implements this with a single
`threading.Lock` held for the duration of each transition. (The
critical sections are short — no audio I/O is held under the lock.)

## Hotkey device disappearance

If `device.read_loop()` returns (e.g. the keyboard is unplugged),
the listener:

1. Logs `hotkey.listener: device <path> disappeared`.
2. Calls `errors.notify_failure("hotkey device lost")`.
3. Attempts to re-acquire a keyboard every 2 s for 30 s.
4. If re-acquisition succeeds, the state machine resets to `IDLE`
   and resumes.
5. If 30 s elapses without re-acquisition, the daemon exits 1
   (per `09-error-handling.md`).

## API

```python
# stenographer.hotkey.listener
import threading
import evdev

class HotkeyListener:
    def __init__(
        self,
        binding: HotkeyBinding,
        device: evdev.InputDevice,
        state: "HotkeyStateMachine",
        session: "Session",
        feedback: "Feedback",
        threshold_seconds: float,
    ) -> None: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...
```

```python
# stenographer.hotkey.state_machine
class HotkeyStateMachine:
    def on_keydown(self) -> None: ...
    def on_keyup(self) -> None: ...
    @property
    def state(self) -> Literal["IDLE", "RECORDING"]: ...
    @property
    def mode(self) -> Literal["ptt", "toggle"]: ...
    def reset(self) -> None: ...
```

The `HotkeyStateMachine` is a pure object (no I/O) and is unit-tested
in isolation by feeding it `on_keydown` / `on_keyup` calls in
deliberate order. The integration test wires it to a real evdev
device.

## Out of scope (v1)

- Multiple distinct bindings (one PTT, one toggle).
- Per-binding device pinning.
- Long-press (>= 2 s) actions.
- Mouse-button triggers.
- Configurable debounce time (the 0 ms debounce is implicit and
  hardcoded).

## Open questions

- Should the threshold be evaluated live (keydown is followed by an
  immediate 0.5 s timer; if the user keeps holding, we still treat
  the press as PTT) or only at keyup (current spec)? v1: at keyup
  only, since live evaluation would prematurely play `ptt_on` for
  every short toggle press.
- Should `ptt_on` be played on keydown even if the user immediately
  releases before the threshold? Yes, the spec currently says so. If
  the release happens within 1 ms, the user hears a single high
  beep (ptt_on) followed by two high beeps (ptt_off) back to back.
  This is rare in practice; the spec accepts it.
