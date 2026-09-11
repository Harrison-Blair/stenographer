# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview and confirm deletion of matching analytics."""


def run(args, store, filters) -> int:
    count = store.preview_delete(filters)
    print(f"Records selected for deletion: {count}")
    if not args.yes:
        print("Run again with --yes to confirm. Queued matching checkpoints are suppressed.")
        return 0
    print(f"Deleted {store.delete(filters)} records.")
    return 0
