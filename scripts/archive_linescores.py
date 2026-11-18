#!/usr/bin/env python3
"""Quarter (half, in college basketball) scores for every finished game on
the NBA, NFL, CFB and NCAAB slates, for the trend charts' by-quarter view.
Writes data/raw/linescores/<sport>.json: {date: {"<away>@<home>": [[away
periods...], [home periods...]]}} with the slate's team names. A date whose
games are all saved isn't fetched again. Run in the scoring workflow.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, props, store  # noqa: E402
from lib.picks import is_final  # noqa: E402
from score_slate import _same_team  # noqa: E402

OUT = os.path.join(store.REPO_ROOT, "data", "raw", "linescores")
SPORTS = ("nba", "ncaab", "nfl", "cfb")
EXTRA = {"cfb": "&groups=80", "ncaab": "&groups=50"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    os.makedirs(OUT, exist_ok=True)
    session = espn.make_session()
    for sport in SPORTS:
        path = os.path.join(OUT, f"{sport}.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        changed = 0
        for date_str, doc in store.list_docs(sport):
            if date_str < "2026-08-01":
                continue
            done = data.get(date_str, {})
            want = [g for g in doc.get("games", []) if is_final(doc, g) and f"{g.get('away')}@{g.get('home')}" not in done]
            if not want:
                continue
            try:
                evs = session.get(f"https://site.api.espn.com/apis/site/v2/sports/{props.espn_path(sport)}/scoreboard"
                                  f"?dates={date_str.replace('-', '')}&limit=1000{EXTRA.get(sport, '')}", timeout=30).json().get("events", [])
            except Exception as exc:  # noqa: BLE001
                print(f"{sport} {date_str}: {exc.__class__.__name__}")
                continue
            for g in want:
                for ev in evs:
                    t = {c["homeAway"]: c for c in ev["competitions"][0]["competitors"]}
                    if "home" in t and "away" in t and _same_team(t["away"]["team"]["displayName"], g["away"]) \
                            and _same_team(t["home"]["team"]["displayName"], g["home"]):
                        ls = [[_num(x.get("value")) for x in t[s].get("linescores") or []] for s in ("away", "home")]
                        if ls[0] and ls[1] and None not in ls[0] + ls[1]:
                            data.setdefault(date_str, {})[f"{g['away']}@{g['home']}"] = ls
                            changed += 1
                        break
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                f.write("\n")
        print(f"{sport}: {sum(len(v) for v in data.values())} games with quarter scores (+{changed})")


if __name__ == "__main__":
    main()
