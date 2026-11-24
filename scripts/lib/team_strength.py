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
it isn't in here), soccer .24 (2,762). ESPN's summaries carry no soccer injury
report and MLB has no player box archive, so nobody is taken off for injuries.
"""
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIN_GAMES = {"mlb": 10, "soccer": 4}
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


def _same(a, b):
    from score_slate import _same_team
    return a == b or _same_team(a, b)


def for_slate(slate_date, games_today, sport):
    """{game id: {"away": side, "home": side, "lg": runs/goals a team game}};
    a side is {"off", "dfn", "overall", "ppg", "papg", "gp"} (percent vs the league)."""
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
            out[sd] = {"off": round(off, 1), "dfn": round(dfn, 1), "overall": round(off + dfn, 1),
                       "ppg": round(ppg, 2), "papg": round(papg, 2), "gp": len(pf[me])}
        if out.get("away") or out.get("home"):
            res[gid] = out
    return res
