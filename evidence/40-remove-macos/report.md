# 40-remove-macos report

Base: `4b8f12f1addd1938a58e9f9a2db49c150be285a1`

Implementation commit: `8d32520`

## Deleted files

- `src/stenographer/lib/platform/macos/__init__.py`
- `src/stenographer/lib/platform/macos/provider.py`
- `src/stenographer/lib/platform/macos/support.py`
- `src/stenographer/overlay/platform/macos/__init__.py`
- `src/stenographer/overlay/platform/macos/guidance.py`
- `src/stenographer/overlay/platform/macos/provider.py`

## Diff against base

These source-change statistics compare the implementation commit with the base. Evidence files are committed separately and are not included.

`git diff --shortstat 4b8f12f1addd1938a58e9f9a2db49c150be285a1 8d32520`:

```text
 23 files changed, 56 insertions(+), 442 deletions(-)
```

`git diff --stat 4b8f12f1addd1938a58e9f9a2db49c150be285a1 8d32520`:

```text
 .github/workflows/native.yml                       |  10 --
 AGENTS.md                                          |   2 +-
 CHANGELOG.md                                       |   4 +
 docs/architecture.md                               |   4 +-
 docs/building.md                                   |  19 ++-
 packaging/NATIVE-ACCEPTANCE.md                     |  14 +-
 scripts/transcription_bench.py                     |   2 +-
 src/stenographer/lib/platform/__init__.py          |   4 -
 src/stenographer/lib/platform/macos/__init__.py    |   1 -
 src/stenographer/lib/platform/macos/provider.py    | 177 ---------------------
 src/stenographer/lib/platform/macos/support.py     |  20 ---
 src/stenographer/lib/platform/resource_probe.py    |   2 -
 src/stenographer/overlay/platform/__init__.py      |   4 -
 .../overlay/platform/macos/__init__.py             |   1 -
 .../overlay/platform/macos/guidance.py             |  10 --
 .../overlay/platform/macos/provider.py             |  21 ---
 tests/conftest.py                                  |   2 +-
 tests/lib/platform/test_diagnostics_host.py        |  17 +-
 tests/lib/platform/test_platform.py                | 138 ++--------------
 tests/lib/platform/test_system_audio.py            |   6 +-
 tests/overlay/platform/test_providers.py           |  33 ++--
 tests/test_architecture.py                         |   2 -
 tests/test_network_guard.py                        |   5 +-
 23 files changed, 56 insertions(+), 442 deletions(-)
```
