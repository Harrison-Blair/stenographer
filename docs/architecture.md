# Code organization

Handwritten production code lives under `src/stenographer/lib/`, `cli/`, and
`overlay/`. Package version metadata remains at the root, and resources retain
their existing paths in `assets/`.

## Library engines

`lib/` imports neither CLI nor overlay modules. Its domains own:

- `contracts/`: the single lifecycle enum, status sink interface, null sink,
  publication policy, and shared spectrum shape used by configuration.
- `config/`: frozen models, defaults, validation, preservation, backups,
  conflict detection, and saving. No configuration migration is needed.
- `audio/`, `hotkey/`, and `transcribe/`: recording and measurements, binding
  vocabulary and chord tracking, ASR workers, formatting, and utterance records.
- `delivery/` and `sounds/`: confirmed clipboard delivery, release waiting,
  sound-pack validation, preview, and feedback policy.
- `daemon/`: recording lifecycle, locking, publication order, pipeline execution,
  telemetry, and exactly-once utterance completion. The CLI injects a status sink.
- `analytics/`, `diagnostics/`, `logging/`, and `updates/`: numeric history,
  core capability checks and collection, private logging, and update notices.
- `platform/`: host service contracts and lazy Linux, Windows, and macOS providers.

Each ordinary class has a dedicated file without standalone helpers. Related
records may share a file; related exceptions live in their domain's `errors.py`.
Functions are grouped by responsibility. Initializers remain small and import-safe.

## CLI workflows

`cli:main` remains the console entry point. `cli/entry.py` performs frozen-process
bootstrap before argument parsing and recognizes the private `_overlay` entry.
`cli/parser.py` assembles registrations owned by each command package. Command
handlers load their dependencies lazily.

Commands own their prompts, terminal output, consent, and follow-up actions.
`cli/run/` owns startup and its banner. `cli/setup/` owns quick/default setup and
calibration prompts; `cli/sounds/` owns interactive pack selection and preview.
The model download and stats operations have their own subcommand packages.
`cli/shared/` combines independent core and display capability results for reports.

## Optional overlay

`overlay/protocol/` owns protocol-v4 messages, codecs, stream framing, and display
ordering. `overlay/supervision/` owns mailbox, restart, and timeout policy;
`overlay/helper/` owns helper execution and backend selection.
`overlay/rendering/` owns geometry, frames, animation, and display reduction.
`overlay/spectrum/` owns visual analysis and calibration, while the speech gate
remains in `lib/audio/`. Helper logging is isolated in `overlay/logging/`.

`overlay/platform/` owns display providers, helper transport, availability
information, native backends, and generated Wayland bindings. Linux still prefers
layer-shell before XWayland. Windows and macOS still report display unavailability;
this reorganization adds no native platform support. Core providers expose no
display-backend selection or display-specific guidance.

## Verification and packaging

Tests mirror the owning domains. `tests/test_architecture.py` checks the dependency
direction, native boundaries, and class-file rules; generated protocol code is
excluded from handwritten-code rules. Platform isolation tests import portable
modules with native dependencies blocked. Regression assertions retain cancellation,
clipboard confirmation, cue/capture ordering, logging privacy, and completion rules.

The wheel includes the unchanged assets and generated bindings at
`overlay/platform/linux/backends/protocols/`. The frozen build collects the
package recursively, including lazy imports and multiprocessing child entry code.
See [BUILD.md](../BUILD.md) and [native acceptance](../packaging/NATIVE-ACCEPTANCE.md)
for packaging and real-machine release gates. Sandbox checks never access the
microphone or run integration tests.
