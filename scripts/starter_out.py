#!/usr/bin/env python3
"""Starter-out alert (the user's ask, 2026-11-19): for each NBA and NFL game
that hasn't started, which regular starters ESPN's injury report lists as Out
(or questionable / doubtful, as a watch), whether that's news (he played the
team's last game) or an absence the line has had time to price, the line's
move since it opened (ESPN pickcenter, DraftKings), and the teammates at his
position who should pick up his role: their numbers with him and in this
season's games without him.

Also writes `injuries` on each game: {"away": {athlete id: status}, "home": ...}
for everyone listed out or questionable/doubtful/day-to-day, which the matchup
view (lib/nba_dvp.py / nfl_dvp.py) uses to drop out players and re-weight the
offense's positions.

Writes `starterOut` on each game (repo-owned in sync_ledger.py):
  {"checked": ISO time, "line": {"open": home spread, "now": home spread},
   "away": [entry, ...], "home": [entry, ...]}
  entry: {"player", "pos", "status", "out": bool, "lastGame": bool, "missed": n,
          "avg": [games, stats...], "gainers": [{"player", "pos", "with": [games, stats...],
                                                  "without": [games, stats...]}, ...]}
  stats NBA: min, pts, reb, ast, 3pm; NFL QB: att, pass yds, pass TD, rush yds;
  RB: carries, rush yds, rec, rec yds; WR/TE: targets, rec, rec yds, TD.
A game's field is left as it was once the game starts, so a past slate shows
what was known at tip-off / kickoff. Context only, never a pick.

Box scores: data/raw/nba_player_box.json (archive_nba_player_box.py) and
data/raw/nfl_player_box.json (archive_nfl_player_box.py).
Usage: starter_out.py [nba] [nfl] [mlb]   (default all)
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import espn, props, store  # noqa: E402
from lib.picks import is_final  # noqa: E402
from score_slate import _same_team  # noqa: E402

ET = ZoneInfo("America/New_York")
RAW = os.path.join(store.REPO_ROOT, "data", "raw")
AHEAD = {"nba": 1, "nfl": 4, "mlb": 1}   # slate dates looked at: today .. today + N days
# MLB (2026-11-24): only `injuries` is written (for the Team strength box's
# offense adjustment, lib/team_strength.py); no starter alerts.
OUTISH = {"out", "injured reserve", "suspension", "suspended"}
WATCH = {"questionable", "doubtful", "day-to-day", "game time decision", "gtd"}
NBA_GROUP = {"PG": ("PG", "SG"), "SG": ("SG", "PG", "SF"), "SF": ("SF", "SG", "PF"),
             "PF": ("PF", "SF", "C"), "C": ("C", "PF")}
NFL_SLOTS = {"QB": 1, "RB": 1, "WR": 2, "TE": 1}
NFL_MIN_USE = {"QB": 15, "RB": 8, "WR": 4, "TE": 3}
# NFL row: [id, name, pos, cmp, att, pyd, ptd, int, ratt, ryd, rtd, rec, cyd, ctd, tgt]
NFL_STATS = {"QB": lambda r: [r[4], r[5], r[6], r[9]], "RB": lambda r: [r[8], r[9], r[11], r[12]],
             "WR": lambda r: [r[14], r[11], r[12], r[13]]}
NFL_STATS["TE"] = NFL_STATS["WR"]
NFL_USE = {"QB": lambda r: r[4], "RB": lambda r: r[8] + r[11], "WR": lambda r: r[14], "TE": lambda r: r[14]}


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _avg(rows, f):
    if not rows:
        return None
    vals = [f(r) for r in rows]
    return [len(rows)] + [round(sum(v[i] for v in vals) / len(vals), 1) for i in range(len(vals[0]))]


class Team:
    """One team's season from the box file: games in order, each {pid: row}."""

    def __init__(self, games):
        self.games = games            # [(date, {pid: row})], oldest first
        self.names = {}
        for _d, rows in games:
            for pid, r in rows.items():
                self.names[pid] = r[1]

    def played(self, pid):
        return [rows[pid] for _d, rows in self.games if pid in rows]

    def missed_run(self, pid):
        n = 0
        for _d, rows in reversed(self.games):
            if pid in rows:
                break
            n += 1
        return n

    def with_without(self, star, mate):
        w = [rows[mate] for _d, rows in self.games if mate in rows and star in rows]
        wo = [rows[mate] for _d, rows in self.games if mate in rows and star not in rows]
        return w, wo


def teams_from_box(sport, before):
    box = _load(os.path.join(RAW, f"{sport}_player_box.json"))
    by = defaultdict(list)
    for _eid, e in sorted(box.items(), key=lambda kv: kv[1].get("date", "")):
        if e.get("date", "") >= before:
            continue
        for team, rows in (e.get("players") or {}).items():
            by[team].append((e["date"], {r[0]: r for r in rows}))
    return {t: Team(g) for t, g in by.items()}


def find(teams, name):
    return next((teams[t] for t in teams if t == name), None) or next((teams[t] for t in teams if _same_team(t, name)), None)


# ---------------------------------------------------------------- NBA
def nba_positions(before):
    from lib import nba_dvp
    box, heights = nba_dvp._load()
    return nba_dvp.derive_positions([g for g in box if g[0] < before], heights)


def nba_starters(team):
    """Regular starters: started half of the team's last 10 games, or 60%+ of
    the games he played this season (3+ games) -- that keeps a starter who has
    been out a while."""
    last10 = team.games[-10:]
    cnt = defaultdict(int)
    for _d, rows in last10:
        for pid, r in rows.items():
            cnt[pid] += r[3]
    out = {pid for pid, c in cnt.items() if c >= max(1, len(last10) / 2)}
    for pid in team.names:
        p = team.played(pid)
        if len(p) >= 3 and sum(r[3] for r in p) >= 0.6 * len(p) and sum(r[4] for r in p) / len(p) >= 20:
            out.add(pid)
    return out


NBA_F = lambda r: [r[4], r[5], r[6], r[7], r[8]]   # noqa: E731  min, pts, reb, ast, 3pm


def nba_entry(team, pid, pos_of, status, out_tonight):
    P = pos_of.get(pid, "")
    mates = []
    for m in team.names:
        if m == pid or m in out_tonight or pos_of.get(m) not in NBA_GROUP.get(P, ()):
            continue
        w, wo = team.with_without(pid, m)
        if len(w) + len(wo) < 2:
            continue
        aw, awo = _avg(w, NBA_F), _avg(wo, NBA_F)
        gain = (awo[1] - aw[1]) if aw and awo else -99
        mates.append((gain, (aw or [0, 0])[1], m, aw, awo))
    mates.sort(key=lambda x: (-x[0], -x[1]))
    gainers = [{"player": team.names[m], "pos": pos_of.get(m, ""), "with": aw, "without": awo} for _g, _mn, m, aw, awo in mates[:3]]
    return {"player": team.names[pid], "pos": P, "status": status.title(), "out": status in OUTISH,
            "lastGame": bool(team.games and pid in team.games[-1][1]), "missed": team.missed_run(pid),
            "avg": _avg(team.played(pid), NBA_F), "gainers": gainers}


# ---------------------------------------------------------------- NFL
def nfl_starters(team):
    """{pid: pos}: by position, the top players by usage a game (2+ games,
    a floor per position) -- QB1, RB1, WR1-2, TE1."""
    out = {}
    by = defaultdict(list)
    for pid in team.names:
        p = team.played(pid)
        P = p[-1][2] if p else ""
        P = "RB" if P == "FB" else P
        if P not in NFL_SLOTS or len(p) < 2:
            continue
        use = sum(NFL_USE[P](r) for r in p) / len(p)
        if use >= NFL_MIN_USE[P]:
            by[P].append((use, pid))
    for P, lst in by.items():
        for _u, pid in sorted(lst, reverse=True)[:NFL_SLOTS[P]]:
            out[pid] = P
    return out


def nfl_entry(team, pid, P, status, out_tonight):
    f = NFL_STATS[P]
    mates = []
    for m in team.names:
        p = team.played(m)
        mp = "RB" if (p and p[-1][2] == "FB") else (p[-1][2] if p else "")
        if m == pid or m in out_tonight or mp != P:
            continue
        w, wo = team.with_without(pid, m)
        if len(w) + len(wo) < 2:
            continue
        aw, awo = _avg(w, f), _avg(wo, f)
        use = lambda a: a[1] if a else 0  # noqa: E731
        mates.append((use(awo) - use(aw) if awo else -99, use(aw), m, aw, awo))
    mates.sort(key=lambda x: (-x[0], -x[1]))
    gainers = [{"player": team.names[m], "pos": P, "with": aw, "without": awo} for _g, _u, m, aw, awo in mates[:2 if P == "QB" else 3]]
    return {"player": team.names[pid], "pos": P, "status": status.title(), "out": status in OUTISH,
            "lastGame": bool(team.games and pid in team.games[-1][1]), "missed": team.missed_run(pid),
            "avg": _avg(team.played(pid), f), "gainers": gainers}


# ---------------------------------------------------------------- shared
def summary(session, sport, eid):
    try:
        return session.get(f"https://site.api.espn.com/apis/site/v2/sports/{props.espn_path(sport)}/summary?event={eid}",
                           timeout=25).json()
    except Exception:  # noqa: BLE001
        return None


def _num(v):
    try:
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return None


def line_move(d):
    ps = ((d.get("pickcenter") or [{}])[0].get("pointSpread") or {}).get("home") or {}
    o, c = _num((ps.get("open") or {}).get("line")), _num((ps.get("close") or {}).get("line"))
    return {"open": o, "now": c} if o is not None or c is not None else None


def run(sport, session):
    today = datetime.now(ET).date()
    dates = [(today + timedelta(days=i)).isoformat() for i in range(AHEAD[sport] + 1)]
    teams = teams_from_box(sport, today.isoformat())
    pos_of = nba_positions(today.isoformat()) if sport == "nba" else {}
    boards = {}
    changed = 0
    for date_str in dates:
        doc = store.read_doc(sport, date_str)
        if not doc or not doc.get("games"):
            continue
        dirty = False
        for g in doc["games"]:
            if is_final(doc, g):
                continue
            if date_str not in boards:
                try:
                    boards[date_str] = session.get(f"https://site.api.espn.com/apis/site/v2/sports/{props.espn_path(sport)}/scoreboard"
                                                   f"?dates={date_str.replace('-', '')}&limit=1000", timeout=25).json().get("events", [])
                except Exception as exc:  # noqa: BLE001
                    print(f"{sport} {date_str}: {exc.__class__.__name__}")
                    boards[date_str] = []
            eid = None
            for ev in boards[date_str]:
                t = {c["homeAway"]: c["team"]["displayName"] for c in ev["competitions"][0]["competitors"]}
                if _same_team(t.get("away", ""), g.get("away", "")) and _same_team(t.get("home", ""), g.get("home", "")):
                    eid = str(ev["id"])
                    break
            if not eid:
                continue
            d = summary(session, sport, eid)
            if not d:
                continue
            state = (((d.get("header") or {}).get("competitions") or [{}])[0].get("status") or {}).get("type", {}).get("state")
            if state and state != "pre":
                continue          # started: keep what was known before it
            inj = {}
            for t in d.get("injuries") or []:
                for i in t.get("injuries") or []:
                    a = i.get("athlete") or {}
                    inj.setdefault((t.get("team") or {}).get("displayName"), {})[str(a.get("id"))] = str(i.get("status", "")).lower()
            res = {"checked": datetime.now(timezone.utc).isoformat(timespec="seconds"), "line": line_move(d)}
            any_ = False
            # every player on the report as out or doubtful-ish, for the matchup view's adjustment
            injuries = {}
            for side in ("away", "home"):
                st = next((v for k, v in inj.items() if k and _same_team(k, g.get(side, ""))), {})
                injuries[side] = {pid: s for pid, s in st.items() if s in OUTISH or s in WATCH}
            if injuries != (g.get("injuries") or {}):
                if injuries["away"] or injuries["home"]:
                    g["injuries"] = injuries
                else:
                    g.pop("injuries", None)
                dirty = True
            for side in ("away", "home"):
                team = find(teams, g.get(side))
                st = next((v for k, v in inj.items() if k and _same_team(k, g.get(side, ""))), {})
                rows = []
                if team and st:
                    out_tonight = {pid for pid, s in st.items() if s in OUTISH}
                    if sport == "nba":
                        for pid in nba_starters(team):
                            s = st.get(pid)
                            if s and (s in OUTISH or s in WATCH):
                                rows.append(nba_entry(team, pid, pos_of, s, out_tonight))
                    else:
                        for pid, P in nfl_starters(team).items():
                            s = st.get(pid)
                            if s and (s in OUTISH or s in WATCH):
                                rows.append(nfl_entry(team, pid, P, s, out_tonight))
                rows.sort(key=lambda e: (not e["out"], not e["lastGame"], -(e["avg"] or [0, 0])[1]))
                res[side] = rows
                any_ = any_ or bool(rows)
            new = res if any_ else None
            old = g.get("starterOut")
            if (old or {}).get("away") != (new or {}).get("away") or (old or {}).get("home") != (new or {}).get("home") \
                    or (old or {}).get("line") != (new or {}).get("line"):
                if new:
                    g["starterOut"] = new
                else:
                    g.pop("starterOut", None)
                dirty = True
                changed += 1
        if dirty:
            store.write_doc(sport, date_str, doc)
    print(f"{sport}: starter-out alerts changed on {changed} game(s)")


def main():
    sports = [a for a in sys.argv[1:] if a in AHEAD] or list(AHEAD)
    session = espn.make_session()
    for sport in sports:
        run(sport, session)


if __name__ == "__main__":
    main()
