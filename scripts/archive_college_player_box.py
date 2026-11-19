#!/usr/bin/env python3
"""College player box scores for the "Matchup by position" view on NCAAB and
CFB cards (the NBA/NFL version is archive_nba_player_box.py /
archive_nfl_player_box.py).

College has too many teams to save every game, so this keeps every finished
game this season that involves a team that has been on one of our slates for
that sport (data/<sport>/): what those teams' defenses allowed, and their own
players' lines. The league average comes from the same saved games.
Games come from data/raw/schedule/<sport>.json (archive_schedule.py, with ESPN
event ids); each is fetched once, at most MAX_FETCH a run per sport.

Writes data/raw/ncaab_player_box.json, same rows as the NBA file:
  {event id: {"date", "away", "home", "players": {team: [[id, name, pos(G/F/C), starter, min, pts, reb, ast, 3pm, None], ...]}}}
and data/raw/cfb_player_box.json, same rows as the NFL file:
  {event id: {"date", "away", "home", "players": {team: [[id, name, pos, cmp, att, pyd, ptd, int, ratt, ryd, rtd, rec, cyd, ctd, 0], ...]}}}
(no targets in college box scores), with positions from ESPN team rosters
(data/raw/cfb_positions.json; box scores carry none). Run in the scoring workflow.
"""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, props, store  # noqa: E402
from score_slate import _same_team  # noqa: E402

RAW = os.path.join(store.REPO_ROOT, "data", "raw")
MAX_FETCH = 250
POS_PATH = os.path.join(RAW, "cfb_positions.json")


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
        return float(str(v).split("-")[0].split("/")[0])
    except (TypeError, ValueError):
        return 0.0


def tracked(sport):
    names = set()
    for _d, doc in store.list_docs(sport):
        for g in doc.get("games", []):
            names.update(t for t in (g.get("away"), g.get("home")) if t)
    return names


def is_tracked(name, names, memo):
    if name not in memo:
        memo[name] = name in names or any(_same_team(name, t) for t in names)
    return memo[name]


def parse_bb(d):
    out, ids = {}, {}
    for t in (d.get("boxscore") or {}).get("players") or []:
        team = (t.get("team") or {}).get("displayName")
        ids[team] = str((t.get("team") or {}).get("id"))
        st = (t.get("statistics") or [{}])[0]
        lab = st.get("labels") or []
        ix = {k: lab.index(k) for k in ("MIN", "PTS", "REB", "AST", "3PT") if k in lab}
        rows = []
        for a in st.get("athletes") or []:
            v = a.get("stats") or []
            if not v or "MIN" not in ix or not _n(v[ix["MIN"]]):
                continue
            at = a.get("athlete") or {}
            rows.append([str(at.get("id")), at.get("displayName"), (at.get("position") or {}).get("abbreviation") or "",
                         1 if a.get("starter") else 0] + [_n(v[ix[k]]) if k in ix else 0.0 for k in ("MIN", "PTS", "REB", "AST", "3PT")] + [None])
        out[team] = rows
    return out, ids


def parse_fb(d):
    out, ids = {}, {}
    for t in (d.get("boxscore") or {}).get("players") or []:
        team = (t.get("team") or {}).get("displayName")
        ids[team] = str((t.get("team") or {}).get("id"))
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
                    r[11], r[12], r[13] = _n(vals.get("REC")), _n(vals.get("YDS")), _n(vals.get("TD"))
        out[team] = [r for r in rows.values() if any(r[3:])]
    return out, ids


def run(sport, session, today):
    path = os.path.join(RAW, f"{sport}_player_box.json")
    data = _load(path)
    names, memo = tracked(sport), {}
    sched = (_load(os.path.join(RAW, "schedule", f"{sport}.json")).get("dates") or {})
    want = []
    for d, rows in sorted(sched.items()):
        if d >= today:
            continue
        for r in rows:
            if len(r) > 4 and r[4] not in data and (is_tracked(r[0], names, memo) or is_tracked(r[1], names, memo)):
                want.append((d, r))
    pos = _load(POS_PATH) if sport == "cfb" else {}
    team_ids, added, skipped = {}, 0, 0
    for d, r in want[:MAX_FETCH]:
        try:
            j = session.get(f"https://site.api.espn.com/apis/site/v2/sports/{props.espn_path(sport)}/summary?event={r[4]}", timeout=25).json()
        except Exception as exc:  # noqa: BLE001
            print(f"{sport} {r[4]}: {exc.__class__.__name__}")
            continue
        comp = ((j.get("header") or {}).get("competitions") or [{}])[0]
        if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
            skipped += 1
            continue
        players, ids = (parse_bb if sport == "ncaab" else parse_fb)(j)
        if len(players) != 2:
            skipped += 1
            continue
        team_ids.update(ids)
        data[r[4]] = {"date": d, "away": r[0], "home": r[1], "players": players}
        added += 1
    if sport == "cfb":
        # positions: each team's roster once (box scores carry none)
        have_team = set(pos.get("_teams") or [])
        for team, tid in sorted(team_ids.items()):
            if tid in have_team:
                continue
            try:
                for pid, _name, p in props.team_roster(session, "cfb", tid):
                    pos[pid] = p
                have_team.add(tid)
            except Exception as exc:  # noqa: BLE001
                print(f"roster {team}: {exc.__class__.__name__}")
        pos["_teams"] = sorted(have_team)
        _save(POS_PATH, pos)
        for e in data.values():
            for rows in e["players"].values():
                for row in rows:
                    row[2] = pos.get(row[0], row[2])
    if added or sport == "cfb":
        _save(path, data)
    print(f"{sport}: {len(data)} games saved (+{added}, {len(want) - added - skipped} still to fetch); {len(names)} slate teams")


def main():
    session = espn.make_session()
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    for sport in [a for a in sys.argv[1:] if a in ("ncaab", "cfb")] or ["ncaab", "cfb"]:
        run(sport, session, today)


if __name__ == "__main__":
    main()
