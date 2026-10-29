#!/usr/bin/env python3
"""Record how the scoring workflow's steps went, in data/health.json, so the
pick sheet can say when part of it is failing (and since when).

Run by .github/workflows/diamond-ledger.yml after its steps, with each
step's outcome:

    python scripts/health.py nbaStats=success nflStats=failure scoring=success lines=skipped

The file holds dates, not times, so it changes at most once a day plus on
any change of status. That daily change is deliberate: the bot commit it
causes keeps the repo "active", and GitHub switches off scheduled workflows
in a public repo after 60 days without activity (the off-season would
otherwise do exactly that).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import store  # noqa: E402
from lib.dates import today_et_str  # noqa: E402

PATH = os.path.join(store.REPO_ROOT, "data", "health.json")
LABELS = {"nbaStats": "NBA Stats picks", "nflStats": "NFL Stats picks", "scoring": "Scores and grading", "lines": "Line archive"}


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main(args):
    today = today_et_str()
    old = load()
    doc = {"date": today, "steps": dict(old.get("steps") or {})}
    for arg in args:
        name, _, outcome = arg.partition("=")
        prev = doc["steps"].get(name) or {}
        step = {"label": LABELS.get(name, name), "status": outcome or "unknown",
                "okOn": prev.get("okOn"), "failingSince": None}
        if outcome == "success":
            step["okOn"] = today
        elif outcome == "failure":
            step["failingSince"] = prev.get("failingSince") or today
        else:  # skipped / cancelled: keep whatever was known
            step["failingSince"] = prev.get("failingSince")
        doc["steps"][name] = step
    if doc != old:
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
            f.write("\n")
        os.replace(tmp, PATH)
    failing = [s["label"] for s in doc["steps"].values() if s["status"] == "failure"]
    print("health:", ", ".join(f"{k}={v['status']}" for k, v in doc["steps"].items()), "| failing:", ", ".join(failing) or "none")


if __name__ == "__main__":
    main(sys.argv[1:])
