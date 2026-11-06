"""Put each game's over/under line on today's and tomorrow's slates (US
Eastern), for the pick sheet's Over/Under picks: gameTotal (the total) and
gameTotalOverOdds / gameTotalUnderOdds, from ESPN's pickcenter (DraftKings).

Refreshed every run while a game hasn't started, then left as it was, so a
started game keeps its last pre-game line. The user's O/U pick is locked at
the line on the slate when they submit it (scripts/intake_picks.py), so this
only sets what the pick sheet offers. sync_ledger.py treats these fields as
repo-owned, so a database sync never drops them.

    python scripts/slate_totals.py [sport ...]   (default: every sport but epl)
"""
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, sports, store  # noqa: E402
from score_slate import _same_team  # noqa: E402

FIELDS = ("gameTotal", "gameTotalOverOdds", "gameTotalUnderOdds")


def pickcenter_total(session, cfg, event_id):
    try:
        d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/{cfg['espn_sport']}/{cfg['espn_league']}"
                        f"/summary?event={event_id}", timeout=20).json()
    except Exception:
        return {}
    pc = (d.get("pickcenter") or [{}])[0]
    if not isinstance(pc, dict):
        return {}
    out = {"gameTotal": espn.fmt_num(pc.get("overUnder")),
           "gameTotalOverOdds": espn.fmt_ml(pc.get("overOdds")), "gameTotalUnderOdds": espn.fmt_ml(pc.get("underOdds"))}
    return {k: v for k, v in out.items() if v is not None}


def run(sport_key, date_str, session):
    cfg = sports.SPORTS[sport_key]
    doc = store.read_doc(cfg["collection"], date_str)
    if not doc:
        return
    key = "matches" if "matches" in doc else "games"
    try:
        events = espn.fetch_scoreboard(session, cfg["espn_sport"], cfg["espn_league"], date_str.replace("-", ""))
    except Exception as e:  # noqa: BLE001
        print(f"  {sport_key} {date_str}: ESPN scoreboard failed ({e}) -- lines left as they were.")
        return
    evs = []
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): (c.get("team") or {}).get("displayName") for c in comp.get("competitors", [])}
        evs.append((ev.get("id"), teams.get("away"), teams.get("home"), ((comp.get("status") or {}).get("type") or {}).get("state")))
    changed = set_lines = 0
    for g in doc.get(key, []):
        ev = next((e for e in evs if e[1] and e[2] and _same_team(g.get("away"), e[1]) and _same_team(g.get("home"), e[2])), None)
        if ev is None or ev[3] != "pre":
            continue  # not found, or started: keep the last pre-game line
        line = pickcenter_total(session, cfg, ev[0])
        if line.get("gameTotal") is None:
            continue
        set_lines += 1
        before = {k: g.get(k) for k in FIELDS}
        g.update(line)
        if {k: g.get(k) for k in FIELDS} != before:
            changed += 1
    if changed:
        store.write_doc(cfg["collection"], date_str, doc)
    print(f"  {sport_key} {date_str}: over/under lines on {set_lines} upcoming game(s), {changed} changed.")


def main():
    wanted = sys.argv[1:] or [k for k in sports.SPORTS if k != "epl"]
    today = datetime.now(ZoneInfo("America/New_York")).date()
    session = espn.make_session()
    for sport_key in wanted:
        for d in (today, today + timedelta(days=1)):
            run(sport_key, d.isoformat(), session)


if __name__ == "__main__":
    main()
