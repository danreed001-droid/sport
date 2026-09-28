#!/usr/bin/env python3
"""Mirrors Diamond Ledger database documents into data/<sport>/<date>.json.

The daily Routines write every slate (and later its grades) to the ledger
database. The hourly "Diamond Ledger — sync to GitHub" Routine exports each
collection with ArtifactData (out_dir) and runs this script on the export,
then commits whatever changed to main.

Usage: python scripts/sync_ledger.py <export_dir>
  <export_dir>/<collection>/<date>.json, as ArtifactData's out_dir writes it
  (collections: days, nfl, cfb, nba, ncaab, soccer).

Rules: a new date is always written; a graded (scored) database doc replaces
the repo copy whenever they differ; an ungraded database doc never replaces a
repo copy that's already graded (the ESPN scoring workflow may have graded it
first).

The daily research check leaves its findings for a sport in that doc's
"auditReport" field (a Markdown section starting "## <Sport> (N games)").
That field stays out of the slate file; the sections for a date are joined
into data/audits/<date>.md instead.
"""
import glob
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from lib import store  # noqa: E402

COLLECTIONS = {"days": "mlb", "nfl": "nfl", "cfb": "cfb", "nba": "nba", "ncaab": "ncaab", "soccer": "soccer"}
AUDIT_INTRO = (
    "Fact-check of the day's slates. The research check has the final say: when a\n"
    "wrong fact changes a pick, it's fixed in the ledger before first pitch/kickoff\n"
    "and listed under **Changed**.\n"
)


def normalize(doc, sport):
    doc = dict(doc)
    doc.pop("id", None)
    doc.pop("version", None)
    doc.pop("auditReport", None)
    if "games" not in doc and "matches" in doc:
        doc["games"] = doc.pop("matches")
    doc["sport"] = sport
    return doc


def render(doc):
    head = ["date", "weekday", "sport", "scored", "scoredAt", "generatedAt"]
    lines = ["{"]
    for k in head:
        if k in doc:
            lines.append(f"  {json.dumps(k)}: {json.dumps(doc[k], ensure_ascii=False)},")
    for k in sorted(k for k in doc if k not in head and k != "games"):
        lines.append(f"  {json.dumps(k)}: {json.dumps(doc[k], ensure_ascii=False, sort_keys=True)},")
    games = doc.get("games", [])
    lines.append('  "games": [')
    lines.append(",\n".join("    " + json.dumps(g, separators=(",", ":"), sort_keys=True, ensure_ascii=False) for g in games))
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_audit(date_str, sections):
    """Joins the research check's per-sport sections into data/audits/<date>.md.
    Returns True when the file changed."""
    d = date.fromisoformat(date_str)
    title = f"# Research check — {d.strftime('%A, %b')} {d.day}, {d.year}\n"
    body = title + "\n" + AUDIT_INTRO + "".join("\n" + sec.strip() + "\n" for sec in sections)
    out = os.path.join(store.REPO_ROOT, "data", "audits", f"{date_str}.md")
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            if f.read() == body:
                return False
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(body)
    return True


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    export_dir = sys.argv[1]
    written = []
    audits = {}
    for coll, sport in COLLECTIONS.items():
        for path in sorted(glob.glob(os.path.join(export_dir, coll, "*.json"))):
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            doc = normalize(raw, sport)
            date_str = doc.get("date") or os.path.splitext(os.path.basename(path))[0]
            if isinstance(raw.get("auditReport"), str) and raw["auditReport"].strip():
                audits.setdefault(date_str, []).append(raw["auditReport"])
            current = store.read_doc(sport, date_str)
            if current is not None:
                if normalize(current, sport) == doc:
                    continue
                if current.get("scored") and not doc.get("scored"):
                    continue
            out = os.path.join(store.REPO_ROOT, "data", sport, f"{date_str}.json")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(render(doc))
            written.append(f"{sport}/{date_str}{' (graded)' if doc.get('scored') else ''}")
    for date_str, sections in sorted(audits.items()):
        if write_audit(date_str, sections):
            written.append(f"audits/{date_str}")
    if written:
        print("Updated: " + ", ".join(written))
    else:
        print("No changes.")


if __name__ == "__main__":
    main()
