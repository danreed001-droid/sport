#!/usr/bin/env python3
"""Builds a day's slate straight from ESPN for a sport no Routine has written
one for yet (teams, start time, current lines), marked autoSlate, so the pick
sheet shows the games -- and grades your picks on them -- without waiting on
anything outside this repo. A Routine's slate replaces it when it syncs in
(scripts/sync_ledger.py). Later runs fill in lines ESPN hadn't posted yet.

NBA and NFL get theirs from nba_stats_signals.py / nfl_stats_signals.py;
this covers the rest. NCAA basketball uses ESPN's default scoreboard, which
lists the games involving an AP Top 25 team -- the Basketball Routine's
scope, and the same feed the grader reads.

Usage: python scripts/auto_slate.py ncaab [YYYY-MM-DD ...]   (default: today ET)
"""
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
from lib import espn, sports, store  # noqa: E402
from lib.dates import et_date_of_iso, today_et_str, weekday_et  # noqa: E402


def build(session, sport, date_str):
    cfg = sports.get(sport)
    try:
        events = espn.fetch_scoreboard(session, cfg["espn_sport"], cfg["espn_league"], date_str.replace("-", ""))
    except Exception as e:
        print(f"{sport} {date_str}: ESPN scoreboard unavailable ({e}); nothing built.")
        return None
    games = []
    for ev in events:
        if et_date_of_iso(ev["date"]) != date_str:
            continue
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c["team"]["displayName"] for c in comp["competitors"]}
        start = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
        g = {"espnId": ev["id"], "away": teams.get("away"), "home": teams.get("home"),
             "time": start.strftime("%I:%M %p").lstrip("0") + " ET",
             **espn.pickcenter_lines(session, cfg["espn_sport"], cfg["espn_league"], ev["id"])}
        if comp.get("neutralSite"):
            g["neutral"] = True
        games.append(g)
    if not games:
        return None
    return {"date": date_str, "weekday": weekday_et(date_str), "sport": sport, "scored": False, "autoSlate": True,
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "games": games}


def run(session, sport, date_str):
    cfg = sports.get(sport)
    doc = store.read_doc(cfg["collection"], date_str)
    if doc is None:
        doc = build(session, sport, date_str)
        if doc is None:
            print(f"{sport} {date_str}: no games on ESPN.")
            return
        store.write_doc(cfg["collection"], date_str, doc)
        print(f"{sport} {date_str}: built a slate from ESPN ({len(doc['games'])} games).")
        return
    if doc.get("autoSlate") and not doc.get("scored"):
        filled = 0
        for g in doc.get("games", []):
            if g.get("homeSpread") is None and g.get("espnId"):
                lines = espn.pickcenter_lines(session, cfg["espn_sport"], cfg["espn_league"], g["espnId"])
                if lines:
                    g.update(lines)
                    filled += 1
        if filled:
            store.write_doc(cfg["collection"], date_str, doc)
        print(f"{sport} {date_str}: ESPN-built slate; filled lines for {filled} game(s).")
    else:
        print(f"{sport} {date_str}: a slate already exists; left as is.")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sport, dates = sys.argv[1], sys.argv[2:] or [today_et_str()]
    session = espn.make_session()
    for d in dates:
        run(session, sport, d)


if __name__ == "__main__":
    main()
