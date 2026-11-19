#!/usr/bin/env python3
"""Every NBA player's box-score line this season, for the pick sheet's
"Matchup by position" view (what each defense allows to each position).

Writes data/raw/nba_player_box.json:
  {event id: {"date", "away", "home",
              "players": {team: [[athlete id, name, pos, starter, min, pts, reb, ast, 3pm, +/-], ...]}}}
`pos` is ESPN's G/F/C (ESPN no longer splits guards and forwards; the site
derives PG/SG/SF/PF itself, see `nba_positions` in build_site.py). Each final
regular-season game is fetched once. Run in the scoring workflow.
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, store  # noqa: E402

OUT = os.path.join(store.REPO_ROOT, "data", "raw", "nba_player_box.json")
SCORES = os.path.join(store.REPO_ROOT, "data", "raw", "master_nba_scores.csv")
SEASON_START = "2026-10-20"   # regular season


def _n(v):
    try:
        return float(str(v).split("-")[0])
    except (TypeError, ValueError):
        return 0.0


def _pm(v):
    try:
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return None


def _old(e):
    """A game saved before +/- was kept (rows of 9) gets fetched again."""
    return any(len(r) < 10 for rows in (e.get("players") or {}).values() for r in rows)


def fetch(session, eid):
    d = session.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={eid}", timeout=25).json()
    comp = ((d.get("header") or {}).get("competitions") or [{}])[0]
    if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
        return None
    if ((d.get("header") or {}).get("season") or {}).get("type") not in (2, None):
        return {"skip": "not regular season"}
    out = {}
    for t in (d.get("boxscore") or {}).get("players") or []:
        team = (t.get("team") or {}).get("displayName")
        st = (t.get("statistics") or [{}])[0]
        lab = st.get("labels") or []
        ix = {k: lab.index(k) for k in ("MIN", "PTS", "REB", "AST", "3PT", "+/-") if k in lab}
        rows = []
        for a in st.get("athletes") or []:
            v = a.get("stats") or []
            if not v or "MIN" not in ix or not _n(v[ix["MIN"]]):
                continue   # didn't play
            at = a.get("athlete") or {}
            rows.append([str(at.get("id")), at.get("displayName"), (at.get("position") or {}).get("abbreviation") or "",
                         1 if a.get("starter") else 0] + [_n(v[ix[k]]) if k in ix else 0.0 for k in ("MIN", "PTS", "REB", "AST", "3PT")]
                        + [_pm(v[ix["+/-"]]) if "+/-" in ix else None])
        out[team] = rows
    return {"players": out}


def main():
    try:
        with open(OUT, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    with open(SCORES, encoding="utf-8") as f:
        games = [r for r in csv.DictReader(f) if r.get("Status", "").startswith("Final") and r.get("Date", "") >= SEASON_START]
    session = espn.make_session()
    added = 0
    for r in games:
        eid = r["Game_ID"]
        if eid in data and not _old(data[eid]):
            continue
        try:
            e = fetch(session, eid)
        except Exception as exc:  # noqa: BLE001
            print(f"{eid}: {exc.__class__.__name__}")
            continue
        if e is None:
            continue
        e.update(date=r["Date"], away=r["Away_Team"], home=r["Home_Team"])
        data[eid] = e
        added += 1
    # Heights split forwards into SF / PF (lib/nba_dvp.py): look new forwards up once.
    try:
        from lib import nba_heights
        known = nba_heights._load() if hasattr(nba_heights, "_load") else {}
        for e in data.values():
            for rows in (e.get("players") or {}).values():
                for row in rows:
                    if row[2] == "F" and str(row[0]) not in known:
                        nba_heights.height(session, str(row[0]))
        nba_heights.save()
    except Exception as exc:  # noqa: BLE001
        print(f"heights: {exc.__class__.__name__}")
    if added:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            f.write("\n")
    print(f"NBA player box scores: {len(data)} games (+{added})")


if __name__ == "__main__":
    main()
