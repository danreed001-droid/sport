#!/usr/bin/env python3
"""Quarter (half, in college basketball) scores for every finished game on
the NBA, NFL, CFB and NCAAB slates, for the trend charts' by-quarter view.
Writes data/raw/linescores/<sport>.json: {date: {"<away>@<home>": [[away
periods...], [home periods...]]}} with the slate's team names. A date whose
games are all saved isn't fetched again. Run in the scoring workflow.

The same scoreboards give each team's record going into the game (ESPN's
overall record on a finished game is the one after it, so the result is taken
back off): data/raw/records/<sport>.json {date: {ESPN team name: "W-L"}}, for
every finished game on the date (the trend charts label each opponent with
it). College dates come from the lines files too, since trend charts fill
college teams' games from them.
"""
import csv
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, props, store  # noqa: E402
from lib.picks import is_final  # noqa: E402
from score_slate import _same_team  # noqa: E402

OUT = os.path.join(store.REPO_ROOT, "data", "raw", "linescores")
REC = os.path.join(store.REPO_ROOT, "data", "raw", "records")
SPORTS = ("nba", "ncaab", "nfl", "cfb")
EXTRA = {"cfb": "&groups=80", "ncaab": "&groups=50"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        f.write("\n")


def record_before(c, other):
    """A finished game's competitor -> its overall record going into the game."""
    rec = next((r for r in c.get("records") or [] if r.get("type") == "total" or r.get("name") == "overall"), None)
    try:
        parts = [int(x) for x in (rec or {}).get("summary", "").split("-")]
    except ValueError:
        return None
    if len(parts) < 2:
        return None
    if c.get("winner"):
        parts[0] -= 1
    elif other.get("winner"):
        parts[1] -= 1
    elif len(parts) > 2:
        parts[2] -= 1   # a tie
    else:
        return None
    if min(parts) < 0:
        return None
    if len(parts) > 2 and parts[2] == 0:
        parts = parts[:2]
    return "-".join(str(x) for x in parts)


def _line_dates(sport):
    path = os.path.join(store.REPO_ROOT, "data", "raw", f"{sport}_lines.csv")
    try:
        with open(path, encoding="utf-8") as f:
            return {r.get("date") or r.get("Date") for r in csv.DictReader(f)} - {None, ""}
    except OSError:
        return set()


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(REC, exist_ok=True)
    session = espn.make_session()
    today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    for sport in SPORTS:
        rpath = os.path.join(REC, f"{sport}.json")
        recs = _load(rpath)
        rchanged = 0
        path = os.path.join(OUT, f"{sport}.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        changed = 0
        docs = dict(store.list_docs(sport))
        dates = sorted(d for d in set(docs) | (_line_dates(sport) if sport in ("cfb", "ncaab") else set())
                       if d >= "2026-08-01" and (not today or d < today))
        for date_str in dates:
            doc = docs.get(date_str) or {"games": []}
            done = data.get(date_str, {})
            want = [g for g in doc.get("games", []) if is_final(doc, g) and f"{g.get('away')}@{g.get('home')}" not in done]
            # records: a past date is fetched once (a "_done" mark once every game on it is final)
            need_rec = not (recs.get(date_str) or {}).get("_done")
            if not want and not need_rec:
                continue
            try:
                evs = session.get(f"https://site.api.espn.com/apis/site/v2/sports/{props.espn_path(sport)}/scoreboard"
                                  f"?dates={date_str.replace('-', '')}&limit=1000{EXTRA.get(sport, '')}", timeout=30).json().get("events", [])
            except Exception as exc:  # noqa: BLE001
                print(f"{sport} {date_str}: {exc.__class__.__name__}")
                continue
            if need_rec:
                day = {}
                all_final = True
                for ev in evs:
                    comp = ev["competitions"][0]
                    if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
                        all_final = False
                        continue
                    cs = comp.get("competitors") or []
                    if len(cs) != 2:
                        continue
                    for c, o in ((cs[0], cs[1]), (cs[1], cs[0])):
                        r = record_before(c, o)
                        if r:
                            day[c["team"]["displayName"]] = r
                if all_final:
                    day["_done"] = 1
                if day and day != recs.get(date_str):
                    recs[date_str] = day
                    rchanged += 1
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
            _save(path, data)
        if rchanged:
            _save(rpath, recs)
        print(f"{sport}: {sum(len(v) for v in data.values())} games with quarter scores (+{changed}); "
              f"records on {len(recs)} dates (+{rchanged})")


if __name__ == "__main__":
    main()
