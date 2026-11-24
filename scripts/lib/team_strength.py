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
(archive_mlb_player_box.py), at OUT_KEEP (see below).

MLB starting pitchers (the user's ask, 2026-11-24): the opponent's runs allowed
is adjusted for tonight's starter (the game's `probables` from starter_out.py;
a past game without them uses the starter in its box score): his runs allowed
per out as a starter this season, shrunk toward the league's starters by
SP_SHRINK outs, minus his team's starters' rate, times 27 and the share of a
game he usually pitches (his average outs a start / 27). 2026 replay (4,634
team-games, before-the-game data): runs scored vs offense + opponent allowed
r=.095, with the starter .112 (first half .072 -> .097, second .131 -> .132);
on its own a starter's prior runs/9 tracked the runs his opponent scored at .11
(best fifth of starters 3.78 runs, worst fifth 4.92).
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
SP_SHRINK = 60       # outs of league-average starting added to each starter's line
SP_CENTER = 2.4      # the adjustment averaged -2.4% in the 2026 replay (starts go to the better arms): added back
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


def _mlb_pitchers(slate_date, start):
    """Starters this season before the slate: ({pid: [name, outs, runs, starts]},
    {team: [starters' outs, runs, starts]}, league starters' runs per out,
    {(date, away, home): {"away": [pid, name], "home": [...]}} actual starters)."""
    key = ("pit", slate_date)
    if key in _CACHE:
        return _CACHE[key]
    try:
        with open(os.path.join(ROOT, "data", "raw", "mlb_player_box.json"), encoding="utf-8") as f:
            box = json.load(f)
    except (OSError, ValueError):
        box = {}
    sp, team, lg, actual = {}, defaultdict(lambda: [0, 0.0, 0]), [0, 0.0], {}
    for e in sorted(box.values(), key=lambda e: e.get("date") or ""):
        d = e.get("date") or ""
        if d < start:
            continue
        starters = {}
        for t, rows in (e.get("pit") or {}).items():
            r = next((r for r in rows if r[2]), None)
            if r:
                starters[t] = r
        if d == slate_date:
            sides = {sd: starters.get(e.get(sd)) for sd in ("away", "home")}
            actual[(d, e.get("away"), e.get("home"))] = {sd: [r[0], r[1]] for sd, r in sides.items() if r}
            continue
        if d > slate_date:
            continue
        for t, r in starters.items():
            x = sp.setdefault(r[0], [r[1], 0, 0.0, 0])
            x[1] += r[3]
            x[2] += r[5]
            x[3] += 1
            tm = team[t]
            tm[0] += r[3]
            tm[1] += r[5]
            tm[2] += 1
            lg[0] += r[3]
            lg[1] += r[5]
    _CACHE[key] = (sp, dict(team), lg[1] / lg[0] if lg[0] else None, actual)
    return _CACHE[key]


def _same(a, b):
    from score_slate import _same_team
    return a == b or _same_team(a, b)


def for_slate(slate_date, games_today, sport, injuries=None, probables=None):
    """{game id: {"away": side, "home": side, "lg": runs/goals a team game}};
    a side is {"off", "dfn", "overall", "ppg", "papg", "gp"} (percent vs the league),
    plus "offBase", "offLost", "out" ([name, runs a team game]) when hitters are out,
    and for MLB "sp" ({name, starts, ip, ra9, adj}: the opponent's starter, adj = %
    added to "dfn") with "dfnBase" (the opponent's allowed before the starter)."""
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

    sps, steam, lg_rate, actual = _mlb_pitchers(slate_date, start) if sport == "mlb" else ({}, {}, None, {})

    def starter_adj(gid, away, home, sd, team):
        """The pitcher starting for `sd` tonight and how much he moves his team's runs allowed (%)."""
        pr = ((probables or {}).get(gid) or {}).get(sd)
        if not pr:
            act = next((v for (d, a, h), v in actual.items() if _same(a, away or "") and _same(h, home or "")), {})
            pr = act.get(sd)
        if not pr or not lg_rate or not team or team not in steam:
            return None
        tm = steam[team]
        x = sps.get(str(pr[0]))
        outs, runs, starts = (x[1], x[2], x[3]) if x else (0, 0.0, 0)
        rate = (runs + lg_rate * SP_SHRINK) / (outs + SP_SHRINK)
        share = min(27.0, (outs / starts) if starts else tm[0] / max(1, tm[2])) / 27
        adj = 100 * (rate - tm[1] / max(1, tm[0])) * 27 * share / lg + SP_CENTER
        return {"name": pr[1], "starts": starts, "ip": round(outs / 3, 1),
                "ra9": round(27 * runs / outs, 2) if outs else None, "adj": round(adj, 1)}

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
            if sport == "mlb":
                st = starter_adj(gid, away, home, "home" if sd == "away" else "away", op)
                if st:
                    side["sp"] = st
                    side["dfnBase"] = side["dfn"]
                    side["dfn"] = round(dfn + st["adj"], 1)
                    dfn = side["dfn"]
                    side["overall"] = round(side["off"] + dfn, 1)
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
