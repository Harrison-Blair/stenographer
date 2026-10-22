<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Smoke-test fixtures

`test_transcribe_smoke.py` needs one short **mono, 16 kHz** WAV clip of
real speech. They are recorded/supplied on the dev machine (a subagent cannot
record audio), and are intentionally *not* generated here — synthetic tones do
not exercise the decoder.

Drop the files in this directory:

- `speech_16k.wav` — a short spoken clip (a sentence or two). Drives the public
  CLI-vs-surviving-API equivalence test. Required for the smoke test to run.

Record, e.g.:

```sh
# 3 seconds, mono, 16 kHz
arecord -f S16_LE -r 16000 -c 1 -d 3 speech_16k.wav
```

With the clip present, the model cached, and `STENOGRAPHER_INTEGRATION=1`, run:

```sh
STENOGRAPHER_INTEGRATION=1 .venv/bin/pytest tests/test_transcribe_smoke.py
```

Without the env var, the fixtures, or the cached model, the whole module
self-skips.
