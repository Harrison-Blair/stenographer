# SPDX-License-Identifier: GPL-3.0-or-later
"""Tables for the report from the run JSONs. Prints numbers only (no transcript text).

python3 -I analyze.py RUN.json ...   (row order follows the arguments)
"""

from __future__ import annotations

import difflib
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[7] / "scripts/transcription_study"))
from scoring import normalize, score

FILLERS = {"um", "uh", "umm", "uhm", "hmm", "mm", "mhm", "er", "erm", "ah"}
TOL = 1.0  # seconds; the same tolerance as lib/transcribe/decode.py


def pooled(pairs):
    s = d = i = n = 0
    for ref, hyp in pairs:
        r = score(ref, hyp)
        if r["N"]:
            s, d, i, n = s + r["S"], d + r["D"], i + r["I"], n + r["N"]
    return 100 * (s + d + i) / n if n else float("nan")


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))] if xs else float("nan")


def main() -> None:
    runs = {}
    for p in sys.argv[1:]:
        r = json.loads(Path(p).read_text())
        runs[r["label"]] = r
    labels = list(runs)

    print("## Speed and memory\n")
    print(
        "| run | load s | first decode s | RTF corpus | RTF excerpts | phrase 2-10 s p50 / p95 ms "
        "| phrase <2 s p50 ms | peak RSS MB | RSS after load MB | peak GPU MB |"
    )
    print("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for k, r in runs.items():
        rc = sum(x["latency"] for x in r["corpus"]) / sum(x["duration"] for x in r["corpus"])
        re_ = sum(x["latency"] for x in r["excerpts"]) / sum(x["duration"] for x in r["excerpts"])
        mid = [x["latency"] * 1000 for x in r["excerpts"] if 2 <= x["duration"] <= 10]
        short = [x["latency"] * 1000 for x in r["excerpts"] if x["duration"] < 2]
        print(
            f"| {k} | {r['load_s']:.1f} | {r['first_decode_s']:.2f} | {rc:.4f} | {re_:.4f} | "
            f"{pct(mid, 0.5):.0f} / {pct(mid, 0.95):.0f} | {pct(short, 0.5):.0f} | "
            f"{r['peak_rss_mb']:.0f} | "
            f"{r['rss_after_load_mb']:.0f} | {r['peak_gpu_mb'] or '-'} |"
        )
    first = runs[labels[0]]
    print(
        f"\nPhrases: {len(first['excerpts'])} "
        f"({sum(1 for x in first['excerpts'] if 2 <= x['duration'] <= 10)} of 2-10 s), "
        f"{sum(x['duration'] for x in first['excerpts']):.0f} s of speech; "
        f"corpus clips: {len(first['corpus'])}, "
        f"{sum(x['duration'] for x in first['corpus']):.0f} s.\n"
    )

    print("## Corpus WER % (verbatim references, scripts/transcription_study/scoring.py)\n")
    subsets = [
        ("ami", "AMI headset"),
        ("librispeech_clean", "LS clean"),
        ("librispeech_other", "LS other"),
    ]
    print(
        "| run | "
        + " | ".join(n for _, n in subsets)
        + " | all | AMI, fillers removed from ref and hyp "
        "| filler words in hyp (ref has N) | exact clips |"
    )
    print("|---|" + "--:|" * (len(subsets) + 4))
    for k, r in runs.items():
        c = r["corpus"]
        cells = [
            pooled((x["reference"], x["text"]) for x in c if x["corpus"] == s) for s, _ in subsets
        ]
        strip = lambda t: " ".join(w for w in normalize(t) if w not in FILLERS)  # noqa: E731
        ami_nf = pooled(
            (strip(x["reference"]), strip(x["text"])) for x in c if x["corpus"] == "ami"
        )
        fill_h = sum(sum(w in FILLERS for w in normalize(x["text"])) for x in c)
        fill_r = sum(sum(w in FILLERS for w in normalize(x["reference"])) for x in c)
        exact = sum(score(x["reference"], x["text"])["exact"] for x in c)
        print(
            f"| {k} | "
            + " | ".join(f"{v:.2f}" for v in cells)
            + f" | {pooled((x['reference'], x['text']) for x in c):.2f} | {ami_nf:.2f} | "
            f"{fill_h} ({fill_r}) | "
            f"{exact}/{len(c)} |"
        )

    print("\n## Agreement on the private excerpts: WER % of column against row as reference\n")
    print("| reference \\ hypothesis | " + " | ".join(labels) + " |")
    print("|---|" + "--:|" * len(labels))
    for a in labels:
        cells = []
        for b in labels:
            if a == b:
                cells.append("-")
                continue
            ta = [x["text"] for x in runs[a]["excerpts"]]
            tb = [y["text"] for y in runs[b]["excerpts"]]
            cells.append(f"{pooled(zip(ta, tb, strict=True)):.1f}")
        print(f"| {a} | " + " | ".join(cells) + " |")
    print()
    for k, r in runs.items():
        e = r["excerpts"]
        fill = sum(sum(w in FILLERS for w in normalize(x["text"])) for x in e)
        words = sum(len(normalize(x["text"])) for x in e)
        empty = sum(1 for x in e if not x["text"])
        print(f"- {k}: {words} words, {fill} filler words, {empty} empty phrases of {len(e)}")

    print("\n## Word timestamps on the excerpt phrases\n")
    print(
        "| run | phrases with text | with word times | invalid (outside phrase ±1 s or end<start) "
        "| non-monotonic starts | median word length ms |"
    )
    print("|---|--:|--:|--:|--:|--:|")
    for k, r in runs.items():
        e = [x for x in r["excerpts"] if x["text"]]
        with_w = [x for x in e if x["words"]]
        invalid = sum(
            1
            for x in with_w
            for s, en, _ in x["words"]
            if s < -TOL or en > x["duration"] + TOL or en < s
        )
        nonmono = sum(
            1
            for x in with_w
            if any(b[0] < a[0] for a, b in zip(x["words"], x["words"][1:], strict=False))
        )
        lens = [(en - s) * 1000 for x in with_w for s, en, _ in x["words"]]
        print(
            f"| {k} | {len(e)} | {len(with_w)} | {invalid} | {nonmono} | "
            f"{statistics.median(lens) if lens else float('nan'):.0f} |"
        )

    print(
        "\n### Start-time difference of matched words "
        "(|Δstart|, ms; same normalised word, aligned)\n"
    )
    print("| run A | run B | matched words | median | p90 |")
    print("|---|---|--:|--:|--:|")
    for i, a in enumerate(labels):
        for b in labels[i + 1 :]:
            diffs = []
            for xa, xb in zip(runs[a]["excerpts"], runs[b]["excerpts"], strict=True):
                wa = [(normalize(w)[0] if normalize(w) else "", s) for s, _, w in xa["words"]]
                wb = [(normalize(w)[0] if normalize(w) else "", s) for s, _, w in xb["words"]]
                sm = difflib.SequenceMatcher(
                    a=[w for w, _ in wa], b=[w for w, _ in wb], autojunk=False
                )
                for blk in sm.get_matching_blocks():
                    for j in range(blk.size):
                        diffs.append(abs(wa[blk.a + j][1] - wb[blk.b + j][1]) * 1000)
            if diffs:
                print(
                    f"| {a} | {b} | {len(diffs)} | {statistics.median(diffs):.0f} | "
                    f"{pct(diffs, 0.9):.0f} |"
                )


if __name__ == "__main__":
    main()
