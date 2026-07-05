<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 01 — Hotkey

## Dependencies

- **Reads:** `00-overview.md` (HotkeyListener, Session, glossary).
- **Reads:** `07-configuration.md` (`hotkey.*` keys).
- **Reads:** `09-error-handling.md` (capability matrix for `input`
  group, runtime error policy).
- **Reads:** `10-packaging.md` (`evdev` dep, system deps for
  `/dev/input/event*`).
- **Calls into:** `04-audio-feedback.md` (fires `ptt_on`, `ptt_off`,
  `toggle_on`, `toggle_off` cues).
- **Calls into:** `02-audio-capture.md` (starts / stops Recorder).
- **Blocks:** `08-process-model.md` constructs the HotkeyListener.

## Goal

Specify the `HotkeyListener` component and the hybrid PTT /
double-tap-toggle state machine that decides what a press means. A
single keybinding is arbitrated by press duration and tap count:

- **hold >= 0.5 s** => **push-to-talk mode** (one beep high on
  keydown, two beeps high on keyup; recording while held).
- **double-tap** (two short presses within the double-tap window) =>
  **toggle mode** (one beep low on latch, two beeps low off). The
  recording latches on and ends on a later press-and-release of the
  chord.
- **single short tap** => the recording that tentatively started on
  keydown is **discarded** when the double-tap window expires (soft
  `discard` cue, nothing transcribed). This makes stray taps of the
  hotkey harmless.

A separate **cancel chord** — the main chord held plus
`cfg.hotkey.cancel_binding` (default `KEY_ESC`) — discards the active
recording, aborts in-flight transcription, and clears the utterance
queue (see `05-text-output.md`; text already typed at the cursor is
not undone).

The default threshold `0.5` is `cfg.hotkey.toggle_threshold_seconds`;
the double-tap window `0.35` is `cfg.hotkey.double_tap_window_seconds`.

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
`evdev.UINPUT_KEY_NAMES` is accepted. The parser MUST reject
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

States: `IDLE`, `RECORDING_PTT`, `PENDING_TAP`, `TOGGLE_LATCHED`,
`TOGGLE_STOPPING`.
Variables:
- `press_start: float | None` — wall-clock time of the current
  keydown, or `None` if not pressed.
- `chord_active: bool` — whether all keys of the chord are currently
  held.
- `consumed: bool` — the current chord press was swallowed by a
  cancel; its keyup must not stop/reclassify/start anything.
- `pending_generation: int` — bumped whenever a pending-tap wait is
  invalidated; stale timeout events are ignored.

### Transitions

| Event | From | To | Side effects |
|---|---|---|---|
| `keydown` (chord starts) | `IDLE` | `RECORDING_PTT` | `press_start = now`; `recorder.start()`; `feedback.play("ptt_on")` |
| `keyup`, duration >= threshold | `RECORDING_PTT` | `IDLE` | `recorder.stop()` and transcribe; `feedback.play("ptt_off")` |
| `keyup`, duration < threshold | `RECORDING_PTT` | `PENDING_TAP` | recording continues; listener arms the double-tap window timer (no cue) |
| `keydown` (second tap) | `PENDING_TAP` | `TOGGLE_LATCHED` | generation bump (stale timer becomes a noop); `feedback.play("toggle_on")` |
| window timeout (current generation) | `PENDING_TAP` | `IDLE` | `recorder.stop()`, samples discarded; `feedback.play("discard")` |
| window timeout (stale generation) | any | (unchanged) | ignored |
| `keyup` (release of the latching tap, any duration) | `TOGGLE_LATCHED` | `TOGGLE_LATCHED` | ignored — the latch committed on keydown |
| `keydown` | `TOGGLE_LATCHED` | `TOGGLE_STOPPING` | no side effect; stop fires on the release so the cancel chord can intervene |
| `keyup` | `TOGGLE_STOPPING` | `IDLE` | `recorder.stop()` and transcribe; `feedback.play("toggle_off")` |
| cancel (chord held + cancel key) | `RECORDING_PTT` / `TOGGLE_LATCHED` / `TOGGLE_STOPPING` | `IDLE` | `consumed = true`; `session.cancel_all()`; `feedback.play("cancel")` |
| cancel (chord held) | `IDLE` | `IDLE` | idempotent: `session.cancel_all()` again (covers cancel while only processing) |
| cancel (chord not held) | any | (unchanged) | ignored (bare cancel-key presses pass through) |
| `keyup` while `consumed` | any | (unchanged) | clears `consumed`; otherwise ignored |
| Any `keydown` outside chord | any | (unchanged) | ignored |
| Any `keyup` of a non-chord key | any | (unchanged) | ignored (the chord is not complete yet; see below) |

**Chord bookkeeping.** A chord with N keys is considered "started"
on the N-th keydown (the moment all N keys are down) and "ended" on
the first keyup of any of the N keys. If the user releases one chord
key and re-presses it without releasing the others, the chord stays
down and the `keydown` / `keyup` events for that key are debounced
(ignored) until the chord truly ends. This is the same logic most
DE shortcut handlers use.

**Double-tap window timer.** The state machine stays pure: it never
arms a timer. On the `await_double_tap` action the listener arms a
`threading.Timer` for `double_tap_window_seconds`, capturing
`pending_generation` at arming time, and delivers the expiry as
`on_timeout(generation)` through the ordinary dispatch lock. A second
keydown racing the expiry is safe: both serialize on the lock, and
whichever loses sees either a stale generation or a non-pending state
and no-ops. `Timer.cancel()` is only hygiene.

**Cancel chord.** The cancel key (default `KEY_ESC`) fires only when
every key of the main chord is physically held at the cancel keydown.
Pressing it marks the current chord press consumed, so the eventual
chord keyup does nothing. While a latched-toggle recording is
running, the user holds the main chord (which enters
`TOGGLE_STOPPING` without stopping anything) and presses the cancel
key; releasing the chord without the cancel key stops and
transcribes as usual. While the daemon is merely processing (not
recording), pressing the chord starts a fresh recording and the
cancel key then cancels both it and all queued/in-flight processing.

**Stuck keys.** If a keydown (`value == 1`) arrives for a key already
in the shared held set, its release was missed (multi-HID keyboards
can route it to a node we lost). The listener synthesizes a release
followed by a press — recomputing chord state after each — so a
wedged `chord_active` clears and the chord can fire again. Logged at
DEBUG.

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

| Transition                                   | Cue fired    | When                |
|----------------------------------------------|--------------|---------------------|
| `IDLE -> RECORDING_PTT` (chord starts)       | `ptt_on`     | keydown             |
| `RECORDING_PTT -> IDLE` (long release)       | `ptt_off`    | keyup               |
| `PENDING_TAP -> TOGGLE_LATCHED` (second tap) | `toggle_on`  | keydown             |
| `PENDING_TAP -> IDLE` (window expired)       | `discard`    | timer               |
| `TOGGLE_STOPPING -> IDLE`                    | `toggle_off` | keyup               |
| cancel chord fired                           | `cancel`     | cancel-key keydown  |

The recorder's `start()` / `stop()` calls and the cue plays are
synchronous calls into the Session main thread; the state machine
itself runs on the evdev read-loop thread, so all Session methods
MUST be thread-safe. v1 implements this with a single
`threading.RLock` held for the duration of each transition. The lock
is reentrant because the listener's dispatch path already holds the
lock when it invokes session callbacks (e.g. `on_recording_start`),
and the callbacks re-acquire the same lock to guard their own state.
(The critical sections are short — no audio I/O is held under the
lock.)

## Hotkey device disappearance

If `device.read_loop()` returns (e.g. the keyboard is unplugged),
the listener:

1. Logs `hotkey.listener: device <path> disappeared`.
2. Calls `errors.notify_failure("hotkey device lost")`.
3. Attempts to re-acquire a keyboard every 2 s for 30 s.
4. If re-acquisition succeeds, a `PENDING_TAP` recording is
   discarded (its timer would be orphaned by the reset), then the
   state machine resets to `IDLE` and resumes.
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
    def on_keydown(self, timestamp: float) -> Transition: ...
    def on_keyup(self, timestamp: float) -> Transition: ...
    def on_timeout(self, generation: int) -> Transition: ...
    def on_cancel(self) -> Transition: ...
    def force_discard(self) -> Transition: ...  # device loss during PENDING_TAP
    @property
    def state(self) -> Literal[
        "IDLE", "RECORDING_PTT", "PENDING_TAP", "TOGGLE_LATCHED", "TOGGLE_STOPPING"
    ]: ...
    @property
    def pending_generation(self) -> int: ...
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

- Should `ptt_on` be played on keydown even if the user immediately
  releases before the threshold? Yes: the recording must start
  immediately for PTT responsiveness, and the cue confirms it. A lone
  short tap is discarded when the double-tap window expires (soft
  `discard` cue).
