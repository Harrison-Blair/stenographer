# SPDX-License-Identifier: GPL-3.0-or-later
"""Evaluate production refinement on public corpus text, retaining only counts.

Verbatim WER is not a cleanup-quality score. Protected-token counts are lexical
proxies, not semantic judgments: writing "two" as "2", for example, changes a
number token. Names are assessed only when explicitly annotated by the caller.
"""

from __future__ import annotations

import ipaddress
import json
import re
import time
from collections import Counter
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from stenographer.lib.config.models import RefineConfig

_TOKENS = re.compile(r"\d+(?:[.,:]\d+)*|\b\w+(?:['\u2019]\w+)*\b")
_NEGATIONS = frozenset(
    [
        "no",
        "not",
        "never",
        "neither",
        "nor",
        "nobody",
        "nothing",
        "nowhere",
        "cannot",
        "can't",
        "don't",
        "doesn't",
        "didn't",
        "won't",
        "wouldn't",
        "isn't",
        "aren't",
        "wasn't",
        "weren't",
        "hasn't",
        "haven't",
        "hadn't",
        "shouldn't",
        "couldn't",
        "mustn't",
        "needn't",
    ]
)
_NUMBERS = frozenset(
    [
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "million",
        "billion",
        "trillion",
    ]
)


def _tokens(text: str) -> list[str]:
    return [token.casefold().replace("\u2019", "'") for token in _TOKENS.findall(text)]


def loopback_host(host: str) -> bool:
    """Accept only HTTP(S) loopback authorities without credentials or URL extras."""

    value = host.strip()
    if "://" not in value:
        value = "http://" + value
    try:
        parsed = urlsplit(value)
        name = parsed.hostname
        port = parsed.port
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or port == 0
            or name is None
        ):
            return False
        return name == "localhost" or ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def refinement_metadata(cfg: RefineConfig) -> dict[str, object]:
    """Pin configured local model identity without warming or fetching a model.

    Total metadata probe budget is three seconds. This dedicated GET opener has
    neither proxy nor redirect handlers, so even metadata stays on loopback.
    Metadata errors retain only their type; no response or exception text leaks.
    """

    import urllib.request

    from stenographer.lib.refine.endpoints import normalize_host

    result: dict[str, object] = {
        "config": {
            "enabled": cfg.enabled,
            "model": cfg.model,
            "min_words": cfg.min_words,
            "structured_output": cfg.structured_output,
        },
        "model_digest": None,
        "model_bytes": None,
        "server_version": None,
        "metadata_status": "disabled",
    }
    if not cfg.enabled:
        return result
    if not loopback_host(cfg.host):
        raise ValueError("public-corpus refinement requires a loopback HTTP(S) host")
    opener = urllib.request.OpenerDirector()
    opener.add_handler(urllib.request.HTTPHandler())
    opener.add_handler(urllib.request.HTTPSHandler())
    deadline = time.monotonic() + 3.0
    try:
        responses = {}
        for endpoint in ("tags", "version"):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            url = f"{normalize_host(cfg.host)}/api/{endpoint}"
            with opener.open(url, timeout=remaining) as response:
                if response.status != 200:
                    raise ValueError("metadata_http_status")
                payload = response.read(1_048_577)
                if len(payload) > 1_048_576:
                    raise ValueError("metadata_too_large")
                responses[endpoint] = json.loads(payload)
        version = responses["version"].get("version")
        if isinstance(version, str) and re.fullmatch(r"[0-9A-Za-z.+_-]{1,100}", version):
            result["server_version"] = version
        aliases = {cfg.model, cfg.model if ":" in cfg.model else cfg.model + ":latest"}
        for model in responses["tags"].get("models", []):
            if not isinstance(model, dict) or model.get("name") not in aliases:
                continue
            digest = model.get("digest")
            size = model.get("size")
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                result["model_digest"] = digest
            if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
                result["model_bytes"] = size
            break
        result["metadata_status"] = "ok" if result["model_digest"] else "model_unavailable"
    except Exception as exc:
        result["metadata_status"] = "unavailable"
        result["error_type"] = type(exc).__name__
    return result


def protected_metrics(
    reference: str,
    before: str,
    after: str,
    *,
    protected_names: tuple[str, ...] = (),
) -> dict[str, object]:
    """Count preservation of annotated names, lexical numbers and negations.

    Repeated occurrences count separately. A 'lost_correct' token was present
    in both the reference and input but is missing from the output. No text or
    token values escape this function. Name annotations must come from corpus
    metadata, not guesses based on capitalization (LibriSpeech uses capitals).
    """

    reference_tokens = Counter(_tokens(reference))
    input_tokens = Counter(_tokens(before))
    output_tokens = Counter(_tokens(after))
    vocabulary = reference_tokens.keys() | input_tokens.keys() | output_tokens.keys()
    names = {token for name in protected_names for token in _tokens(name)}
    categories = {
        "negations": _NEGATIONS,
        "numbers": {
            word for word in vocabulary if word in _NUMBERS or any(c.isdigit() for c in word)
        },
        "names": names,
    }
    result: dict[str, object] = {
        "names_evaluated": bool(protected_names),
        "cleanup_reference_available": False,
    }
    for category, selected in categories.items():
        ref = Counter({word: count for word, count in reference_tokens.items() if word in selected})
        initial = Counter({word: count for word, count in input_tokens.items() if word in selected})
        final = Counter({word: count for word, count in output_tokens.items() if word in selected})
        initial_correct = ref & initial
        final_correct = ref & final
        result[category] = {
            "reference": ref.total(),
            "input_matching": initial_correct.total(),
            "output_matching": final_correct.total(),
            "lost_correct": (initial_correct - final_correct).total(),
            "gained_correct": (final_correct - initial_correct).total(),
            "added_nonreference": ((final - ref) - (initial - ref)).total(),
        }
    return result


def evaluate_refinement(
    text: str,
    reference: str,
    cfg: RefineConfig,
    *,
    idle_unload_seconds: int = 900,
    protected_names: tuple[str, ...] = (),
) -> dict[str, object]:
    """Refine public corpus text using saved settings and return counts only.

    Construction is lazy; the production factory controls thresholds, prompts,
    guards, timeout, and keep-alive. There is no warm-up, model download, or
    service startup. The caller must explicitly opt in and serialize this work
    with ASR timing runs. A disabled configuration performs no network activity.
    """

    from stenographer.lib.refine.factory import build_refiner
    from transcription_study.scoring import score

    if cfg.enabled and not loopback_host(cfg.host):
        raise ValueError("public-corpus refinement requires a loopback HTTP(S) host")
    refiner = build_refiner(cfg, idle_unload_seconds=idle_unload_seconds)
    refined = refiner.refine(text)
    last = refiner.last_result
    return {
        **score(reference, refined),
        "outcome": last.outcome if last is not None else "disabled",
        "duration_ms": (last.duration_ms or 0.0) if last is not None else 0.0,
        "protected_metrics": protected_metrics(
            reference, text, refined, protected_names=protected_names
        ),
    }
