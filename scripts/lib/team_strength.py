"""Team strength for sports without a matchup-by-position view (MLB, soccer):
the overall grade of lib/nba_dvp.py without the position part -- each offense's
runs/goals a game vs the league plus what tonight's opponent allows a game vs
the league (the user's ask, 2026-11-24: "do all sports").

From data/raw/schedule/<sport>.json (archive_schedule.py's final scores), this
season's games before the slate's date. Soccer's "league" is every club in the
saved competitions (SOCCER_LEAGUES), so a club in a high-scoring league looks a
little stronger; adjusting for each team's opponents predicted no better.
Predicting a team's runs/goals (correlation, 2026 seasons, before-the-game
data): MLB .10 (4,634 team-games: tonight's starting pitcher matters more, and
it isn't in here), soccer .24 (2,762). ESPN has no soccer injury report.

MLB injuries (the user's ask, 2026-11-24): hitters on ESPN's injury report as
out (the game's `injuries`, from starter_out.py) come off the offense: each
one's (runs + RBI) / 2 a team game, from data/raw/mlb_player_box.json
(archive_mlb_player_box.py), at OUT_KEEP (see below). Pitchers aren't counted.
"""
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIN_GAMES = {"mlb": 10, "soccer": 4}
OUTISH = {"out", "injured reserve", "suspension", "suspended"}
# 2026 (4,484 team-games): a regular missing 3-30 straight games (IL-like) cost
# about 0.16 of his (R + RBI) / 2 a game (0.44 missing: -0.07 runs; 0.77:
# -0.16); missing on a rest day cost nothing measurable (+0.07). Noisy (runs
# swing ~3 a game), so 0.15.
OUT_KEEP = {"mlb": 0.15}
_CACHE = {}


def _season_start(sport, slate_date):
    y, m = int(slate_date[:4]), int(slate_date[5:7])
    if sport == "mlb":
        return f"{y}-03-25"
    return f"{y if m >= 7 else y - 1}-07-01"     # soccer: European seasons start in August


def _dates(sport):
    if sport not in _CACHE:
        try:
            with open(os.path.join(ROOT, "data", "raw", "schedule", sport + ".json"), encoding="utf-8") as f:
                _CACHE[sport] = json.load(f).get("dates") or {}
        except (OSError, ValueError):
            _CACHE[sport] = {}
    return _CACHE[sport]


def _mlb_hitters(slate_date, start):
    """{team: (team games, {pid: [name, games, (R + RBI) / 2 total]})} and each hitter's last team."""
    key = ("bat", slate_date)
    if key in _CACHE:
        return _CACHE[key]
    try:
        with open(os.path.join(ROOT, "data", "raw", "mlb_player_box.json"), encoding="utf-8") as f:
            box = json.load(f)
    except (OSError, ValueError):
        box = {}
    tg, hit, last = defaultdict(int), defaultdict(dict), {}
    for e in sorted(box.values(), key=lambda e: e.get("date") or ""):
        d = e.get("date") or ""
        if d < start or d >= slate_date:
            continue
        for team, rows in (e.get("bat") or {}).items():
            tg[team] += 1
            for r in rows:
                x = hit[team].setdefault(r[0], [r[1], 0, 0.0])
                x[1] += 1
                x[2] += (r[5] + r[7]) / 2
                last[r[0]] = team
    _CACHE[key] = ({t: (tg[t], hit[t]) for t in tg}, last)
    return _CACHE[key]


def _same(a, b):
    from score_slate import _same_team
    return a == b or _same_team(a, b)


def for_slate(slate_date, games_today, sport, injuries=None):
    """{game id: {"away": side, "home": side, "lg": runs/goals a team game}};
    a side is {"off", "dfn", "overall", "ppg", "papg", "gp"} (percent vs the league),
    plus "offBase", "offLost", "out" ([name, runs a team game]) when hitters are out."""
    dates = _dates(sport)
    start = _season_start(sport, slate_date)
    pf, pa = defaultdict(list), defaultdict(list)
    for d in sorted(dates):
        if d < start or d >= slate_date:
            continue
        for r in dates[d]:
            if len(r) > 6 and r[5] is not None and r[6] is not None:
                a, h, sa, sh = r[0], r[1], float(r[5]), float(r[6])
                pf[a].append(sa); pa[a].append(sh)
                pf[h].append(sh); pa[h].append(sa)
    tot = [x for v in pf.values() for x in v]
    if not tot or not games_today:
        return {}
    lg = sum(tot) / len(tot)
    mn = MIN_GAMES.get(sport, 5)

    def pick(name):
        if name in pf:
            return name
        hits = [t for t in pf if _same(t, name or "")]
        return max(hits, key=lambda t: len(pf[t])) if hits else None

    hitters, last = _mlb_hitters(slate_date, start) if sport == "mlb" and injuries else ({}, {})

    def lost_to(team, inj):
        """Runs a game taken off for this team's hitters listed out."""
        hits = [t for t in hitters if t == team] or [t for t in hitters if _same(t, team or "")]
        if not hits or not inj:
            return 0.0, []
        t = hits[0]
        n, players = hitters[t]
        gone = []
        for pid, st in inj.items():
            x = players.get(pid)
            if st in OUTISH and x and last.get(pid) == t and n:
                gone.append([x[0], round(x[2] / n, 2)])
        return OUT_KEEP.get(sport, 0) * sum(g[1] for g in gone), sorted(gone, key=lambda g: -g[1])

    res = {}
    for gid, away, home in games_today:
        ta, th = pick(away), pick(home)
        out = {"lg": round(lg, 2)}
        for sd, me, op in (("away", ta, th), ("home", th, ta)):
            if not me or not op or len(pf[me]) < mn or len(pa[op]) < mn:
                out[sd] = None
                continue
            ppg, papg = sum(pf[me]) / len(pf[me]), sum(pa[op]) / len(pa[op])
            off, dfn = 100 * (ppg / lg - 1), 100 * (papg / lg - 1)
            side = {"off": round(off, 1), "dfn": round(dfn, 1), "overall": round(off + dfn, 1),
                    "ppg": round(ppg, 2), "papg": round(papg, 2), "gp": len(pf[me])}
            lost, gone = lost_to(me, ((injuries or {}).get(gid) or {}).get(sd))
            if gone:
                side["out"] = gone
            if lost >= 0.01:
                side["offBase"], side["offLost"] = side["off"], round(lost, 2)
                side["off"] = round(off - 100 * lost / lg, 1)
                side["overall"] = round(side["off"] + dfn, 1)
            out[sd] = side
        if out.get("away") or out.get("home"):
            res[gid] = out
    return res
