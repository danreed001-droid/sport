#!/usr/bin/env python3
"""Closing 3-way moneylines for finished soccer matches, for the candle chart's
"Moneyline" view (soccer has no spread, so the moneyline stands in for ATS;
the user's call, 2026-11-23).

Reads data/raw/schedule/soccer.json (archive_schedule.py) and, for every
finished match not saved yet, the match's ESPN summary (soccer/all, by event
id): pickcenter's first provider (DraftKings) home / away / draw moneylines.
Writes data/raw/soccer_odds.json: {event id: [home ML, away ML, draw ML]}, or
null when ESPN has no odds for it (looked at once, not again). At most
MAX_FETCH matches a run (the first run backfills the season over a few runs).
Run in the scoring workflow after archive_schedule.py.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, store  # noqa: E402

SCHED = os.path.join(store.REPO_ROOT, "data", "raw", "schedule", "soccer.json")
OUT = os.path.join(store.REPO_ROOT, "data", "raw", "soccer_odds.json")
URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary?event={}"
MAX_FETCH = int(os.environ.get("SOCCER_ODDS_MAX", "400"))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def moneylines(summary):
    """[home, away, draw] American odds from a summary's pickcenter, else None."""
    for pc in summary.get("pickcenter") or []:
        h = _num((pc.get("homeTeamOdds") or {}).get("moneyLine"))
        a = _num((pc.get("awayTeamOdds") or {}).get("moneyLine"))
        d = _num((pc.get("drawOdds") or {}).get("moneyLine"))
        if h is not None and a is not None:
            return [h, a, d]
    return None


def main():
    try:
        with open(SCHED, encoding="utf-8") as f:
            dates = json.load(f).get("dates") or {}
    except (OSError, ValueError):
        print("no soccer schedule saved")
        return
    try:
        with open(OUT, encoding="utf-8") as f:
            have = json.load(f)
    except (OSError, ValueError):
        have = {}
    todo = [r[4] for d in sorted(dates, reverse=True) for r in dates[d]
            if len(r) > 6 and r[5] is not None and str(r[4]) not in have]
    session = espn.make_session()
    got = 0
    for eid in todo[:MAX_FETCH]:
        try:
            s = session.get(URL.format(eid), timeout=25).json()
        except Exception as exc:  # noqa: BLE001
            print(f"{eid}: {exc.__class__.__name__}")
            continue
        have[str(eid)] = moneylines(s)
        got += 1
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(have, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")
    print(f"soccer odds: {got} fetched, {len(todo) - got} still to fetch, "
          f"{sum(1 for v in have.values() if v)} of {len(have)} saved with a moneyline")


if __name__ == "__main__":
    main()
