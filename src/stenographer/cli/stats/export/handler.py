# SPDX-License-Identifier: GPL-3.0-or-later
"""Export numeric analytics to stdout or a file."""

from pathlib import Path


def run(args, store, filters) -> int:
    content = store.export_csv(filters) if args.format == "csv" else store.export_json(filters)
    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
    else:
        print(content, end="" if content.endswith("\n") else "\n")
    return 0
