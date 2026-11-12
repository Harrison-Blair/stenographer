# SPDX-License-Identifier: GPL-3.0-or-later
"""Benchmark local Ollama models for the dictation refine stage.

Runs a fixed corpus of dictated-speech samples through one or more models and reports
timings, token counts, resident VRAM and the raw outputs so the blessed default model and
its request settings can be re-chosen later. Nothing here is imported by the application.

Example:
    .venv/bin/python scripts/refine_bench.py --model qwen3.5:4b --model gemma3:4b
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from stenographer.lib.refine.profiles import RefineProfile
from stenographer.lib.refine.request import build_messages

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_NUM_PREDICT = 400
DEFAULT_KEEP_ALIVE = "15m"
DEFAULT_TIMEOUT = 180.0

# --- Corpus ---------------------------------------------------------------------------

SAMPLES: dict[str, str] = {
    # Opener kept, self-correction collapsed, repeated word dropped.
    "correction": (
        "yeah so um i think we should uh push the release to thursday no wait friday "
        "because the the acceptance run isn't done yet"
    ),
    # Short chat message that must keep its opener and stay short.
    "opener": (
        "hey yeah i just wanted to say the thing you sent over looks good to me um i'll "
        "take another proper look at it tonight"
    ),
    # Stammers and doubled words throughout.
    "repeats": (
        "so i i think the the main problem is that we we keep rebuilding the whole index "
        "every every time somebody saves a file"
    ),
    # Spoken enumeration of three items.
    "list": (
        "three things for today um first fix the overlay bug second write the release "
        "notes and third run the acceptance pass on the laptop"
    ),
    # Enumeration where the speaker retracts the last item.
    "list_retract": (
        "so for the demo we need uh the slides the recording and the budget sheet "
        "actually no not the budget sheet just the slides and the recording"
    ),
    # Ordinal steps inside a longer message: each step becomes its own line,
    # keeping first/second/third as the numbering, with no "- " and no digits.
    "ordinals": (
        "Hey, quick one about the crash. I can reproduce it every time now. First, start the "
        "daemon with refine on. Second, cancel an utterance during the refining pill. Third, "
        "dictate again and it hangs. Let me know if you need logs. "
    ),
    # Two topics: must become two paragraphs.
    "topic_shift": (
        "so the encoder is finally done i got the last of the timing tests passing this "
        "morning and it's about twenty percent faster than the old one and then "
        "completely separately i wanted to ask whether we're still doing the offsite in "
        "march because i need to book flights"
    ),
    # A question the model may be tempted to answer.
    "question": (
        "hey can you remind me what time the standup is tomorrow i think it moved to nine thirty"
    ),
    # Proper nouns and numbers that must survive verbatim.
    "names_numbers": (
        "i told marcus okafor that the rtx 3080 only has 8 gigabytes of vram so the "
        "medium dot e n whisper model plus the 4b refine model both have to fit in there "
        "at the same time"
    ),
    # Long rambling paragraph, roughly 150 words.
    "ramble": (
        "okay so i've been thinking about the whole refine thing again and um the the "
        "part that i keep getting stuck on is what happens when ollama isn't running at "
        "all because right now the pipeline just kind of assumes that it's there and if "
        "it's not you get this you know weird hang for like ten seconds before anything "
        "comes out which is that's terrible for dictation because you're sitting there "
        "waiting and you don't know if it crashed or what and i think what we want is uh "
        "we want the thing to just fail open immediately so if the socket isn't there we "
        "we don't even try we just deliver the locally formatted text and move on and "
        "then maybe the first time it happens we log something numeric so you can tell "
        "from the analytics that it's been failing but we never we never put the actual "
        "text in there obviously"
    ),
    # Already clean: the model must not embellish it.
    "already_clean": (
        "The build finished at 4:15 and the acceptance run is green on both machines, so "
        "I am going to tag the release tomorrow morning."
    ),
}


@dataclass(frozen=True)
class Settings:
    """Request settings shared by every call in a benchmark run."""

    host: str
    think: bool
    num_predict: int
    keep_alive: str
    timeout: float


@dataclass(frozen=True)
class Result:
    """One sample's outcome."""

    name: str
    text: str
    output: str
    wall: float
    load: float
    prompt_tokens: int
    eval_tokens: int
    error: str = ""


def post_json(url: str, body: dict, timeout: float) -> tuple[dict, float]:
    """POST a JSON body and return the decoded reply plus the wall time in seconds."""
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        payload = json.loads(reply.read())
    return payload, time.perf_counter() - start


def get_json(url: str, timeout: float) -> dict:
    """GET a JSON document."""
    with urllib.request.urlopen(url, timeout=timeout) as reply:
        return json.loads(reply.read())


def build_body(model: str, text: str, settings: Settings) -> dict:
    """Build the /api/chat request body for one sample."""
    body: dict = {
        "model": model,
        "stream": False,
        "think": settings.think,
        "keep_alive": settings.keep_alive,
        "options": {"temperature": 0, "num_predict": settings.num_predict},
        "messages": build_messages(text, profile=RefineProfile.GENERAL),
    }
    return body


def run_sample(model: str, name: str, text: str, settings: Settings) -> Result:
    """Send one sample and collect its timings and output."""
    body = build_body(model, text, settings)
    try:
        payload, wall = post_json(f"{settings.host}/api/chat", body, settings.timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return Result(name, text, "", 0.0, 0.0, 0, 0, error=f"{type(error).__name__}: {error}")
    message = payload.get("message", {})
    return Result(
        name=name,
        text=text,
        output=str(message.get("content", "")).strip(),
        wall=wall,
        load=payload.get("load_duration", 0) / 1e9,
        prompt_tokens=payload.get("prompt_eval_count", 0),
        eval_tokens=payload.get("eval_count", 0),
    )


def unload(model: str, settings: Settings) -> None:
    """Evict the model from VRAM so the next call measures a cold load."""
    try:
        post_json(
            f"{settings.host}/api/generate",
            {"model": model, "keep_alive": 0},
            settings.timeout,
        )
    except (urllib.error.URLError, TimeoutError, OSError):
        return


def unload_all(settings: Settings) -> None:
    """Evict every resident model so the run is not measured against a squatted GPU."""
    try:
        payload = get_json(f"{settings.host}/api/ps", settings.timeout)
    except (urllib.error.URLError, TimeoutError, OSError):
        return
    for entry in payload.get("models", []):
        unload(str(entry.get("model", "")), settings)


def resident_vram(model: str, settings: Settings) -> float:
    """Return the model's resident VRAM in gigabytes, or 0.0 when it is not loaded."""
    try:
        payload = get_json(f"{settings.host}/api/ps", settings.timeout)
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0.0
    for entry in payload.get("models", []):
        if entry.get("name") == model or entry.get("model") == model:
            return entry.get("size_vram", 0) / 1e9
    return 0.0


def report(model: str, settings: Settings, cold: Result, warm: list[Result]) -> None:
    """Print the timing table and every output for one model."""
    print(f"\n{'=' * 78}\nmodel={model} think={settings.think} ")
    print(f"num_predict={settings.num_predict} keep_alive={settings.keep_alive}\n{'=' * 78}")
    print(
        f"[cold] wall={cold.wall:6.2f}s load={cold.load:6.2f}s "
        f"prompt_tok={cold.prompt_tokens} eval_tok={cold.eval_tokens} {cold.error}"
    )
    print(f"[vram] {resident_vram(model, settings):.2f} GB resident after load")
    header = f"{'sample':<14}{'wall':>8}{'prompt':>8}{'eval':>7}{'in_w':>6}{'out_w':>7}{'ratio':>7}"
    print(f"\n{header}\n{'-' * len(header)}")
    for item in warm:
        in_words = len(item.text.split())
        out_words = len(item.output.split())
        ratio = len(item.output) / max(len(item.text), 1)
        print(
            f"{item.name:<14}{item.wall:>7.2f}s{item.prompt_tokens:>8}{item.eval_tokens:>7}"
            f"{in_words:>6}{out_words:>7}{ratio:>7.2f}"
        )
    total = sum(item.wall for item in warm)
    print(f"{'TOTAL':<14}{total:>7.2f}s")
    for item in warm:
        print(f"\n--- {item.name} ({item.wall:.2f}s) {item.error}")
        print(f"  IN : {item.text}")
        for line in (item.output or "<empty>").splitlines():
            print(f"  OUT: {line}")


def benchmark(model: str, names: list[str], settings: Settings) -> None:
    """Unload every model, time a cold run, then run each selected sample warm."""
    unload_all(settings)
    time.sleep(2)
    first = names[0]
    cold = run_sample(model, first, SAMPLES[first], settings)
    warm = [run_sample(model, name, SAMPLES[name], settings) for name in names]
    report(model, settings, cold, warm)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=DEFAULT_HOST, help="Ollama base URL")
    parser.add_argument("--model", action="append", required=True, help="model tag (repeatable)")
    parser.add_argument("--think", action="store_true", help="enable model thinking")
    parser.add_argument("--num-predict", type=int, default=DEFAULT_NUM_PREDICT)
    parser.add_argument("--keep-alive", default=DEFAULT_KEEP_ALIVE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--sample",
        action="append",
        choices=sorted(SAMPLES),
        help="run only these samples (repeatable; default: all)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark for every requested model."""
    args = parse_args(argv)
    settings = Settings(
        host=args.host.rstrip("/"),
        think=args.think,
        num_predict=args.num_predict,
        keep_alive=args.keep_alive,
        timeout=args.timeout,
    )
    names = args.sample or list(SAMPLES)
    for model in args.model:
        benchmark(model, names, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
