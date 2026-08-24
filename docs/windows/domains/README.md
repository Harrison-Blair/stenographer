# Windows Feature Parity — Domain Plans

Status: **implementation plan** (2026-08-24). This directory turns
`docs/windows/SCOPE.md` — the first-pass scope — into seven per-domain plans
whose work items can be handed to an implementer one at a time.

Read order: this file first, then the domain doc you are working in. This file
is the **single home** for anything true of more than one domain: the settled
decisions (§D), the designed source tree (§T), the phase map (§F), the binding
principles (§P), and the work-item format (§W). Domain docs cite those anchors
and never restate them. If you find yourself copying a fact from here into a
domain doc, that is the DRY violation this structure exists to prevent.

| Domain doc | Blast area | Touches core? |
|---|---|---|
| [`input-hotkey.md`](input-hotkey.md) | key table, LL hook listener | no |
| [`delivery.md`](delivery.md) | clipboard, `SendInput` paste chord | no |
| [`feedback.md`](feedback.md) | cue player, toast notifier | no |
| [`lifecycle-and-service.md`](lifecycle-and-service.md) | mutex, console handler, dirs, logon task | no |
| [`overlay.md`](overlay.md) | layered-window helper backend | **yes** — `status.py` |
| [`diagnostics-and-setup.md`](diagnostics-and-setup.md) | host probe, doctor text, binding capture | **yes** — `cli/doctor.py`, `cli/setup.py` |
| [`packaging-ci-and-test-gate.md`](packaging-ci-and-test-gate.md) | bundle, installer, workflows, merge gate | **yes** — repo-wide |

The split is by **blast radius**, not by protocol surface: the four "contained"
domains can be built and reverted inside `platform/windows/` alone as far as
`src/` is concerned, while the three core-touching domains modify `src/` code
that Linux also executes and therefore carry a heavier review and test burden
(§P7, §F).

**"Contained" is a claim about `src/`, not about the test tree.** Every domain
that replaces a stubbed provider method must also edit
`tests/platform/test_platform.py` (§P11), which Linux CI runs — so no domain is
fully self-contained, and every such item falls in the "both suites" row of §D8.

---

## §D. Settled decisions

SCOPE.md §9 listed eight decisions that `docs/reauthor.md` reserves to the
owner and required to be recorded before implementation. All eight were settled
on 2026-08-24 and are recorded in the `docs/reauthor.md` Windows amendment of
that date. They are restated here **only** as the citable index for domain
docs; `docs/reauthor.md` remains the source of truth, and a conflict between
the two is a bug in this file.

### D1 — Paste chord is Ctrl+V

The Windows `KeyInjector` sends **Ctrl+V**, not Linux's Shift+Insert.

Rationale: reauthor decision 7 chose Shift+Insert as "the most broadly honored
paste chord across toolkits" — a claim about GTK/Qt and Linux terminals, where
Ctrl+V is frequently bound to something else and paste is Ctrl+Shift+V. On
Windows the claim inverts: Ctrl+V is the OS-wide convention including cmd.exe
and Windows Terminal, while Shift+Insert is honored inconsistently in WinUI3,
UWP and some Electron apps — and its failure mode is a silent no-op
indistinguishable from a bad paste. The single-path property of decision 7 is
preserved; only the constant differs. Owner: [`delivery.md`](delivery.md).

*Mechanism refined 2026-08-24 while planning:* the chord is sent as a **virtual
key**, never with `KEYEVENTF_SCANCODE`, which SCOPE.md §2 prescribed. A scan code
injects the physical key *position*, which the foreground layout re-maps — under
Dvorak the chord becomes Ctrl+K and the paste silently no-ops, exactly the
failure mode this decision was settled to avoid. Note this is the deliberate
**inverse** of D5's listener, which resolves scan-code-first *because* it wants
physical position so a binding survives a layout change. The two must not be
harmonized.

### D2 — Autostart is a `schtasks` logon task with no auto-restart

A real Windows Service runs in session 0 and cannot install global hooks, call
`SendInput`, or reach the user-session clipboard, so the daemon must be a
user-session process. The analog is `schtasks /create /sc ONLOGON`.

Task Scheduler cannot condition restart on an exit code, so the choice was
between no auto-restart and a supervisor wrapper. **No auto-restart** is
chosen: it honors "78 = don't restart" trivially, adds no new process to the
tree, and is a strict subset of the wrapper design — adding the wrapper later
changes only the task's action path.

Accepted regression, to be documented in user-facing text: the systemd unit's
`Restart=on-failure` has no Windows equivalent, so a transient crash leaves
dictation dead until next logon. Owner:
[`lifecycle-and-service.md`](lifecycle-and-service.md).

> Correcting SCOPE.md §4: it describes the Linux policy as "print the systemctl
> command, never install". `scripts/install.sh` (lines 195–206) installs,
> enables and starts the unit. The print-only policy belongs to `doctor` and
> `setup`, which only ever restart an already-installed unit. The Windows
> installer should therefore *register* the logon task, matching `install.sh`.

> Correcting SCOPE.md §4 second option: enabling Task Scheduler's native
> restart is not a cheap variant. `schtasks` command-line flags cannot set
> restart-on-failure; it requires generating and registering a task XML
> document, making it more work than the plain logon task, not less — and it
> would still retry an exit-78 daemon.

### D3 — Toast notifications via a PowerShell subprocess

`Notifier.error()` shells out to `powershell -NoProfile -NonInteractive
-Command <toast script>` via non-blocking `Popen`, exactly mirroring
`platform/linux/notify.py`: a pure `build_notify_command` unit target, DEVNULL
redirection, `OSError` swallowed to `log.debug`, and a `shutil.which` probe.

Accepted cost: an unregistered application has no AppUserModelID, so the toast
borrows the shell-registered PowerShell AUMID and is branded "Windows
PowerShell". This is cosmetic and appears only on the errors-only path. The
~1 s launch latency is irrelevant there. `windows-toasts` was rejected to hold
the near-zero-new-dependency verdict of SCOPE.md §6. Owner:
[`feedback.md`](feedback.md).

*Mechanism refined 2026-08-24 while planning:* `build_notify_command()` takes
**no message argument**, unlike its Linux counterpart. PowerShell `-Command`
takes source code, so interpolating a caller-supplied string into it is arbitrary
code execution. The message crosses only through `STENOGRAPHER_TOAST_MESSAGE` in
the child environment, truncated and control-character-stripped — which also
makes §P9 a structural guarantee rather than a matter of discipline.

### D4 — Cues play in-process via sounddevice

`CuePlayer` reads the WAV with `soundfile`, scales by `feedback.volume` with
numpy, and plays through `sounddevice`. `play()` is fire-and-forget; `preview()`
blocks to completion under a bounded join and raises on failure.

This departs from the Linux spawn-a-player pattern deliberately: `winsound` is
stdlib but has no volume control, which would silently break the
`feedback.volume` config contract, and a PowerShell `SoundPlayer` subprocess has
neither volume control nor acceptable latency for a `record_start` cue.

The departure costs `build_play_command`, the pure unit target. Per §P5 it must
be replaced, not dropped: `prepare_cue(samples, volume) -> ndarray` is the new
pure target. Two consequences to design around: an output stream is opened
alongside the retained capture stream (valid on WASAPI shared mode, but a new
PortAudio failure surface), and `sounddevice`'s playback is a singleton, so a
second cue cuts off the first. Owner: [`feedback.md`](feedback.md).

*Mechanism refined 2026-08-24 while planning:* cue **resampling is mandatory,
not contingent**. The bundled `legacy` pack is 44100 Hz while `warm-desk`,
`soft-electronic` and `minimal-ui` are 48000 Hz, so on a 48000 shared-mode mix a
`legacy` user hits rate rejection every time; custom packs may be any rate. A
second pure target, `resample_cue_linear`, joins `prepare_cue`, reached through a
single retry that mirrors `Recorder`'s existing one-recovery precedent.

### D5 — `WH_KEYBOARD_LL` listener; `hotkey.device` warns once

The listener is a low-level keyboard hook: global, non-grabbing, installed on a
dedicated thread running a `GetMessage` pump and stopped with
`PostThreadMessage(WM_QUIT)`. The hook callback translates VK → evdev code and
**enqueues only**; a separate dispatch thread feeds `ChordTracker._key_event()`.
See §P4 — this is an invariant, not an implementation preference.

`hotkey_devices()` returns `[]` because a hook is global and cannot select a
device; `setup` already degrades on an empty list. When `hotkey.device` is
non-empty the Windows listener logs **one** warning that the key is Linux-only
and ignored, mirroring the sound-pack "warn once and fall back" precedent. The
conditional lives in the provider: `config.py` must not learn what platform it
is on (§P2). Raw Input remains a documented deferred door for per-device
selection. Owner: [`input-hotkey.md`](input-hotkey.md).

*Two mechanism refinements 2026-08-24 while planning.* (a) **Auto-repeat must be
mapped to evdev value 2 in the provider.** Windows delivers auto-repeat as bare
repeated `WM_KEYDOWN`; `ChordTracker._key_event` reads a second value-1 for an
already-held code as a lost release and answers with stop-then-start, so holding
the push-to-talk key would storm the daemon for as long as the user spoke. Value
2 already returns early at `hotkey.py:149` — the branch exists for exactly this.
(b) **Translation resolves scan-code-first with VK as fallback.** evdev codes are
identical to AT set-1 scan codes across the base block (`KEY_A` 30 = `0x1E`), but
diverge for extended keys — including `KEY_RIGHTCTRL` (97 vs `E0 1D`), which is
the *default* binding. VK codes are layout-dependent; scan codes are physical.

### D6 — Overlay vocabulary grows additively; protocol stays v4

Add `Backend.WIN32 = "win32"` and any needed `UnavailableReason` members to
`status.py`. `PROTOCOL_VERSION` stays **4**.

Rationale: the decoder rejects `version != PROTOCOL_VERSION` — exact equality,
not a minimum — and the helper is re-exec'd from the same installation, so
daemon and helper are always one build and no mixed-version case exists for a
bump to protect against. `UnavailableReason` has already grown to twelve
members including backend-specific ones (`X_ARGB_UNAVAILABLE`,
`REQUIRED_GLOBALS_MISSING`) with no bump; this follows that precedent. Owner:
[`overlay.md`](overlay.md).

### D7 — Medium integrity by default, `/rl HIGHEST` as opt-in

The logon task registers at medium integrity by default. The task builder takes
an `elevated` flag; `setup` offers it with the trade stated and `doctor` reports
which mode is active.

Rationale: UIPI blocks a medium-integrity hook from seeing keystrokes typed
into a higher-integrity foreground window, and blocks `SendInput` into one — so
dictation silently dies while an elevated window has focus. The clipboard write
is *not* blocked, so the existing "text is on your clipboard" recovery path
still works; the failure is annoying, not data-losing. Elevating by default
would fix it but breaks the no-admin per-user install model, strictly worsens
the antivirus heuristic match of SCOPE.md risk 2 (unsigned bundle + global
keyboard hook + running as administrator), and turns any daemon compromise into
an admin-level one — the same reasoning that put the Linux daemon in a *user*
unit rather than running as root. Elevation is also not "always works": the UAC
consent dialog is on a System-integrity secure desktop that only a signed
`uiAccess` binary can reach.

Authenticode signing is recorded as the real long-term fix for both this and
the antivirus risk; it is a cost decision, not a code one. Owners:
[`lifecycle-and-service.md`](lifecycle-and-service.md) (the flag),
[`diagnostics-and-setup.md`](diagnostics-and-setup.md) (the reporting),
[`packaging-ci-and-test-gate.md`](packaging-ci-and-test-gate.md) (signing).

### D8 — Per-platform merge gate, scoped by changed paths

AGENTS.md rule 10 requires the integration smoke suite green **on a real
machine** before any `dev` → `main` merge. A real Windows machine is available
for the merge loop, so the gate is genuine rather than aspirational.

The rule is scoped by what a change touches:

| Paths changed | Required real-machine suite |
|---|---|
| only `src/stenographer/platform/linux/**`, `tests/platform/linux/**` | Linux |
| only `src/stenographer/platform/windows/**`, `tests/platform/windows/**` | Windows |
| anything else — core, `cli/**`, `overlay/**`, `status.py`, `packaging/**`, `scripts/**`, `pyproject.toml` | **both** |

The table is deliberately mechanical rather than a judgement call, and it
reuses the core/provider boundary AGENTS.md already enforces. Owner:
[`packaging-ci-and-test-gate.md`](packaging-ci-and-test-gate.md).

---

## §T. Designed source tree

End state after all four phases. `NEW` = file does not exist today; `EDIT` =
existing file changed; unmarked = referenced but unchanged. Domain docs restate
only their own rows, with the per-item file lists that §W requires.

```
src/stenographer/
├── status.py                              EDIT  D6: additive Backend.WIN32 + reasons
├── overlay/
│   ├── supervisor.py                      EDIT  portable helper read loop (see below)
│   └── win32.py                           NEW   layered click-through helper backend
├── cli/
│   ├── doctor.py                          EDIT  HostText-driven labels and hints
│   ├── setup.py                           EDIT  Windows service + elevation prompts
│   └── setup_config.py                    EDIT  rule-9 preservation on Windows
├── platform/
│   ├── base.py                            EDIT  HostText type + host_text() Protocol
│   └── linux/probe.py                     EDIT  Linux HostText table
└── platform/windows/
    ├── __init__.py                        EDIT  provider wiring; lazy imports only
    ├── vk.py                              NEW   generated KEY_* ↔ VK table (pure)
    ├── hotkey.py                          NEW   WH_KEYBOARD_LL listener + dispatch queue
    ├── binding_capture.py                 NEW   temporary hook + console quieting
    ├── sendinput.py                       NEW   Ctrl+V chord via SendInput scan codes
    ├── clipboard.py                       NEW   CF_UNICODETEXT write + read-back confirm
    ├── cues.py                            NEW   in-process sounddevice playback
    ├── notify.py                          NEW   PowerShell toast subprocess
    ├── lock.py                            NEW   CreateMutexW named mutex
    ├── process.py                         NEW   child env + SetConsoleCtrlHandler
    ├── service.py                         NEW   schtasks builder/parser/restart
    ├── probe.py                           NEW   HostProbe for doctor
    └── overlay.py                         NEW   OverlayBackendSpec for win32

scripts/
├── gen_vk_keycodes.py                     NEW   generator for platform/windows/vk.py
├── merge_gate.py                          NEW   D8 path-to-suite rule, executable
└── install.ps1                            NEW   per-user installer, %LOCALAPPDATA%\Programs

packaging/
├── spec_support.py                        NEW   per-OS spec inputs, importable and pure
├── stenographer.spec                      EDIT  per-OS conditionals
├── hook-sounddevice.py                    EDIT  deregistered on win32 (see below)
└── rthooks/                               EDIT  Linux-only paths guarded

tests/
├── platform/test_platform.py              EDIT  stub-conformance assertions (see §P11)
├── platform/test_vk_table.py              NEW   pure VK drift test, runs on both CI legs
└── platform/windows/                      NEW   Windows-only tests, not collected elsewhere

.github/workflows/
├── build.yml                              EDIT  windows-latest bundle job
├── release.yml                            EDIT  Windows zip + checksums
└── test.yml                               EDIT  merge-gate job
```

Three rows above are corrections that the domain plans established against real
code, not restatements of SCOPE.md:

- **`overlay/supervisor.py` is not portable.** SCOPE.md §3 says the daemon-side
  supervisor "carries over untouched". It does not: line 437 registers the
  helper's stdout **pipe** with `selectors.DefaultSelector()`, and on Windows
  that is `SelectSelector`, whose `select()` accepts sockets only. The loop
  raises on its first turn. Degradation is graceful (two wasted helper spawns,
  then disabled), so D6's severability claim survives — but this is a core edit
  Linux executes.
- **`packaging/hook-sounddevice.py` does not carry over.** It excludes
  `libportaudio*`; on Windows the `sounddevice` wheel's bundled DLL is the only
  copy. It is deregistered on win32 rather than edited. Separately,
  `stenographer.spec` calls `find_spec("pywayland._ffi")` and raises at **module
  scope**, so it aborts every Windows build before `Analysis` runs.
- **`tests/platform/test_platform.py` is shared and Linux-run.** See §P11.

§T covers `src/`, `scripts/`, `packaging/`, `tests/` and workflows. Documentation
and per-item test files beyond those listed are enumerated in the domain docs
that own them, not here.

`platform/windows/__init__.py` today already implements the directory policy
(`%APPDATA%` / `%LOCALAPPDATA%` honouring `XDG_*`), returns `StaticKeyTable`,
`[]` from `hotkey_devices`, `NullNotifier`, `None` from `cue_player`, `{}` from
`helper_spawn_kwargs`, `()` from `overlay_backends`, and raises
`UnsupportedPlatformError` from the rest. Every work item that lands replaces
one of those degraded returns; until it does, the degraded return is the
correct behavior and must keep working.

## §F. Phase map

SCOPE.md §8's four severable phases map to work items, not to whole domains —
several domains contribute to more than one phase.

| Phase | Delivers | Contributing domains |
|---|---|---|
| 1 — dictation parity | hold hotkey, speak, text appears; overlay stays disabled via `NullStatusSink` | input-hotkey (all), delivery (all), feedback (all), lifecycle (mutex, console handler, dirs), diagnostics (probe, hint text) |
| 2 — setup + service | binding capture, console quieting, logon task | lifecycle (service, elevation flag), diagnostics (binding capture, setup prompts) |
| 3 — overlay | layered-window helper | overlay (all) |
| 4 — packaging, CI, gate | bundle, installer, release artifacts, smoke suite, D8 gate | packaging (all) |

Each phase is independently mergeable behind the existing "unavailable"
degradation. Work items carry their phase in the header line (§W).

## §P. Principles binding every domain

These are the rules an implementer can violate without the code failing to run.
Each is stated so a reviewer can check it. Domain docs add only domain-specific
principles and cite these by number.

- **P1 — Lazy provider imports.** Every `WindowsPlatform` method lazy-imports
  its sibling backend inside the method body. `platform/__init__.py` and both
  provider `__init__.py` files stay importable on every OS. `stenographer
  --help` must never load `ctypes.windll`, `msvcrt`, `sounddevice`, or any
  Win32 surface. The Linux bundle `collect_submodules` the Windows package, so
  an import-time Win32 call breaks the Linux build too.
- **P2 — Core stays host-blind.** Core modules never import
  `stenographer.platform.windows`, `msvcrt`, or a Win32 module, not even
  lazily. Platform conditionals live in the provider — `config.py` never learns
  what OS it is on (see D5). `tests/platform/test_core_isolation.py` is the
  enforcement.
- **P3 — Add capability via the Protocol.** A new host capability gets a
  stdlib-only signature in `platform/base.py` first, then implementations in
  both providers — Linux real, Windows real or explicitly unavailable — then
  core wiring through `current_platform()` or `Daemon.build`. Never the reverse
  order.
- **P4 — The hook callback only enqueues.** Windows silently removes low-level
  hooks whose callbacks exceed the (~300 ms) budget. The hook callback
  translates and enqueues; nothing else. No locks, no I/O, no logging, no
  dispatch. This is the same class of invariant as reauthor §4.8's
  "the PortAudio callback only copies blocks" and must be treated with the same
  severity in review.
- **P5 — Every backend keeps a pure unit target.** If a mechanism change
  deletes one (D4 deletes `build_play_command`), the plan must name its
  replacement. Command builders, output parsers, code translation tables, retry
  policies and scaling functions are all extractable; the `ctypes` call is not
  and is never the thing under unit test.
- **P6 — No mock theater.** Per AGENTS.md rule 4, never mock `SendInput`,
  `OpenClipboard`, `CreateMutexW`, `subprocess` or `schtasks` to assert a call
  would have happened. If a behavior is only testable by mocking, extract the
  pure part (P5) and cover the rest in the real-machine smoke suite. A new pure
  test counts only once it has been *seen to fail* against broken behavior.
- **P7 — Core-touching changes cost more.** The three core-touching domains
  modify code Linux executes. Every such item states what Linux behavior must
  remain byte-identical and names the Linux test that proves it, and it falls
  under the "both suites" row of D8.
- **P8 — Preserve the delivery invariant.** The paste chord fires only after a
  *confirmed* clipboard copy and physical hotkey release. A failed or
  unconfirmed copy never fires the chord. Windows clipboard retry policy is
  bounded by this, not the other way round.
- **P9 — Privacy holds across the boundary.** Logs carry numeric and structural
  metrics and transcript *lengths* only. Toast text is a short caller-supplied
  error string, never transcript content. Overlay IPC carries fixed lifecycle
  metadata, a model-loading boolean and 18 quantized levels — never transcript,
  raw audio, device or model names, config values, or detailed errors.
- **P11 — Replacing a stub method edits a shared, Linux-run test.**
  `tests/platform/test_platform.py` asserts that `WindowsPlatform` raises
  `UnsupportedPlatformError` from `key_injector`, `clipboard_writer`,
  `single_instance_lock` and `hotkey_listener`, that `overlay_backends() == ()`,
  and that the probe reports `not (key_injector_ok or hotkey_access_ok or
  clipboard_ok)`. It lives in `tests/platform/`, **not** `tests/platform/linux/`,
  so Linux CI runs it. Every item that implements one of those surfaces must
  update it in the same commit, guarded so the Linux assertions still hold, and
  is therefore a "both suites" change under §D8 regardless of its domain's
  blast-area row. The same applies to `tests/cli/test_doctor.py`, which
  `unit-windows` collects today and which asserts Linux prose — it passes on
  Windows now only because `doctor` emits Linux prose there.
- **P10 — SPDX and tooling.** `SPDX-License-Identifier: GPL-3.0-or-later` on
  every new source file; Python 3.12 target; ruff line length 100 with rules
  `E,F,I,B,UP,N,SIM,RUF`; all tooling through `.venv/bin/`.

## §W. Work-item format

Every item in a domain doc's *Functional criteria* section uses this shape, and
its *Acceptance criteria* section keys off the same ID. An item is sized as one
module plus its tests — small enough to hand to one implementer unattended,
large enough to be independently reviewable.

```
### WIN-<DOMAIN>-<NN> — <imperative title>
Phase: <1-4>   Depends on: <ID, ID | none>
Files: <path (NEW|EDIT)>, ...
Pure tests: <test path::name>, ...
Smoke: <smoke case name | none>
Done when: <single observable statement>
```

Rules the format enforces:

- **IDs are stable.** Once published, an ID is never reused or renumbered; a
  dropped item is struck through with a reason, keeping the dependency
  references of other items valid.
- **`Depends on` is the build order.** It references item IDs, including
  across domains. The union of all `Depends on` edges must be acyclic; the
  phase map (§F) is a coarser view of the same graph and must not contradict it.
- **`Pure tests` names files and test functions**, not intentions, so the item
  is complete only when those tests exist and have been seen to fail against
  broken behavior (P6).
- **`Smoke` names a case in the Windows integration suite** or `none` with a
  justification in the domain's Acceptance criteria. Items whose only
  verification would be a mock name `none` and explain why (P6).
- **`Done when` is one observable statement**, checkable by someone who did not
  write the code.

---

## §X. Open refinement pending owner sign-off

One item surfaced during planning that changes a settled decision rather than
its mechanism, so it is recorded here rather than applied:

**§D8's third row, read literally, makes a `docs/` typo require both
real-machine smoke suites.** "Anything else" was written to be mechanical and
fail-closed, and it is — but paths that cannot affect runtime behaviour
(`docs/**`, `*.md` outside the package, `LICENSE`) gate two machine runs for no
signal, which is how gates come to be skipped. `scripts/merge_gate.py`
(WIN-PKG-08) implements the rule exactly as written pending a decision. The
proposed carve-out is a fourth row: documentation-only changes require neither
suite. Owner decision; until then the fail-closed reading stands.
