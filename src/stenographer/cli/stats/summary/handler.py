# SPDX-License-Identifier: GPL-3.0-or-later
"""Render numeric analytics summary."""


def _duration(seconds: float) -> str:
    value = int(seconds)
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def run(args, store, filters) -> int:
    report = store.report(filters)
    totals = report["totals"]
    print(f"Recognized words: {totals['recognized_words']:,}")
    print(f"Completed ASR audio: {_duration(totals['asr_audio_s'])}")
    print(f"Utterances: {totals['utterances']:,} · Active days: {totals['active_days']:,}")
    print(f"Clipboard-confirmed words: {totals['copied_words']:,}")
    print(f"Paste-chord words: {totals['chord_words']:,}")
    print(f"Incomplete utterances: {totals['incomplete']:,}")
    for name, metric in report["metrics"].items():
        if not name.endswith("_ms") or not metric["count"]:
            continue
        print(
            f"{name}: average {metric['average']:.1f}, p95 {metric['p95']:.1f}, "
            f"p99 {metric['p99']:.1f} ms (n={metric['count']}, missing={metric['missing']})"
        )
    health = report["health"]
    print(
        f"Collection: {'degraded' if health['degraded'] else 'available'}; "
        f"dropped checkpoints: {health['dropped_checkpoints']}"
    )
    return 0
