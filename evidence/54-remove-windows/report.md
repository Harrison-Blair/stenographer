# 54-remove-windows report

Base: `8fa9459` (`dev`)

Implementation commit: `412edd4`

## Deleted files

- `src/stenographer/lib/platform/windows/__init__.py`
- `src/stenographer/lib/platform/windows/provider.py`
- `src/stenographer/lib/platform/windows/support.py`
- `src/stenographer/overlay/platform/windows/__init__.py`
- `src/stenographer/overlay/platform/windows/guidance.py`
- `src/stenographer/overlay/platform/windows/provider.py`

## Diff against base

These statistics compare the implementation commit with the base. Evidence
files are committed separately and are not included.

`git diff --shortstat 8fa9459 412edd4`:

```text
 41 files changed, 127 insertions(+), 775 deletions(-)
```

`git diff --stat 8fa9459 412edd4`:

```text
 .github/workflows/native.yml                       |   5 -
 .github/workflows/test.yml                         |  20 --
 AGENTS.md                                          |   2 +-
 CHANGELOG.md                                       |   7 +
 docs/architecture.md                               |   9 +-
 docs/building.md                                   |  19 +-
 packaging/NATIVE-ACCEPTANCE.md                     |  16 +-
 src/stenographer/lib/analytics/resources.py        |   4 +-
 src/stenographer/lib/config/models.py              |   4 +-
 src/stenographer/lib/config/validation.py          |   8 +-
 src/stenographer/lib/platform/__init__.py          |   4 -
 src/stenographer/lib/platform/platform.py          |  10 +-
 src/stenographer/lib/platform/windows/__init__.py  |   1 -
 src/stenographer/lib/platform/windows/provider.py  | 197 ---------------
 src/stenographer/lib/platform/windows/support.py   |  29 ---
 src/stenographer/overlay/platform/__init__.py      |   4 -
 .../overlay/platform/helper_process.py             |   5 +-
 .../platform/linux/linux_helper_transport.py       |   3 +-
 .../overlay/platform/windows/__init__.py           |   1 -
 .../overlay/platform/windows/guidance.py           |  10 -
 .../overlay/platform/windows/provider.py           |  27 ---
 tests/cli/doctor/test_report.py                    |  10 +-
 tests/cli/setup/test_workflow.py                   |   9 +-
 tests/conftest.py                                  |  40 +--
 tests/lib/analytics/test_analytics.py              |   4 +-
 tests/lib/config/test_models.py                    |   3 +-
 tests/lib/config/test_persistence.py               |   3 -
 tests/lib/live/test_live_session.py                |   2 +-
 tests/lib/logging/test_pipeline.py                 |   5 +-
 tests/lib/platform/test_core_isolation.py          |  31 +--
 tests/lib/platform/test_diagnostics_host.py        |   2 +-
 tests/lib/platform/test_platform.py                | 270 ++++-----------------
 tests/lib/platform/test_resource_probe.py          |  12 -
 tests/lib/platform/test_system_audio.py            |   9 -
 tests/lib/refine/test_agent_guard.py               |  10 +-
 tests/lib/transcribe/test_model.py                 |   4 +-
 tests/overlay/platform/test_providers.py           |  35 +--
 .../supervision/test_supervisor_lifecycle.py       |   4 +-
 tests/test_architecture.py                         |   5 -
 tests/test_network_guard.py                        |  57 +----
 tests/test_sound_asset_guard.py                    |   2 +-
```

## Remaining grep matches

Command:

```sh
git grep -n -i -E 'windows|win32' -- ':!docs/reference/guru/**' ':!evidence/**'
```

All remaining matches are accounted for:

- `CHANGELOG.md:16,20-21` is the new removal notice. `CHANGELOG.md:61,126,155`
  records older releases and their then-current support. `CHANGELOG.md:340`
  uses “decode windows” for audio time segments.
- `src/stenographer/assets/keycodes.toml:236,814` contains the generated Linux
  input key name `KEY_CYCLEWINDOWS`.
- `src/stenographer/overlay/spectrum/calibration.py:69,89,91,98,107-108,150-154`
  uses “window” for sample buffers and measurement intervals.
- `tests/lib/platform/test_platform.py:55,58-59` and
  `tests/overlay/platform/test_providers.py:56-59` simulate `win32` and verify
  that the factories reject it.
- `tests/overlay/protocol/test_protocol.py:294` uses “display windows” for
  timed display intervals.
- `tests/overlay/spectrum/test_calibration.py:61,248,367` uses “windows” for
  audio sample and capture intervals.

No remaining match selects or implements a Windows platform provider.
