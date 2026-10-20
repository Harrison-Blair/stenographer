# SPDX-License-Identifier: GPL-3.0-or-later
"""Render numeric ASR grid summaries as a Markdown table."""

from __future__ import annotations


def render_markdown_table(rows: list[dict]) -> str:
    """Render WER, repeated latency, default delta, and RSS without speech text."""
    lines = [
        "| Model | Setting | WER | Median | p90 | Extra vs default | RTF | RSS peak |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        context = row["context"]
        if context == "reference":
            context += " (upper bound)"
        setting = (
            f"beam {row['beam_size']}; hotwords {'on' if row['hotwords'] else 'off'}; "
            f"context {context}"
        )
        if row["wer"] is not None:
            wer = f"{row['wer'] * 100:.2f}% ({row['errors']}/{row['N']})"
        else:
            wer = "N/A"
        median = (
            f"{row['latency_median_seconds']:.3f} s"
            if row["latency_median_seconds"] is not None
            else "N/A"
        )
        p90 = (
            f"{row['latency_p90_seconds']:.3f} s"
            if row["latency_p90_seconds"] is not None
            else "N/A"
        )
        extra = (
            f"{row['extra_latency_vs_default_seconds']:+.3f} s"
            if row["extra_latency_vs_default_seconds"] is not None
            else "N/A"
        )
        rtf = f"{row['latency_rtf']:.3f}x" if row["latency_rtf"] is not None else "N/A"
        rss = (
            f"{row['rss_peak_bytes'] / 1024**3:.2f} GiB"
            if row["rss_peak_bytes"] is not None
            else "N/A"
        )
        lines.append(
            f"| {row['model']} | {setting} | {wer} | {median} | {p90} | {extra} | {rtf} | {rss} |"
        )
    return "\n".join(lines)
