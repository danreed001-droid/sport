#!/usr/bin/env python3
"""Put hand-entered games and lines (data/manual/<sport>/<date>.json, see
scripts/lib/manual.py) onto the slates in data/<sport>/<date>.json. Run first
in the scoring workflow, so everything after it -- NBA/NFL Stats, grading,
the pick sheet -- sees them.

- A date with no slate at all gets one built from the manual games (marked
  autoSlate, so a Routine's slate still replaces it when one arrives; the
  manual lines are re-applied on top every run).
- A manual game missing from an existing slate is added to it.
- Entered lines overwrite the slate's. A graded slate whose lines or final
  scores were changed by hand is marked ungraded, so it's graded again from
  the corrected numbers (the hand-entered scores reach the scores archive in
  fetch_scores.py).

Usage: python scripts/apply_manual.py [sport ...]   (default: every sport)
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import fetch_scores  # noqa: E402
from lib import manual, store  # noqa: E402
from lib.dates import weekday_et  # noqa: E402


def apply(sport, date_str):
    entries = manual.load(sport, date_str)
    if not entries:
        return None
    doc = store.read_doc(sport, date_str)
    created = doc is None
    if created:
        doc = {"date": date_str, "weekday": weekday_et(date_str), "sport": sport, "scored": False,
               "autoSlate": True, "manualSlate": True,
               "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "games": []}
    regrade = added = 0
    changed = created
    was_scored = bool(doc.get("scored"))
    for e in entries.values():
        g = next((x for x in doc["games"] if x.get("away") == e["away"] and x.get("home") == e["home"]), None)
        if g is None:
            g = {"away": e["away"], "home": e["home"], "manual": True}
            if e.get("time"):
                g["time"] = e["time"]
            doc["games"].append(g)
            added += 1
            changed = True
        fields = set(g.get("manualFields") or [])
        for f in manual.LINE_FIELDS:
            if f in e and g.get(f) != e[f]:
                g[f] = e[f]
                fields.add(f)
                changed = True
                regrade += 1
        if manual.has_final(e):
            fields.update(("awayScore", "homeScore"))
            if doc.get("scored") and (g.get("awayScore"), g.get("homeScore")) != (e["awayScore"], e["homeScore"]):
                regrade += 1
        if fields and sorted(fields) != g.get("manualFields"):
            g["manualFields"] = sorted(fields)
            changed = True
    if regrade and was_scored:
        doc["scored"] = False  # graded again from the corrected numbers this run
        changed = True
    if changed:
        store.write_doc(sport, date_str, doc)
    return created, added, regrade if was_scored else 0, changed


def main():
    for sport in sys.argv[1:] or manual.SPORTS:
        if manual.dates(sport):
            # Final scores into the scores archive now, not only when grading
            # runs, so NBA Stats (which reads it) sees them this same run.
            os.makedirs(fetch_scores.OUTPUT_DIR, exist_ok=True)
            history = fetch_scores.load_history(sport)
            fetch_scores.apply_manual_scores(sport, history)
            fetch_scores.save_history(sport, history)
        for date_str in manual.dates(sport):
            r = apply(sport, date_str)
            if r and r[3]:
                created, added, regrade, _ = r
                print(f"{sport} {date_str}: manual data applied"
                      + (" (built the slate from it)" if created else "")
                      + (f", {added} game(s) added" if added and not created else "")
                      + (", re-grading" if regrade else ""))


if __name__ == "__main__":
    main()
