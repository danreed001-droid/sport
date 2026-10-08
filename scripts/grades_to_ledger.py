#!/usr/bin/env python3
"""Prepares GitHub's grades for writing back into the Diamond Ledger database.

The scoring workflow grades slates in data/<sport>/<date>.json, but the
database (which the Diamond Ledger Console reads) only gets new slates from
the daily Routines, which never grade. The hourly sync Routine runs this
after sync_ledger.py, then writes each prepared document back with
ArtifactData, so the database catches up with GitHub's grades.

Usage: python scripts/grades_to_ledger.py <export_dir> <out_dir>
  <export_dir> is the same ArtifactData export sync_ledger.py read.
  For every slate graded here but still ungraded in the database, writes
  <out_dir>/<collection>/<date>.json (the full document to "set") and prints
  one "<collection>/<date>" line per document, or "No grades to write back."

Each prepared document is the graded repo copy, with the database's
auditReport kept and the database's own game-list key ("games"/"matches")
kept, so sync_ledger.py sees the two copies as equal on its next run.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import store  # noqa: E402
from sync_ledger import COLLECTIONS, normalize  # noqa: E402


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    export_dir, out_dir = sys.argv[1], sys.argv[2]
    prepared = []
    for coll, sport in COLLECTIONS.items():
        for path in sorted(glob.glob(os.path.join(export_dir, coll, "*.json"))):
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if raw.get("scored"):
                continue
            date_str = raw.get("date") or os.path.splitext(os.path.basename(path))[0]
            graded = store.read_doc(sport, date_str)
            if not graded or not graded.get("scored"):
                continue
            doc = dict(graded)
            if "matches" in raw and "games" not in raw:
                doc["matches"] = doc.pop("games", [])
            if "auditReport" in raw:
                doc["auditReport"] = raw["auditReport"]
            if normalize(doc, sport) != normalize(graded, sport):
                print(f"skipping {coll}/{date_str}: prepared copy doesn't round-trip", file=sys.stderr)
                continue
            out = os.path.join(out_dir, coll, f"{date_str}.json")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False)
            prepared.append(f"{coll}/{date_str}")
    if prepared:
        print("\n".join(prepared))
    else:
        print("No grades to write back.")


if __name__ == "__main__":
    main()
