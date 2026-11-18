#!/usr/bin/env python3
"""Save the rosters of every team on today's and tomorrow's slates (all
sports), for the pick sheet's player-prop picker, plus each game's ESPN event
id. Writes data/raw/rosters/<sport>.json:
  {"<date>": {"teams": {slate team name: [[athlete id, name, position], ...]},
              "events": {"<away>@<home>": event id}}}
A team already saved for that date isn't fetched again; only the last 3
dates are kept. Run in the scoring workflow.
"""
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, props, store  # noqa: E402
from lib.dates import today_et_str  # noqa: E402

OUT = os.path.join(store.REPO_ROOT, "data", "raw", "rosters")
SPORTS = ("nba", "ncaab", "nfl", "cfb", "mlb", "soccer")


def main():
    os.makedirs(OUT, exist_ok=True)
    session = espn.make_session()
    t = date.fromisoformat(today_et_str())
    dates = [t.isoformat(), (t + timedelta(days=1)).isoformat()]
    for sport in SPORTS:
        path = os.path.join(OUT, f"{sport}.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        before = json.dumps(data, sort_keys=True)
        for d in dates:
            doc = store.read_doc(sport, d)
            if not doc:
                continue
            day = data.setdefault(d, {"teams": {}, "events": {}})
            for g in doc.get("games", []):
                away, home = g.get("away"), g.get("home")
                if not away or not home or (away in day["teams"] and home in day["teams"]):
                    continue
                key = f"{away}@{home}"
                try:
                    eid, ids, _ = props.event_for(session, sport, d, away, home)
                    if not eid:
                        continue
                    day["events"][key] = eid
                    slug = props.league_slug(session, sport, eid)
                    for side, name in (("away", away), ("home", home)):
                        if name not in day["teams"] and ids.get(side):
                            day["teams"][name] = props.team_roster(session, sport, ids[side], slug)
                except Exception as exc:  # noqa: BLE001
                    print(f"{sport} {d} {key}: {exc.__class__.__name__}")
        for d in sorted(data)[:-3]:
            data.pop(d)
        if json.dumps(data, sort_keys=True) != before:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                f.write("\n")
        n = sum(len(v["teams"]) for v in data.values())
        print(f"{sport}: rosters for {n} team-dates")


if __name__ == "__main__":
    main()
