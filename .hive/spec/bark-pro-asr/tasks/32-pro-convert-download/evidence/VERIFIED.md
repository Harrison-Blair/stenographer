# Task 32 independent verification

Verifier: `t32-verifier-1`. Commit under test: `0154022`.
Verdict: **pass**.

Read the task brief and the full Bark Pro spec. Used the spec's updated
8 GiB rule. The brief's earlier 6 GiB value is superseded by that spec.
No source file, worker evidence file, or plan tracker was changed.

## Verification items

| Item | Result | Observation |
| --- | --- | --- |
| 1. Converter and allowlists | pass | Inspected seeds, fixed threads, metadata, graph failure and exit codes. Real subprocess tests cover usage and missing input. Both real conversions exited 0. Git and Hatch allowlists contain both assets. A wheel contains the converter (14,104 bytes) and constraints (910 bytes). PyInstaller collects the whole assets directory. |
| 2. Pins | pass | Source revision, six source hashes, CPU torch and package versions, lock hash and four output hashes are centralized in `bark_pins.py`. Packages installed on system Python 3.12. Three conversions matched the pinned output hashes. |
| 3. Download | pass | Real CLI download installed ASR and Silero VAD in scratch. Tests cover check order, no network before prerequisite failures, no pip cache, pinned URLs, source/output checks, exit-code messages, cleanup and replacement. A second CLI call reported both models already present without conversion. |
| 4. Manifest/cache | pass | Tests cover malformed manifests, revision mismatch, absent files, no hashing and cache reuse. Installed files matched all six manifest hashes. |
| 5. Doctor/Setup | pass | Tests cover the Doctor warning with the apt fix, collection of the check, and Setup use of the new download. Warning has the plain-text state `warn`. |
| 6. Failing-first pure logic | pass | Reran 232 targeted tests successfully. Nineteen independent mutations in scratch source copies each caused failures. Original checkout source remained unchanged. Details below. |
| 7a. Two real conversions | pass | Both runs produced identical bytes for all four outputs, equal to the pins. |
| 7b. Real CLI install | pass | Exit 0; tree, manifest, attribution, VAD and cleanup checked below. |
| 7c. Resource measurements/cache | pass | Recorded wall time, peak RSS and sampled peak disk. Pip cache did not grow. |
| 7d. Scratch cleanup | pass | Deleted both conversion outputs, source weights, temporary venv, installed scratch ASR/VAD and wheel. Deleted scratch scripts and logs after recording the results. |
| `.venv/bin/ruff check .` | pass | `All checks passed!` |
| `.venv/bin/ruff format --check .` | pass | Final run after scratch cleanup: 801 files already formatted. |
| `.venv/bin/pytest -m "not integration"` | pass | 2781 passed, 2 skipped, 6 deselected in 120.50 seconds. |
| `.venv/bin/stenographer --help` | pass | Exit 0; normal command list and help text. |

The two skips are unchanged tests with absent local data: Silero VAD in the
user data directory and public speaker clips in `tmp/live_audio`. No
integration test, microphone capture, daemon or live recording was run.
The backend and Whisper configuration remain in place for subsequent tasks.
User documentation remains assigned to task D, as recorded in V8.

No visual layout changed. Hub's change maps the new diagnostic identifier to
its existing page. CLI text changes use the spec's text-only board exemption.
No screenshot or visual-layout acceptance is claimed.

## Independent red and green runs

Green command (232 passed):

```sh
.venv/bin/pytest tests/lib/transcribe/test_bark_download.py tests/lib/transcribe/test_bark_converter.py tests/lib/diagnostics/test_additional_checks.py tests/lib/platform/linux/test_subprocess_command_runner.py tests/cli/model/download/test_handler.py tests/cli/setup/test_workflow.py -q
```

For red runs, copied `src/` into a scratch directory. Applied each mutation
separately. Selected that copy with `pytest -o pythonpath=<scratch-src>`.
Each run exited 1 with assertion failures; restored each copy before the
next mutation. No production source was changed.

| Deliberate break | Tests that failed |
| --- | ---: |
| Manifest schema ignored | 1 |
| Revision ignored | 3 |
| Missing listed files accepted | 1 |
| Free-space boundary off by one | 1 |
| Venv failure ignored | 3 |
| Present model rebuilt | 1 |
| Pip cache enabled | 1 |
| Source hash ignored | 1 |
| Output hash ignored | 3 |
| Converter exit codes ignored | 6 |
| Cleanup removed | 16 |
| Atomic output move removed | 3 |
| Converter accepts nonempty output | 1 |
| Converter input check removed | 1 |
| Doctor venv warning removed | 1 |
| Doctor check not collected | 1 |
| VAD download removed | 1 |
| Setup download removed | 2 |
| Quiet subprocess output enabled | 1 |

Green checkout tests passed both the targeted run and the full gate.
The atomic-install assertion detects a missing move; inspection also
confirmed the implementation uses `os.replace` on the same filesystem.

## Real conversions

System interpreter: `/usr/bin/python3`, Python 3.12. Temporary venv used the
pinned CPU index and constraints through the product package-install helper.
Source fetch used the product urllib helper and checked every source hash.
Ran each conversion as:

```text
/usr/bin/time -v <venv>/bin/python -I <asset>/bark_pro_to_sherpa.py <source> <empty-output>
```

| File | Bytes | SHA256 in both runs and installed output |
| --- | ---: | --- |
| encoder.int8.onnx | 630748040 | f111c3ad95637239021cc25b3166c0b6dbb64ab93854f8e9246d56e38b13a29e |
| decoder.int8.onnx | 47658546 | 7c6ce4acf9282c323a5097467699fe2f2863142cff677b84426dc90fde7bd73f |
| joiner.int8.onnx | 6123466 | 21674f569e8f102d6c5e10c222fabea73cafb171bace666f33bb2a1b4d0067a2 |
| tokens.txt | 93939 | d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d |

Both runs printed:

```text
check encoder.fp32: max rel diff 6.74e-06, mean cosine 1.0000
check decoder.fp32: max rel diff 1.69e-06, mean cosine 1.0000
check joiner.fp32: max rel diff 2.48e-07, mean cosine 1.0000, token argmax agreement 1.000
check encoder.int8: max rel diff 7.02e-01, mean cosine 0.9204
check decoder.int8: max rel diff 6.46e-02, mean cosine 0.9994
check joiner.int8: max rel diff 5.06e-03, mean cosine 1.0000, token argmax agreement 1.000
```

| Run | Wall time | Peak RSS, KiB | Exit |
| --- | --- | ---: | ---: |
| Conversion 1 | 55.51 s | 10706080 | 0 |
| Conversion 2 | 41.04 s | 10496180 | 0 |
| CLI end to end | 2:02.12 | 10717600 | 0 |
| Cached CLI repeat | 0.43 s | 29900 | 0 |

Sampled file-size sum every 150 ms beneath the scratch root. End-to-end
peak: 8,077,353,693 bytes (7.52 GiB), below the 8 GiB prerequisite. This is
a sampled measurement, not a bound on every transient filesystem allocation.
The two-conversion harness peaked at 8,881,682,334 bytes because it retained
the first output while building the second. That harness is not the product
download layout. Timing and measured peak differ from the worker's earlier
run; output bytes remain identical.

## Real CLI download

Scratch root was `<worktree>/.hive/tmp/verify32/models/`. Set
`XDG_DATA_HOME=<scratch>/xdg`, then ran:

```sh
/usr/bin/time -v .venv/bin/stenographer model download --asr
```

CLI output, with the scratch path shortened:

```text
stenographer: creating a temporary venv with the system Python 3
stenographer: installing the pinned converter packages (not cached)
stenographer: downloading ConwayResearch/Underdog-Bark-3.0-Pro at 4b5c51e04aa8 (about 1.3 GB)
stenographer: converting to int8 ONNX (about a minute; longer on slower machines)
[the six graph-check lines above]
file encoder.int8.onnx 630748040
file decoder.int8.onnx 47658546
file joiner.int8.onnx 6123466
file tokens.txt 93939
stenographer: ASR model installed at <scratch>/xdg/stenographer/models/asr/bark-pro-int8
stenographer: Underdog Bark 3.0 Pro by Conway Research (CC BY 4.0), converted to int8 ONNX on this machine
stenographer: VAD model silero_vad.onnx downloaded
```

Installed files, relative to `<scratch>/xdg/stenographer/`:

```text
models/asr/bark-pro-int8/LICENSE                 18657
models/asr/bark-pro-int8/NOTICE                    705
models/asr/bark-pro-int8/decoder.int8.onnx    47658546
models/asr/bark-pro-int8/encoder.int8.onnx   630748040
models/asr/bark-pro-int8/joiner.int8.onnx      6123466
models/asr/bark-pro-int8/manifest.json            868
models/asr/bark-pro-int8/tokens.txt             93939
models/live/silero_vad.onnx                   643854
```

Installed manifest:

```json
{
  "schema": 1,
  "source": {
    "repo": "ConwayResearch/Underdog-Bark-3.0-Pro",
    "revision": "4b5c51e04aa8d16dda9ecdff71bc29f7360149e4"
  },
  "packages": {
    "torch": "2.14.1+cpu",
    "transformers": "5.20.2",
    "onnx": "1.23.2",
    "onnxruntime": "1.31.0",
    "onnx-ir": "1.1.0",
    "numpy": "2.5.4"
  },
  "files": {
    "encoder.int8.onnx": "f111c3ad95637239021cc25b3166c0b6dbb64ab93854f8e9246d56e38b13a29e",
    "decoder.int8.onnx": "7c6ce4acf9282c323a5097467699fe2f2863142cff677b84426dc90fde7bd73f",
    "joiner.int8.onnx": "21674f569e8f102d6c5e10c222fabea73cafb171bace666f33bb2a1b4d0067a2",
    "tokens.txt": "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d",
    "NOTICE": "400201cab858d361f3acc3a7fd35f2fc49a348a91198d639bb78aebcac9b06e4",
    "LICENSE": "9ba9550ad48438d0836ddab3da480b3b69ffa0aac7b7878b5a0039e7ab429411"
  }
}
```

Hashing each installed manifest entry matched its recorded value. The extra
`onnx-ir` pin follows the manager approval recorded in worker V7.
No `.build-*`, `model.safetensors` or `pyvenv.cfg` remained under scratch
after installation. A repeat CLI call reported ASR and VAD `already present`.
Deleted the full scratch model root after those checks.

## Packaging and cache

The optional worker wheel command with `--no-build-isolation` could not
import `hatchling.build` in this repo venv. Retried with standard pip build
isolation and `--no-cache-dir`; the wheel built successfully and contained
both expected assets. No repo venv or application dependency was changed.

| Cache measurement | Bytes from `du -sb ~/.cache/pip` | `du -sh ~/.cache/pip` |
| --- | ---: | --- |
| Before real model runs | 3585560660 | 3.4G |
| After real model runs | 3585560660 | 3.4G |
| After optional isolated wheel build | 3585560656 | 3.4G |

No wheel-size cache growth occurred. Scratch mutation packages, downloaded
models, source weights, venv, wheel, scripts and logs were removed after
this record was written. The pre-existing user-created `.venv` was retained.
No reinstall was run. The manager can offer `scripts/reinstall.sh` when the
feature is ready for user acceptance.
