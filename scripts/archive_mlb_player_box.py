#!/usr/bin/env python3
"""Every MLB player's box-score line this season, for the Team strength box's
injury adjustment (a hitter on the injured list comes off his team's runs a
game; see lib/team_strength.py). The user's ask, 2026-11-24.

Writes data/raw/mlb_player_box.json:
  {event id: {"date", "away", "home",
              "bat": {team: [[athlete id, name, pos, starter, AB, R, H, RBI, HR, BB, K], ...]},
              "pit": {team: [[athlete id, name, starter, outs, H, R, ER, BB, K], ...]}}}
Every finished game in data/raw/schedule/mlb.json (archive_schedule.py) from the
season's start, postseason included, fetched once; at most MAX_FETCH a run
(env MLB_BOX_MAX). Run in the scoring workflow after
archive_schedule.py.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, store  # noqa: E402

OUT = os.path.join(store.REPO_ROOT, "data", "raw", "mlb_player_box.json")
SCHED = os.path.join(store.REPO_ROOT, "data", "raw", "schedule", "mlb.json")
URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event={}"
MAX_FETCH = int(os.environ.get("MLB_BOX_MAX", "300"))
SEASON_START = "-03-25"      # month-day: spring training before it is left out
BAT = ("AB", "R", "H", "RBI", "HR", "BB", "K")
PIT = ("H", "R", "ER", "BB", "K")


def _n(v):
    try:
        return float(str(v).split("-")[0])
    except (TypeError, ValueError):
        return 0.0


def _outs(ip):
    """'5.2' innings = 17 outs."""
    try:
        w, _, f = str(ip).partition(".")
        return int(w) * 3 + int(f or 0)
    except ValueError:
        return 0


def fetch(session, eid):
    d = session.get(URL.format(eid), timeout=25).json()
    comp = ((d.get("header") or {}).get("competitions") or [{}])[0]
    if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
        return None
    side = {c.get("homeAway"): (c.get("team") or {}).get("displayName") for c in comp.get("competitors") or []}
    out = {"date": None, "away": side.get("away"), "home": side.get("home"), "bat": {}, "pit": {}}
    for t in (d.get("boxscore") or {}).get("players") or []:
        team = (t.get("team") or {}).get("displayName")
        for st in t.get("statistics") or []:
            lab = st.get("labels") or []
            kind = st.get("type")
            rows = []
            for a in st.get("athletes") or []:
                v, ath = a.get("stats") or [], a.get("athlete") or {}
                if not v:
                    continue
                pos = (a.get("position") or {}).get("abbreviation")
                if kind == "batting" and all(k in lab for k in BAT):
                    rows.append([str(ath.get("id")), ath.get("displayName"), pos, bool(a.get("starter"))]
                                + [_n(v[lab.index(k)]) for k in BAT])
                elif kind == "pitching" and "IP" in lab and all(k in lab for k in PIT):
                    rows.append([str(ath.get("id")), ath.get("displayName"), bool(a.get("starter")), _outs(v[lab.index("IP")])]
                                + [_n(v[lab.index(k)]) for k in PIT])
            if rows:
                out["bat" if kind == "batting" else "pit"][team] = rows
    return out if out["bat"] else {"skip": "no box score"}


def main():
    try:
        with open(SCHED, encoding="utf-8") as f:
            dates = json.load(f).get("dates") or {}
    except (OSError, ValueError):
        print("no MLB schedule saved")
        return
    try:
        with open(OUT, encoding="utf-8") as f:
            have = json.load(f)
    except (OSError, ValueError):
        have = {}
    todo = [(d, str(r[4])) for d in sorted(dates) for r in dates[d]
            if d[4:] >= SEASON_START and len(r) > 6 and r[5] is not None and str(r[4]) not in have]
    session = espn.make_session()
    got = 0
    for d, eid in todo[:MAX_FETCH]:
        try:
            e = fetch(session, eid)
        except Exception as exc:  # noqa: BLE001
            print(f"{eid}: {exc.__class__.__name__}")
            continue
        if e is not None:
            e["date"] = d            # the schedule's (Eastern) date, not ESPN's UTC start
            have[eid] = e
            got += 1
        if got and got % 200 == 0:
            _save(have)
    _save(have)
    print(f"MLB player box: {got} fetched, {max(0, len(todo) - got)} still to fetch, {len(have)} saved")


def _save(have):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(have, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    main()
