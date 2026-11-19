#!/usr/bin/env python3
"""Every NFL player's offensive box-score line this season, for the pick
sheet's "Matchup by position" view on NFL cards (what each defense allows to
quarterbacks, running backs, receivers and tight ends).

Writes data/raw/nfl_player_box.json:
  {event id: {"date", "week", "away", "home",
              "players": {team: [[athlete id, name, pos, cmp, att, pass yds, pass td, int,
                                  rush att, rush yds, rush td, rec, rec yds, rec td, targets], ...]}}}
and data/raw/nfl_positions.json ({athlete id: "QB"/"RB"/"WR"/"TE"/...}) from ESPN
team rosters (box scores carry no positions); a player not on any roster is
looked up once on his ESPN athlete page. Each final regular-season game is
fetched once. Run in the scoring workflow.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, store  # noqa: E402

OUT = os.path.join(store.REPO_ROOT, "data", "raw", "nfl_player_box.json")
POS_PATH = os.path.join(store.REPO_ROOT, "data", "raw", "nfl_positions.json")
BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"


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


def _n(v):
    try:
        return float(str(v).split("/")[0])
    except (TypeError, ValueError):
        return 0.0


def season_year(now=None):
    now = now or datetime.now(timezone.utc)
    return now.year if now.month >= 8 else now.year - 1


def fetch(session, eid):
    d = session.get(f"{BASE}/summary?event={eid}", timeout=25).json()
    out = {}
    for t in (d.get("boxscore") or {}).get("players") or []:
        team = (t.get("team") or {}).get("displayName")
        rows = {}
        for st in t.get("statistics") or []:
            cat, lab = st.get("name"), st.get("labels") or []
            for a in st.get("athletes") or []:
                at, v = a.get("athlete") or {}, a.get("stats") or []
                if not at.get("id") or not v:
                    continue
                vals = dict(zip(lab, v))
                r = rows.setdefault(str(at["id"]), [str(at["id"]), at.get("displayName"), ""] + [0.0] * 12)
                if cat == "passing":
                    ca = str(vals.get("C/ATT", "0/0")).split("/")
                    r[3], r[4] = _n(ca[0]), _n(ca[1] if len(ca) > 1 else 0)
                    r[5], r[6], r[7] = _n(vals.get("YDS")), _n(vals.get("TD")), _n(vals.get("INT"))
                elif cat == "rushing":
                    r[8], r[9], r[10] = _n(vals.get("CAR")), _n(vals.get("YDS")), _n(vals.get("TD"))
                elif cat == "receiving":
                    r[11], r[12], r[13], r[14] = _n(vals.get("REC")), _n(vals.get("YDS")), _n(vals.get("TD")), _n(vals.get("TGTS"))
        out[team] = [r for r in rows.values() if any(r[3:])]
    return out


def main():
    session = espn.make_session()
    data, pos = _load(OUT), _load(POS_PATH)
    year, added = season_year(), 0
    for week in range(1, 19):
        try:
            evs = session.get(f"{BASE}/scoreboard?seasontype=2&week={week}&dates={year}", timeout=25).json().get("events", [])
        except Exception as exc:  # noqa: BLE001
            print(f"week {week}: {exc.__class__.__name__}")
            continue
        for ev in evs:
            eid = str(ev["id"])
            comp = ev["competitions"][0]
            if eid in data or not ((comp.get("status") or {}).get("type") or {}).get("completed"):
                continue
            try:
                players = fetch(session, eid)
            except Exception as exc:  # noqa: BLE001
                print(f"{eid}: {exc.__class__.__name__}")
                continue
            t = {c["homeAway"]: c["team"]["displayName"] for c in comp["competitors"]}
            data[eid] = {"date": ev["date"][:10], "week": week, "away": t.get("away"), "home": t.get("home"), "players": players}
            added += 1
    # Positions: every team's roster once a run when someone is missing, then athlete pages.
    missing = {r[0] for e in data.values() for rows in e["players"].values() for r in rows if r[0] not in pos}
    if missing:
        try:
            teams = session.get(f"{BASE}/teams", timeout=25).json()["sports"][0]["leagues"][0]["teams"]
            for tm in teams:
                ro = session.get(f"{BASE}/teams/{tm['team']['id']}/roster", timeout=25).json()
                for grp in ro.get("athletes") or []:
                    for a in grp.get("items") or []:
                        pos[str(a["id"])] = ((a.get("position") or {}).get("abbreviation") or "")
        except Exception as exc:  # noqa: BLE001
            print(f"rosters: {exc.__class__.__name__}")
        for pid in sorted(m for m in missing if m not in pos)[:150]:
            try:
                a = session.get(f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/athletes/{pid}", timeout=15).json()
                pos[pid] = (a.get("position") or {}).get("abbreviation") or ""
            except Exception:  # noqa: BLE001
                pass
        _save(POS_PATH, pos)
    for e in data.values():   # stamp positions on the rows
        for rows in e["players"].values():
            for r in rows:
                r[2] = pos.get(r[0], r[2])
    if added or missing:
        _save(OUT, data)
    print(f"NFL player box scores: {len(data)} games (+{added}); positions for {len(pos)} players")


if __name__ == "__main__":
    main()
