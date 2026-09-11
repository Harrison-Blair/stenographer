<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Refine: optional local cleanup

Refine is an optional second pass over a finished transcript. After the local
formatter has done its work and before anything is pasted, the text goes to a
model running on your own machine through [Ollama](https://ollama.com), and the
cleaned result is what lands at your cursor.

It is **off by default**. Nothing in this document happens unless you turn it
on.

## What it does

Speech is not writing. You restart sentences, you say "um", you correct
yourself half a word in. Refine removes that without changing what you said:

- Self-corrections collapse to what you actually meant. "thursday no wait
  friday" becomes "Friday".
- Hesitation fillers and accidental repeated words go away. A deliberate
  opener — "hey", "yeah", "okay" — stays, because it is part of the message.
- Punctuation and capitalization are fixed.
- A topic shift starts a new paragraph; a spoken list becomes lines starting
  with `- `.

And what it must never do, which the prompt states and the output guard
enforces: it never summarizes, never answers or responds to what you said,
never adds a fact, and never adds headers, bold, numbered lists, or any other
markdown. Names, numbers, and quoted phrases come through verbatim.

## Privacy

The transcript leaves the process once: as the body of a single
`POST {host}/api/chat` to the host you configured. With the default host,
`http://127.0.0.1:11434`, that is a loopback request and the text never leaves
your machine.

If you point `host` at anything else, your transcripts are sent over the
network to that machine. Nothing stops you — it is your configuration — but the
config file says so, the setup wizard says so, and the daemon logs a warning at
every start.

Nothing else changes. Transcript text still never appears in a log line, an
error message, a notification, or your local statistics. The refine stage adds
only numbers to the history: how long it took, how many characters went in and
came out, and whether it was applied.

## Turning it on

You need Ollama installed and running. Then:

```toml
[stenographer.refine]
enabled = true
```

The default `gemma4:e2b` is about a 7.2 GB download and about 1.7 GB resident.

`stenographer setup` walks you through the same thing, lists the models Ollama
already has, and offers to pull the one you choose.

Download the model explicitly, like the ASR model:

```sh
stenographer model download --refine   # just the refine model
stenographer model download --asr      # just the speech-recognition model
stenographer model download            # asks about both, with sizes
```

The no-flag form needs a terminal to ask on. Run from a script, a pipe, or
anywhere without a TTY, it downloads only the ASR model and tells you which
flag to pass for the other — so an existing install script does not suddenly
start pulling several more gigabytes.

To try it on a file without touching the daemon's settings:

```sh
stenographer transcribe recording.wav --refine
```

That flag is a deliberate opt-in and does not read `enabled`, so a configured
daemon does not make one-off file transcriptions start calling a model.

## Settings

All of these live under `[stenographer.refine]`.

| Key | Default | What it does |
| --- | --- | --- |
| `enabled` | `false` | Whether the stage runs at all. |
| `host` | `"http://127.0.0.1:11434"` | Your Ollama server. Anything but loopback sends transcripts over the network. |
| `model` | `"gemma4:e2b"` | The Ollama model tag to use. |
| `min_words` | `10` | Shorter utterances are delivered without a refine. |
| `structured_output` | `false` | Constrain the reply to a JSON object with one text field. |

### `model`

The default is `gemma4:e2b`. It is chosen by `scripts/refine_bench.py`, which
runs a fixed corpus of dictated speech past each candidate and scores the
result for meaning fidelity: does it drop a clause, respell a name, change a
number, or answer a question it was supposed to leave alone. `gemma4:e2b` was
the only model measured that never did. It holds about 1.7 GB of VRAM, which
leaves room for the Whisper model on an 8 GB card, and takes roughly 2 seconds
for a short utterance and 5 seconds for a long one once warm.

The documented second choice is `qwen3.5:4b`, which produces the best long-form
output of the field but needs the schema:

```toml
[stenographer.refine]
model = "qwen3.5:4b"
structured_output = true
```

Any model your Ollama has will be used if you name it, but quality is verified
only for those two. Models are not interchangeable here in the way they usually
are: the benchmark rejected candidates for injecting punctuation into digit
strings (`rtx 3080` becoming `RTX 3:080`), for rewriting digits as words, and
for turning `nine thirty` into `ninety-three`. If you pick your own, read its
output before you trust it.

### `min_words`

A four-word utterance has nothing to clean up, and a model round-trip on it is
pure latency. Anything below the threshold goes straight from the local
formatter to your cursor, exactly as it does with refine off.

### `structured_output`

Some models answer with their reasoning unless a grammar stops them. Turning
this on makes Ollama constrain the reply to `{"text": "..."}`.

The default model does not need it and is left in plain-text mode. The second
choice, `qwen3.5:4b`, does: without the schema it loses its paragraph breaks
and keeps retraction markers. And at least one model is actively broken by it —
`gemma3:4b` closes the JSON string with a curly quote, the reply fails to
parse, and it then loops until it exhausts the token budget. If you configure
your own model, try it both ways.

Thinking is always disabled, whatever model you choose and whether or not the
schema is on. It is sent as `think: false` on every request, including to
models that cannot think, which ignore it. Turning it on made a 2-second
utterance take 8.5 seconds in the benchmark, and made one model spend its
entire token budget deliberating and then return nothing at all.

## What you will see

The lifecycle pill gains a **Refining** state between *Transcribing* and
*Delivering*, so you can tell which stage is taking the time.

Escape still cancels the whole utterance. Pressing it during a refine discards
the audio and the transcript; nothing is pasted.

## When it does not work

The stage fails open, always. On any of the following, the locally formatted
transcript is delivered unchanged and the daemon logs one line saying why:

- Ollama is not running, is unreachable, or returns an HTTP error.
- The reply does not arrive inside the time budget, which is
  `10 s + 0.06 s × input words`.
- The reply is not a usable chat response, or the structured reply has no text
  field.
- The output guard refuses the reply. It does that when the output is empty,
  when its length is outside 0.30×–1.6× the input's (which catches a summary
  and catches a model that answered instead of editing), or when it is still
  wrapped in quotes or a code fence after one wrapping pair is stripped.

  The floor is 0.30 rather than something tighter because a correct answer can
  legitimately be much shorter: collapsing a list whose last item the speaker
  retracted drops about a third of the words, which measured 0.37–0.40 for
  every model benchmarked.

A dictation is never lost to a cleanup pass. The worst case is that you get the
text you would have got with refine switched off.

## Residency

The daemon warms the model in the background at start, so the first refined
utterance is not also a cold load. The model is held for as long as
`[stenographer.asr] idle_unload_seconds`; if that is `0` — meaning the ASR
worker never unloads — the refine model is held indefinitely too.
