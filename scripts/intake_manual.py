#!/usr/bin/env python3
"""Reads a "data <sport> YYYY-MM-DD" GitHub issue (opened from the pick
sheet's "Enter data by hand" page, site/manual.html) and merges its games
into data/manual/<sport>/<date>.json (see scripts/lib/manual.py). Run by
.github/workflows/data-intake.yml.

Writes a markdown summary to --summary and changed=true|false to $GITHUB_OUTPUT.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib import manual, store  # noqa: E402

BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


def process(issue):
    m = BLOCK.search(issue.get("body") or "")
    if not m:
        return False, "No data block found in this issue. Enter data from the pick sheet's **Enter data by hand** page."
    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        return False, f"Couldn't read the data block ({e}). Submit again from the pick sheet."
    sport, date_str, games = payload.get("sport"), payload.get("date"), payload.get("games")
    if sport not in manual.SPORTS:
        return False, f"Unknown sport `{sport}`."
    if not isinstance(date_str, str) or not manual.DATE.match(date_str):
        return False, "The data block is missing a valid date."
    if not isinstance(games, list) or not games:
        return False, "The data block has no games."

    slate = {(g.get("away"), g.get("home")) for g in (store.read_doc(sport, date_str) or {}).get("games", [])}
    clean, lines = [], []
    for e in games[:40]:
        if not isinstance(e, dict):
            continue
        c, problems = manual.validate(sport, e)
        label = f"{c.get('away', '?')} @ {c.get('home', '?')}"
        if problems:
            lines.append(f"- **{label}** — not saved: {'; '.join(problems)}")
            continue
        fields = [f for f in c if f not in ("away", "home", "time", "box")]
        if "box" in c:
            fields.append(f"box score ({', '.join(c['box'])})")
        note = "" if not slate or (c["away"], c["home"]) in slate else " (not on that date's slate — it will be added)"
        lines.append(f"- **{label}** — {', '.join(fields) or 'game only'}{note}")
        clean.append(c)
    changed = manual.merge(sport, date_str, clean, {"enteredAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                     "issue": issue.get("number")}) if clean else 0
    head = f"**Hand-entered {sport.upper()} data for {date_str}**"
    tail = (f"Saved to `data/manual/{sport}/{date_str}.json`. A scoring run has been started, so the pick sheet updates in a few minutes."
            if changed else "Nothing new was saved (everything matched what's already there, or nothing passed the checks).")
    return bool(changed), "\n".join([head, ""] + lines + ["", tail])


def main():
    summary_path = sys.argv[sys.argv.index("--summary") + 1] if "--summary" in sys.argv else None
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        issue = json.load(f)["issue"]
    changed, summary = process(issue)
    print(summary)
    if summary_path:
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary + "\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()
