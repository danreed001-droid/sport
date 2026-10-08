#!/usr/bin/env python3
"""Prepares the slates for the Diamond Ledger Console's own database.

The Console artifact can only read its own database, so the hourly sync
Routine copies every slate in data/ (graded here, or still open) into it.
This compares data/ with an export of the Console's database and writes
each slate that is missing or different there.

Usage: python scripts/mirror_to_console.py <console_export_dir> <out_dir>
  <console_export_dir>/<collection>/<date>.json, as ArtifactData's out_dir
  writes it (collections: days, nfl, cfb, nba, ncaab).
  Writes <out_dir>/<collection>/<date>.json for each slate to "set" and
  prints one "<collection>/<date>" line per slate, or "Console is current."
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import store  # noqa: E402
from sync_ledger import normalize  # noqa: E402

# Console collection -> data/ folder. Soccer stays out: its three-way
# model doesn't fit the Console's two-way scorecards.
COLLECTIONS = {"days": "mlb", "nfl": "nfl", "cfb": "cfb", "nba": "nba", "ncaab": "ncaab"}


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    export_dir, out_dir = sys.argv[1], sys.argv[2]
    prepared = []
    for coll, sport in COLLECTIONS.items():
        for date_str, doc in store.list_docs(sport):
            doc = normalize(doc, sport)
            existing = os.path.join(export_dir, coll, f"{date_str}.json")
            if os.path.exists(existing):
                with open(existing, encoding="utf-8") as f:
                    if normalize(json.load(f), sport) == doc:
                        continue
            out = os.path.join(out_dir, coll, f"{date_str}.json")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False)
            prepared.append(f"{coll}/{date_str}")
    print("\n".join(prepared) if prepared else "Console is current.")


if __name__ == "__main__":
    main()
