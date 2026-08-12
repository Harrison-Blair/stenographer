# Reauthor the stenographer GUI on a distro-agnostic stack

> This is the single source of truth for the GUI reauthor. It is executed by
> `workflows/gui-reauthor.workflow.js` (Workflow tool): an Opus 4.8 implementer per milestone plus
> two pairs of adversarial reviewers and a bounded fix loop. Run with
> `Workflow({scriptPath: "workflows/gui-reauthor.workflow.js", args: {milestones: ["M1"]}})`,
> or omit `args` to run all five milestones sequentially. Recommended: one milestone per
> invocation, with the manual integration checks (see Verification) done between M2/M3/M4.

## Context

The status HUD (visualizer) is a GTK4 + gtk4-layer-shell helper process driven over JSON-lines by
the daemon. It works on Arch/Hyprland but is unfixable on Ubuntu 24.04 / GNOME, for layered
reasons:

- `PyGObject>=3.50` (unconditional core dep) needs `girepository-2.0`, which Ubuntu 24.04 doesn't
  ship — pip install fails before GTK is even reached.
- `packaging/install.sh` requests `gir1.2-gtk4layershell-1.0`, which doesn't exist in the 24.04
  archive — the apt step hard-fails.
- The frozen bundle ships its own GTK4 but `LD_PRELOAD`s the *host's* `libgtk4-layer-shell`
  against it (`overlay_client.py:331-347`) — mixed-ABI by design.
- Even fixed, GNOME/Mutter has never implemented wlr-layer-shell, so the overlay can **never**
  appear on stock Ubuntu. Only X11 (XWayland) windows can self-position there.
- Beyond the GUI: `wtype` injection cannot work on GNOME (Mutter lacks
  `zwp_virtual_keyboard_manager_v1`); the reported "no input" on Ubuntu is likely the evdev
  `input`-group requirement (existing `doctor` check).

**Goal:** GUI and install require zero thought on any distro/compositor; same look and features.

## Decisions (made with the repo owner — do not relitigate)

1. **Stack — custom dual-backend, pip-only; PyGObject/GTK fully removed.**
   - Shared software renderer: **Pillow** draws the whole HUD frame (RGBA).
   - Backend 1: native `zwlr_layer_shell_v1` via **pywayland** (Sway/Hyprland/KDE) — identical
     semantics to today.
   - Backend 2: X11 override-redirect ARGB window via **python-xlib** over XWayland (GNOME path).
   - Selection at helper startup: layer-shell → X11 → `ERROR:` line → existing notify-send degrade.
2. **Scope:** GUI reauthor + `doctor` improvements + injection fallback to clipboard. No ydotool.
3. **Minimal diff:** `indicator.py`, `overlay_client.py` writer/coalescing, `spectrum.py`,
   `protocol.py`, `notification.py`, session wiring, and the JSON-lines protocol are preserved;
   the class name `LayerShellOverlay` is kept (renaming touches ~10 sites for zero behavior).
4. **Sans font:** bundle DejaVuSans.ttf (~750 KB, free license) into `assets/fonts/` next to
   Caveat — deterministic rendering everywhere, simplest code.
5. **Provisional preview styling:** alpha-only (58% vs 92%); the italic slant is dropped
   (Pillow has no cheap oblique). Only intended visual deviation.
6. **Cue semantics for clipboard-only delivery:** when the transcript reaches only the clipboard
   (any injection mode): **no success cue, no error cue, and a desktop notification on every such
   utterance** ("typing isn't supported here; transcript copied — paste with Ctrl+V /
   Shift+Insert"). Text at the cursor → success cue as today; text reached nothing → error cue as
   today.

## Invariants to preserve

- Helper spawn contract: frozen `[sys.executable, "_visualizer"]` (pre-argparse dispatch,
  `cli.py:762-765`), source `python -m stenographer.visualizer --child`; child prints `READY`
  (3 s window) or `ERROR: …` on stdout; stdin JSON-lines: `configure {margin_bottom, band_count,
  icon_path}`, `state {state, timeout_ms, label?}` (incl. `hidden`; timeout auto-hide with
  generation guard), `levels`, `preview {stable, provisional}`, `preview_clear`, `quit`; EOF ⇒ quit.
- Daemon never assumes the overlay exists; preview text never goes to `notify-send`.
- `[visualizer]` config keys unchanged; no new config keys.
- SPDX headers; ruff (line 100, py314); `.venv/bin/pytest -m "not integration"` green after every
  milestone. All tooling through the repo venv (`.venv/bin/...`), never system python.
- Uncommitted GTK fix on `dev` (`_reserve_preview_height` + test), if still present, is
  superseded — discard via `git checkout --` before M1 (it targets a GTK API that no longer
  exists after this work).

## Implementation design

### New files (all under `src/stenographer/visualizer/` unless noted)

- **`render.py`** — `HudRenderer(band_count, version, icon_path, font_path, scale=1)` with
  `render(label, preview=(stable, provisional), levels) -> PIL.Image` (RGBA, straight alpha) and
  `size` property. Absorbs `_trim_preview` (moved verbatim, tests repointed) and the preview
  geometry constants. Layout mirrors the GTK box model: padding 12/18/14/18; 76 px icon; header
  row (Caveat 20 px wght 600 `#f2f2f2` status + sans 11 px 40%-alpha version); preview block
  42 chars / 2 lines / 34 px reserved (sans 12 px; stable `(247,247,247,235)`, provisional
  `(242,242,242,148)`); spectrum 280×54 (bar math identical to `_draw_spectrum`: gap 5, baseline
  h−8, min bar 3×2, fill `(255,255,255,173)`). Canvas ≈ 470×207 incl. shadow margins; backends
  apply `effective_margin = max(0, margin_bottom − 36)` so the *box* sits `margin_bottom` px up.
  - Static chrome (shadow via GaussianBlur σ≈14 offset +8, rounded rect `(45,45,48,209)` +
    1 px `(255,255,255,51)` border, radius 20, icon) rendered **once** at 4× and LANCZOS-downscaled
    (ImageDraw shapes aren't antialiased), cached; per frame = copy + text + bars. ~1 ms/frame at
    60 Hz — full-frame rerender, no dirty regions.
  - Fonts: Caveat via `ImageFont.truetype(...).set_variation_by_axes([600])` with fallback to
    default axis on `OSError/NotImplementedError`; bundled DejaVuSans for sans. Keep the existing
    `STENOGRAPHER_FONT_PATH` contract; add `STENOGRAPHER_SANS_FONT_PATH` alongside it.
  - `_wrap_segments(stable, provisional, max_width_px, font)` — greedy word wrap by
    `font.getlength`, carries the stable/provisional boundary through wraps, truncates to 2 lines
    with trailing "…".
  - `to_premultiplied_bgra(img) -> bytes` (numpy) — shared by both backends (Wayland ARGB8888 and
    composited 32-bit X windows are both premultiplied BGRA little-endian).
- **`backend_wayland.py`** — connect, require `wl_compositor`/`wl_shm`/`zwlr_layer_shell_v1`
  globals else raise `BackendUnavailable(reason)`; layer surface: `Layer.overlay`, namespace
  `stenographer-spectrum`, anchor bottom, `set_size(w,h)`, exclusive zone 0, keyboard none,
  bottom margin; empty `wl_region` input region (click-through); wait for `configure` + ack
  before first attach. `memfd_create` + one `wl_shm` pool + **two ARGB8888 buffers** (track
  `wl_buffer.release`; both busy ⇒ drop frame). Push-on-message, no frame callbacks (rate already
  bounded to 60 Hz upstream). **Hide = commit a fully transparent buffer** (null-buffer attach
  unmaps and forces a re-configure handshake — documented trade-off). Scale: integer
  `buffer_scale` from `preferred_buffer_scale` (wl_compositor ≥ v6) else `surface.enter` output
  scale else 1; on change rebuild buffers + renderer. Fractional-scale-v1/viewporter explicitly
  out of scope (comment as upgrade path).
- **`backend_x11.py`** — requires `DISPLAY` + successful `Xlib.display.Display()` connect (GNOME
  spawns XWayland on demand) else `BackendUnavailable`. Depth-32 TrueColor visual with explicit
  `colormap` + `border_pixel` (else BadMatch), `override_redirect=1`,
  `_NET_WM_WINDOW_TYPE_NOTIFICATION` + `_NET_WM_STATE_ABOVE`; click-through via XShape empty
  Input region; position bottom-center of the RandR primary monitor (fallback: root geometry),
  re-queried on show. Frames via `put_image` **chunked into ≤64-row strips** (core protocol
  request cap 262140 bytes; python-xlib does not auto-split); keep last frame, re-put on Expose.
  Hide/show = unmap/map + raise. Render at scale 1 (XWayland pixels are pre-scaled; known
  softness on HiDPI GNOME — accepted for the fallback path).
- **`protocols/`** — vendored pywayland-scanner output for `wlr-layer-shell-unstable-v1` and
  `xdg-shell` (needed only because `get_popup` references `XdgPopup`). **Scanner emits sibling
  imports (`from .wayland import …`) that MUST be rewritten to `from pywayland.protocol.wayland
  import …`; never vendor a duplicate `wayland.py`** (duplicate interface classes break proxy
  marshalling). `tools/generate_wayland_protocols.py` + committed protocol XMLs do the
  regeneration + rewrite + SPDX stamping (dev-time only). Vendored modules ride the existing
  `collect_submodules("stenographer")` in the PyInstaller spec.
- **`src/stenographer/wayland.py`** — ~40-line `wayland_globals() -> frozenset[str] | None`
  registry scan (connect → registry → roundtrip → disconnect), shared by capabilities, doctor,
  and `probe_backend()`.

### Rewritten / modified

- **`overlay_app.py`** — full rewrite of `run_overlay_process()` (name/module kept so `cli.py`
  and `__init__.py` don't change): parse env → `_select_backend()` (try wayland factory, then
  x11, collecting `BackendUnavailable` reasons; all fail ⇒ `print(f"ERROR: {reasons}")`, exit 1)
  → `print("READY")` → single-threaded `select([stdin, backend.fileno()])` loop with
  `timeout = next hide deadline`. Backend `typing.Protocol`: `fileno/pump/present/hide/
  set_margin/scale/close`; backend imports function-local (same discipline as today's GTK).
  stdin read via `os.read` + manual line split (never `readline()`); EOF ⇒ quit. Message handling
  mirrors GTK `_handle_command` semantics exactly, incl. generation-guarded auto-hide (extracted
  `_HideTimer` with injected clock for tests) and zeroed bars on non-listening states. Wayland fd
  discipline: `flush()` before select, `read()` + `dispatch(block=False)` on readable (pywayland
  exposes `get_fd/read/dispatch/flush` — verified).
- **`overlay_client.py`** — `probe()` body becomes: `WAYLAND_DISPLAY` set and `pywayland`
  importable, or `DISPLAY` set and `Xlib` importable (cheap, no display connect; existing
  monkeypatch-based tests keep working). Delete the LD_PRELOAD block + `ctypes.util` import from
  `_build_environment()` (keep font-path env vars). Add `probe_backend() -> str | None`
  ("layer-shell" | "x11" | None — real registry scan / X connect, doctor-only). Docstring updates.
- **`capabilities.py`** — `has_paste_trigger = has_wtype and has_virtual_keyboard` where
  `has_virtual_keyboard` comes from `wayland_globals()` (`None` ⇒ permissive, so a broken scan
  can never disable working wtype); call `errors.degrade_capability(...)` (first real caller)
  when wtype exists but the protocol is missing. Dataclass shape unchanged.
- **`output/delivery.py`** — introduce a delivery outcome distinguishing *injected* /
  *clipboard-only* / *failed* (smallest form: keep `deliver_final` bool for failed vs not, plus a
  `on_clipboard_fallback` callback; or return a 3-value enum — implementer picks the smaller diff
  against `session.py`'s cue logic). Clipboard-only ⇒ suppress both cues and fire the
  notification **every time**, in both `type` mode (delivery.py:96-100 branch) and
  `clipboard_paste` mode (delivery.py:128-132 branch).
- **`notification.py`** — `show_clipboard_fallback()` following the existing `show_*`/`_enqueue`
  pattern; **`indicator.py`** — thin passthrough (bypasses HUD deliberately; notify-send works
  everywhere); **`session.py`** — wire the callback/outcome into cue selection (~5-10 lines).
- **`cli.py`** — doctor: replace the `GTK spectrum` line with `HUD backend: layer-shell | x11
  (XWayland) | NO (notify-send fallback)`; add `virtual keyboard:` and `injection:` lines derived
  from one `wayland_globals()` scan; add `XWayland/DISPLAY:` line. **Exit-code semantics
  unchanged** (required gate stays input group + mic + asr model → 78; injection degradation is
  informational because clipboard delivery exists).
- **Assets** — add `assets/fonts/DejaVuSans.ttf` + license file; pyproject wheel include already
  globs `*.ttf` (verify the license-file glob).

### Packaging / CI / docs

- `pyproject.toml`: remove `PyGObject>=3.50`; add `pillow>=11.0`, `pywayland>=0.4.18`,
  `python-xlib>=0.33`.
- `packaging/stenographer.spec`: delete `gi.*` hiddenimports + `hooksconfig={"gi": ...}`; add
  `pywayland`, `pywayland.protocol.wayland`, `Xlib` hiddenimports; rewrite header comment
  (system deps: libevdev, libportaudio, libwayland-client; python-xlib needs no libX11). Bundle
  should shrink dramatically (GTK/GI stack was the largest contributor of 515 MB).
- `packaging/install.sh`: drop all GTK/gir packages from apt/dnf/pacman lists (fixes the 24.04
  hard-fail) and the `ldconfig | grep libgtk4-layer-shell` check.
- CI (`ci.yml`, `release.yml`): replace GTK/GI/cairo dev packages with `libwayland-dev libffi-dev
  pkg-config` — required because **pywayland has no cp314 wheel; it builds from sdist** (needs
  libwayland headers). Frozen-bundle end users are unaffected; document the caveat for
  source-install users in README.
- Docs: README dependency table/wording, BUILD.md (+ protocol-regen section), CLAUDE.md,
  AGENTS.md. Final sweep: `grep -ri 'gtk\|pygobject\|gi\.repository'` over src/, packaging/,
  .github/, *.md.

### Tests

- Survive unchanged: spectrum tests, overlay_client writer/coalescing/wedged-pipe/degrade tests
  (drop one obsolete `ctypes.util.find_library` monkeypatch line), indicator fallback tests,
  session/capture/config suites.
- Deleted: Pango markup, font-map, cairo-context, and the uncommitted GTK size-request tests.
- Rewritten: frozen-env test asserts font-path vars present and **no LD_PRELOAD manipulation**.
- New: renderer structural-pixel tests (corner transparent, box-center ≈ (45,45,48), bars react
  to levels, label changes bytes, missing-Caveat fallback); `_wrap_segments` boundary/truncation;
  `to_premultiplied_bgra` known-pixel; `_select_backend` with fake factories (first ok / first
  unavailable / both fail ⇒ combined ERROR); helper loop with fake backend + real pipe stdin
  (present/hide sequences, hidden suppresses presents, EOF quits, hide-timer generation guard via
  injected clock); X11 `_iter_put_chunks` request-cap math; capabilities truth table with
  monkeypatched `wayland_globals` (incl. `None` ⇒ permissive); doctor output lines; delivery
  outcome/notification tests for both modes (notifier fires each clipboard-only delivery, no cue,
  copy-failure still errors). Per repo policy, new behavioral tests must be shown to fail against
  broken/stubbed code before passing.

### Known risks (carried into review prompts)

1. Vendored protocol import rewrite (sibling → `pywayland.protocol.wayland`) is mandatory.
2. Pillow `set_variation_by_axes` guard for exotic FreeType builds.
3. Premultiplied-alpha fringing on Mutter — converter is the single adjustment point (verify M3).
4. Layer-shell hide via transparent buffer (null-buffer unmap semantics documented).
5. Mutter stacking of override-redirect windows over fullscreen surfaces is best-effort.
6. Exact python-xlib enum names (`shape_rectangles`, `randr.get_monitors`) verified at
   implementation time.
7. PEP 758 unparenthesized `except` exists in current code — py314-only, fine either style.

## Milestones (each leaves pytest + ruff green, then is committed)

- **M1 — Renderer (pure addition).** Pillow dep; `render.py` (+ `_trim_preview` move with a
  temporary import shim in `overlay_app.py`); DejaVuSans asset; renderer/wrap/conversion tests.
  Discard the uncommitted GTK fix first if present.
- **M2 — Wayland backend + helper rewrite + GTK removal.** `protocols/` vendoring + regen script;
  `backend_wayland.py`; `overlay_app.py` rewrite; `overlay_client.py` probe/env changes; delete
  GTK code + GTK-only tests; pyproject swap PyGObject → pywayland + python-xlib; **CI apt swap in
  the same milestone** (CI must build the pywayland sdist).
- **M3 — X11 backend.** `backend_x11.py`; selector registers it second; chunking/selection tests.
- **M4 — Doctor + injection fallback.** `wayland.py`; capabilities gate + `degrade_capability`;
  delivery outcome + per-utterance notification wiring (session/notification/indicator); doctor
  lines + `probe_backend`; associated tests.
- **M5 — Packaging + docs.** Spec, install.sh, README/BUILD/CLAUDE/AGENTS, GTK-reference sweep,
  bundle-size check.

## Verification

- Per milestone (automated by the workflow gate): `.venv/bin/ruff check .`,
  `.venv/bin/ruff format --check .`, `.venv/bin/pytest -m "not integration"`; new behavioral
  tests demonstrated to fail against broken code first.
- **Arch/Hyprland (manual, after M2/M3):** doctor shows `HUD backend: layer-shell`,
  `virtual keyboard: yes`; HUD bottom-center at `margin_bottom`, side-by-side visual comparison
  with a GTK screenshot; click-through; preview wrap/trim during long dictation; auto-hide 5 s /
  10 s + generation guard; 2× monitor crispness; scratch-venv without pywayland falls back to
  X11; killing the helper mid-session degrades to notify-send; clean shutdown.
- **Ubuntu/GNOME (manual, after M3/M4):** doctor shows `HUD backend: x11 (XWayland)`,
  `virtual keyboard: NO`, `injection: clipboard fallback`; HUD renders with correct alpha (no
  black box) on the primary monitor above a maximized window; click-through; dictation ends with
  **no cue** + notification each utterance + transcript on clipboard; frozen bundle installed via
  `install.sh` end-to-end; record bundle-size drop (baseline 515 MB).
- Final: `stenographer bench` / real dictation sanity on the Arch machine to confirm no daemon
  regressions (HUD is out-of-process, but spawn/env changed).
